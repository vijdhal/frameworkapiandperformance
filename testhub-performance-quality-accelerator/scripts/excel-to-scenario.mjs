#!/usr/bin/env node
/**
 * excel-to-scenario.mjs
 * ---------------------------------------------------------------
 * Compiles the Excel test workbook into the JSON that k6 consumes.
 *
 * k6's Goja runtime cannot read .xlsx, so the workbook is the single source of
 * truth (endpoints AND every run parameter) and this script resolves it ahead
 * of the run. Each endpoint owns its workbook and compiles into its own
 * folder — nothing here is shared between endpoints:
 *
 *   <name> sheet (the request rows)
 *                   -> <out-dir>/<name>-scenario.json   (array of request rows)
 *   "profiles" sheet
 *                   -> <out-dir>/profiles.json           ({ <profile>: { options, run } })
 *
 * Usage:
 *   node scripts/excel-to-scenario.mjs --file tests/<name>/<name>.xlsx --out-dir tests/<name>
 *
 * (Prefer `node scripts/new-endpoint.mjs <name>` to scaffold a new endpoint's
 * workbook/payload/test files in one go, or `npm run <name>:gen` once it exists.)
 *
 * ── REQUEST sheet columns (only `endpoint` is required) ────────────────────
 *   name | endpoint | method | authType | headers | payload | payloadFile |
 *   expectedStatus | maxResponseMs | extractField | injectAs | weight
 *
 * ── PROFILES sheet columns (only `profile` is required; blank cells ignored) ─
 *   Execution shape:
 *     profile executor vus startVus duration iterations stages
 *     rate timeUnit preAllocatedVus maxVus
 *     maxDuration gracefulStop gracefulRampDown
 *   Thresholds (composed into options.thresholds):
 *     p90_ms p95_ms p99_ms max_ms avg_ms errorRate checkRate rawThresholds(JSON)
 *   HTTP / engine:
 *     rps maxRedirects userAgent minIterationDuration dns
 *     insecureSkipTLSVerify noConnectionReuse noVuConnectionReuse
 *     throwOnError discardResponseBodies
 *     summaryTrendStats(csv) tags(JSON) hosts(JSON) blockHostnames(csv)
 *     setupTimeout teardownTimeout
 *     rawOptions(JSON)   <- deep-merged LAST; lets ANY k6 option come from Excel
 *   Framework run knobs (emitted under `run`):
 *     scenarioSheet pick think iterationSleep env baseUrl reportName
 *
 *   stages : comma-separated "<duration>:<targetVUs>" pairs, e.g. "30s:20, 1m:50, 30s:0"
 *   bools  : TRUE / FALSE / 1 / 0 / yes / no
 * ---------------------------------------------------------------
 */
import fs from 'fs';
import path from 'path';
import * as XLSX from 'xlsx';

// The ESM build of SheetJS doesn't auto-wire Node's fs.
XLSX.set_fs(fs);

const args = Object.fromEntries(
    process.argv.slice(2).reduce((acc, a, i, arr) => {
        if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
        return acc;
    }, [])
);

const FILE = args.file;
const OUT_DIR = args['out-dir'];
const PROFILE_SHEETS = new Set(['profiles', 'profile', 'config', 'options']);

if (!FILE || !OUT_DIR) {
    console.error('Usage: node scripts/excel-to-scenario.mjs --file tests/<name>/<name>.xlsx --out-dir tests/<name>');
    console.error('       (or `node scripts/new-endpoint.mjs <name>` to scaffold a new endpoint from scratch)');
    process.exit(1);
}

if (!fs.existsSync(FILE)) {
    console.error(`✖ workbook not found: ${FILE}`);
    console.error('  Run `node scripts/new-endpoint.mjs <name>` to create one, or pass --file <path>.');
    process.exit(1);
}

const has = (v) => v !== undefined && v !== null && String(v).trim() !== '';
const num = (v) => Number(String(v).trim());
const csv = (v) => String(v).split(',').map((s) => s.trim()).filter(Boolean);
const bool = (v) => {
    const s = String(v).trim().toLowerCase();
    if (['true', '1', 'yes', 'y'].includes(s)) return true;
    if (['false', '0', 'no', 'n'].includes(s)) return false;
    throw new Error(`expected a boolean (TRUE/FALSE), got "${v}"`);
};

const parseJsonCell = (v, col, sheet) => {
    if (!has(v)) return undefined;
    if (typeof v === 'object') return v;
    try {
        return JSON.parse(String(v));
    } catch (e) {
        throw new Error(`[${sheet}] column "${col}" is not valid JSON: ${String(v)}`);
    }
};

const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
function deepMerge(base, over) {
    if (!isObj(base) || !isObj(over)) return over === undefined ? base : over;
    const out = { ...base };
    for (const [k, v] of Object.entries(over)) {
        out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : v;
    }
    return out;
}

// ── request rows ────────────────────────────────────────────────────────────
const loadPayloadFile = (p, sheet) => {
    if (!has(p)) return undefined;
    const resolved = path.resolve(String(p));
    if (!fs.existsSync(resolved)) throw new Error(`[${sheet}] payloadFile not found: ${p}`);
    return JSON.parse(fs.readFileSync(resolved, 'utf-8'));
};

function normaliseRow(row, sheet) {
    if (!has(row.endpoint)) {
        throw new Error(`[${sheet}] a row is missing "endpoint": ${JSON.stringify(row)}`);
    }
    const payload = loadPayloadFile(row.payloadFile, sheet) ?? parseJsonCell(row.payload, 'payload', sheet);

    const out = {
        name: has(row.name) ? String(row.name) : `${String(row.method || 'GET').toUpperCase()} ${row.endpoint}`,
        endpoint: String(row.endpoint),
        method: String(row.method || 'GET').toUpperCase(),
    };
    if (has(row.authType)) out.authType = String(row.authType);
    const headers = parseJsonCell(row.headers, 'headers', sheet);
    if (headers) out.headers = headers;
    if (payload !== undefined) out.payload = payload;
    if (has(row.expectedStatus)) out.expectedStatus = num(row.expectedStatus);
    if (has(row.maxResponseMs)) out.maxResponseMs = num(row.maxResponseMs);
    if (has(row.extractField)) out.extractField = String(row.extractField);
    if (has(row.injectAs)) out.injectAs = String(row.injectAs);
    if (has(row.weight)) out.weight = num(row.weight);
    return out;
}

// ── profiles ────────────────────────────────────────────────────────────────
function parseStages(spec, sheet) {
    return csv(spec).map((part) => {
        const [duration, target] = part.split(':').map((x) => x.trim());
        if (!has(duration) || !has(target) || Number.isNaN(Number(target))) {
            throw new Error(`[${sheet}] bad stages entry "${part}" — expected "<duration>:<target>" (e.g. 30s:20)`);
        }
        return { duration, target: Number(target) };
    });
}

function buildThresholds(row) {
    const dur = [];
    if (has(row.p90_ms)) dur.push(`p(90)<${num(row.p90_ms)}`);
    if (has(row.p95_ms)) dur.push(`p(95)<${num(row.p95_ms)}`);
    if (has(row.p99_ms)) dur.push(`p(99)<${num(row.p99_ms)}`);
    if (has(row.max_ms)) dur.push(`max<${num(row.max_ms)}`);
    if (has(row.avg_ms)) dur.push(`avg<${num(row.avg_ms)}`);

    let t = {};
    if (dur.length) t.http_req_duration = dur;
    if (has(row.errorRate)) t.http_req_failed = [`rate<${num(row.errorRate)}`];
    if (has(row.checkRate)) t.checks = [`rate>${num(row.checkRate)}`];

    const raw = parseJsonCell(row.rawThresholds, 'rawThresholds', 'profiles');
    if (raw) t = deepMerge(t, raw);
    return t;
}

function buildProfile(row, sheet) {
    if (!has(row.profile)) throw new Error(`[${sheet}] a row is missing "profile": ${JSON.stringify(row)}`);

    const o = {};

    // executor shape
    if (has(row.executor)) o.executor = String(row.executor).trim();
    if (has(row.stages)) {
        o.stages = parseStages(row.stages, sheet);
        if (has(row.startVus)) o.startVUs = num(row.startVus);
    } else if (has(row.iterations)) {
        if (has(row.vus)) o.vus = num(row.vus);
        o.iterations = num(row.iterations);
    } else if (has(row.rate)) {
        o.rate = num(row.rate);
        if (has(row.timeUnit)) o.timeUnit = String(row.timeUnit).trim();
        if (has(row.duration)) o.duration = String(row.duration).trim();
        if (has(row.preAllocatedVus)) o.preAllocatedVUs = num(row.preAllocatedVus);
        if (has(row.maxVus)) o.maxVUs = num(row.maxVus);
    } else {
        if (has(row.vus)) o.vus = num(row.vus);
        if (has(row.duration)) o.duration = String(row.duration).trim();
    }
    if (has(row.maxDuration)) o.maxDuration = String(row.maxDuration).trim();
    if (has(row.gracefulStop)) o.gracefulStop = String(row.gracefulStop).trim();
    if (has(row.gracefulRampDown)) o.gracefulRampDown = String(row.gracefulRampDown).trim();

    // thresholds
    const thresholds = buildThresholds(row);
    if (Object.keys(thresholds).length) o.thresholds = thresholds;

    // http / engine knobs
    if (has(row.rps)) o.rps = num(row.rps);
    if (has(row.maxRedirects)) o.maxRedirects = num(row.maxRedirects);
    if (has(row.userAgent)) o.userAgent = String(row.userAgent);
    if (has(row.minIterationDuration)) o.minIterationDuration = String(row.minIterationDuration).trim();
    if (has(row.dns)) o.dns = String(row.dns).trim();
    if (has(row.insecureSkipTLSVerify)) o.insecureSkipTLSVerify = bool(row.insecureSkipTLSVerify);
    if (has(row.noConnectionReuse)) o.noConnectionReuse = bool(row.noConnectionReuse);
    if (has(row.noVuConnectionReuse)) o.noVUConnectionReuse = bool(row.noVuConnectionReuse);
    if (has(row.throwOnError)) o.throw = bool(row.throwOnError);
    if (has(row.discardResponseBodies)) o.discardResponseBodies = bool(row.discardResponseBodies);
    if (has(row.summaryTrendStats)) o.summaryTrendStats = csv(row.summaryTrendStats);
    if (has(row.blockHostnames)) o.blockHostnames = csv(row.blockHostnames);
    if (has(row.setupTimeout)) o.setupTimeout = String(row.setupTimeout).trim();
    if (has(row.teardownTimeout)) o.teardownTimeout = String(row.teardownTimeout).trim();
    const tags = parseJsonCell(row.tags, 'tags', sheet);
    if (tags) o.tags = tags;
    const hosts = parseJsonCell(row.hosts, 'hosts', sheet);
    if (hosts) o.hosts = hosts;

    // ultimate escape hatch — merged last
    const raw = parseJsonCell(row.rawOptions, 'rawOptions', sheet);
    const options = raw ? deepMerge(o, raw) : o;

    // framework run knobs
    const run = {};
    if (has(row.scenarioSheet)) run.scenarioSheet = String(row.scenarioSheet).trim();
    if (has(row.pick)) run.pick = String(row.pick).trim().toLowerCase();
    if (has(row.think)) run.think = num(row.think);
    if (has(row.iterationSleep)) run.iterationSleep = num(row.iterationSleep);
    if (has(row.env)) run.env = String(row.env).trim();
    if (has(row.baseUrl)) run.baseUrl = String(row.baseUrl).trim();
    if (has(row.reportName)) run.reportName = String(row.reportName).trim();

    return [String(row.profile).trim(), { options, run }];
}

// ── run ─────────────────────────────────────────────────────────────────────
const workbook = XLSX.readFile(FILE);
fs.mkdirSync(OUT_DIR, { recursive: true });

let written = 0;
let profiles = null;

for (const sheetName of workbook.SheetNames) {
    const raw = XLSX.utils.sheet_to_json(workbook.Sheets[sheetName], { defval: '' });

    if (PROFILE_SHEETS.has(sheetName.trim().toLowerCase())) {
        profiles = Object.fromEntries(raw.filter((r) => has(r.profile)).map((r) => buildProfile(r, sheetName)));
        const outPath = path.join(OUT_DIR, 'profiles.json');
        fs.writeFileSync(outPath, JSON.stringify(profiles, null, 2) + '\n');
        const n = Object.keys(profiles).length;
        console.log(`  ✔ ${sheetName} -> ${outPath} (${n} profile${n === 1 ? '' : 's'})`);
        written++;
        continue;
    }

    if (raw.length === 0) {
        console.warn(`  – ${sheetName}: no rows, skipped`);
        continue;
    }

    const rows = raw.map((r) => normaliseRow(r, sheetName));
    const slug = sheetName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const outPath = path.join(OUT_DIR, `${slug}-scenario.json`);
    fs.writeFileSync(outPath, JSON.stringify(rows, null, 2) + '\n');
    console.log(`  ✔ ${sheetName} -> ${outPath} (${rows.length} row${rows.length === 1 ? '' : 's'})`);
    written++;
}

if (!profiles) {
    console.error(`✖ ${FILE} has no "profiles" sheet — add one (columns: profile, vus, duration, p95_ms, …) with at least a "<name>-smoke" and "<name>-load" row.`);
    process.exit(1);
}

console.log(`\n${written} file${written === 1 ? '' : 's'} generated from ${FILE}`);
