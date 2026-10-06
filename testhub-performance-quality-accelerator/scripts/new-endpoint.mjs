#!/usr/bin/env node
/**
 * new-endpoint.mjs
 * ---------------------------------------------------------------
 * Scaffolds one self-contained endpoint folder — everything a new endpoint
 * needs lives together under tests/<name>/, nothing shared:
 *
 *   tests/<name>/<name>.xlsx                — source: request row(s) (sheet
 *                                              "<name>") + perf params for
 *                                              smoke/load (sheet "profiles")
 *   tests/<name>/<name>-requestpayload.json — source: POST/PUT/PATCH body
 *   tests/<name>/<name>-scenario.json       — generated (gen:scenarios below)
 *   tests/<name>/profiles.json              — generated
 *   tests/<name>/<name>-smoke-test.js       — k6 test, 1 VU / 1 iteration
 *   tests/<name>/<name>-load-test.js        — k6 test, VUs/duration from Excel
 *
 * Usage:
 *   node scripts/new-endpoint.mjs <name> [--method GET] [--path /api/<name>]
 *                                 [--auth none] [--force]
 *
 *   node scripts/new-endpoint.mjs orders --method POST --path /api/orders
 *
 * Every performance input (vus, duration, stages, thresholds, …) lives on the
 * "profiles" sheet of <name>.xlsx — edit it there, then re-run:
 *   npm run <name>:gen
 * ---------------------------------------------------------------
 */
import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';
import * as XLSX from 'xlsx';

XLSX.set_fs(fs);

const REQUEST_COLS = [
    'name', 'endpoint', 'method', 'authType', 'headers', 'payload', 'payloadFile',
    'expectedStatus', 'maxResponseMs', 'extractField', 'injectAs', 'weight',
];
const PROFILE_COLS = [
    'profile', 'executor', 'vus', 'startVus', 'duration', 'iterations', 'stages',
    'rate', 'timeUnit', 'preAllocatedVus', 'maxVus',
    'maxDuration', 'gracefulStop', 'gracefulRampDown',
    'p90_ms', 'p95_ms', 'p99_ms', 'max_ms', 'avg_ms', 'errorRate', 'checkRate', 'rawThresholds',
    'rps', 'maxRedirects', 'userAgent', 'minIterationDuration', 'dns',
    'insecureSkipTLSVerify', 'noConnectionReuse', 'noVuConnectionReuse',
    'throwOnError', 'discardResponseBodies',
    'summaryTrendStats', 'tags', 'hosts', 'blockHostnames',
    'setupTimeout', 'teardownTimeout', 'rawOptions',
    'scenarioSheet', 'pick', 'think', 'iterationSleep', 'env', 'baseUrl', 'reportName',
];
const DEFAULT_STATUS = { GET: 200, POST: 201, PUT: 200, PATCH: 200, DELETE: 204, HEAD: 200, OPTIONS: 200 };
const NEEDS_BODY = new Set(['POST', 'PUT', 'PATCH']);

// ── args ─────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const name = argv.find((a) => !a.startsWith('--'));
const flag = (n, def) => {
    const i = argv.indexOf(`--${n}`);
    return i !== -1 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : def;
};
const force = argv.includes('--force');

if (!name || !/^[a-z][a-z0-9-]*$/.test(name)) {
    console.error('Usage: node scripts/new-endpoint.mjs <name> [--method GET] [--path /api/<name>] [--auth none] [--force]');
    console.error('       <name> must be lowercase letters, digits, or hyphens (e.g. "orders")');
    process.exit(1);
}
const method = String(flag('method', 'GET')).toUpperCase();
const endpointPath = flag('path', `/api/${name}`);
const authType = flag('auth', 'none');

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const DIR = path.join(ROOT, 'tests', name);
const WORKBOOK = path.join(DIR, `${name}.xlsx`);
const PAYLOAD_FILE = path.join(DIR, `${name}-requestpayload.json`);
const PACKAGE_JSON = path.join(ROOT, 'package.json');

if (fs.existsSync(WORKBOOK) && !force) {
    console.error(`✖ ${path.relative(ROOT, WORKBOOK)} already exists — pass --force to overwrite/extend it.`);
    process.exit(1);
}

fs.mkdirSync(DIR, { recursive: true });

// ── 1. request payload JSON (only for methods that carry a body) ──────────
let payloadFileRel = '';
if (NEEDS_BODY.has(method)) {
    if (!fs.existsSync(PAYLOAD_FILE) || force) {
        fs.writeFileSync(PAYLOAD_FILE, JSON.stringify({
            _comment: `Replace with the real request body for ${method} ${endpointPath}.`,
            field1: 'value1',
        }, null, 2) + '\n');
        console.log(`✔ payload           -> ${path.relative(ROOT, PAYLOAD_FILE)}`);
    } else {
        console.log(`  payload already exists — skipped: ${path.relative(ROOT, PAYLOAD_FILE)}`);
    }
    payloadFileRel = path.relative(ROOT, PAYLOAD_FILE).replace(/\\/g, '/');
}

// ── 2. workbook: "<name>" request sheet + "profiles" sheet (smoke + load) ──
const exampleRow = {
    name: `${method} ${name}`,
    endpoint: endpointPath,
    method,
    authType,
    expectedStatus: DEFAULT_STATUS[method] ?? 200,
    maxResponseMs: 2000,
    weight: 1,
};
if (payloadFileRel) exampleRow.payloadFile = payloadFileRel;

const smokeProfile = {
    profile: `${name}-smoke`, vus: 1, iterations: 1,
    p95_ms: 2000, errorRate: 0.01, checkRate: 0.99, env: 'dev',
    scenarioSheet: name, pick: 'sequential', think: 0, iterationSleep: 0,
    reportName: `${name}-smoke-test-report`,
};
const loadProfile = {
    profile: `${name}-load`, vus: 10, duration: '30s',
    p95_ms: 1000, errorRate: 0.01, env: 'dev',
    scenarioSheet: name, pick: 'weighted', iterationSleep: 1,
    reportName: `${name}-load-test-report`,
};

const wb = XLSX.utils.book_new();
const wsReq = XLSX.utils.json_to_sheet([exampleRow], { header: REQUEST_COLS });
wsReq['!cols'] = REQUEST_COLS.map((h) => ({ wch: Math.max(h.length + 4, 18) }));
XLSX.utils.book_append_sheet(wb, wsReq, name);

const wsProf = XLSX.utils.json_to_sheet([smokeProfile, loadProfile], { header: PROFILE_COLS });
XLSX.utils.book_append_sheet(wb, wsProf, 'profiles');

XLSX.writeFile(wb, WORKBOOK);
console.log(`✔ workbook          -> ${path.relative(ROOT, WORKBOOK)} (sheets: ${name}, profiles)`);

// ── 3. compile the workbook straight into its own folder ──────────────────
const gen = spawnSync(process.execPath, [
    path.join(ROOT, 'scripts', 'excel-to-scenario.mjs'),
    '--file', path.relative(ROOT, WORKBOOK),
    '--out-dir', path.relative(ROOT, DIR),
], { stdio: 'inherit', cwd: ROOT });
if (gen.status !== 0) process.exit(gen.status ?? 1);

// ── 4. tests/<name>/<name>-{smoke,load}-test.js ────────────────────────────
function testFileContent(profile, pick, reportName) {
    return `import { sleep } from 'k6';
import { loadScenario } from '../../src/utils/dataLoader.js';
import { loadOptions, loadRunParams } from '../../src/utils/optionsLoader.js';
import { resolveAuthContext } from '../../src/utils/authSetup.js';
import { runScenario } from '../../src/utils/scenarioRunner.js';
import { buildSummary } from '../../src/utils/htmlReport.js';

// Self-contained endpoint example. Everything this file needs lives right
// next to it in tests/${name}/:
//   ${name}.xlsx               — source: the "${name}" request row +
//                                    the "${profile}" row of its "profiles" sheet
${payloadFileRel ? `//   ${name}-requestpayload.json — source: the request body (via the payloadFile column)\n` : ''}//   ${name}-scenario.json      — generated: \`npm run ${name}:gen\`
//   profiles.json                 — generated: \`npm run ${name}:gen\`
// Regenerate the two JSON files after editing the workbook:
//   node scripts/excel-to-scenario.mjs --file tests/${name}/${name}.xlsx --out-dir tests/${name}
const DIR = 'tests/${name}';
const PROFILE = '${profile}';
const run = loadRunParams(PROFILE, DIR);
const scenario = loadScenario(run.scenarioSheet || '${name}', DIR);

export const options = loadOptions(PROFILE, DIR);

export function setup() {
    return { auth: resolveAuthContext(scenario) };
}

export default function (data) {
    runScenario(scenario, {
        auth: data.auth,
        pick: run.pick || '${pick}',
        think: run.think || 0,
    });
    if (run.iterationSleep) {
        sleep(run.iterationSleep);
    }
}

export function handleSummary(data) {
    return buildSummary(data, run.reportName || '${reportName}');
}
`;
}

const smokeTestFile = path.join(DIR, `${name}-smoke-test.js`);
const loadTestFile = path.join(DIR, `${name}-load-test.js`);

for (const [file, profile, pick, reportName] of [
    [smokeTestFile, `${name}-smoke`, 'sequential', `${name}-smoke-test-report`],
    [loadTestFile, `${name}-load`, 'weighted', `${name}-load-test-report`],
]) {
    if (fs.existsSync(file) && !force) {
        console.log(`  test file already exists — skipped: ${path.relative(ROOT, file)}`);
    } else {
        fs.writeFileSync(file, testFileContent(profile, pick, reportName));
        console.log(`✔ test file         -> ${path.relative(ROOT, file)}`);
    }
}

// ── 5. package.json convenience scripts ────────────────────────────────────
const pkg = JSON.parse(fs.readFileSync(PACKAGE_JSON, 'utf-8'));
pkg.scripts ||= {};
const newScripts = {
    [`${name}:gen`]: `node scripts/excel-to-scenario.mjs --file tests/${name}/${name}.xlsx --out-dir tests/${name}`,
    [`${name}:smoke`]: `npm run ${name}:gen && k6 run -e ENV=dev tests/${name}/${name}-smoke-test.js`,
    [`${name}:load`]: `npm run ${name}:gen && k6 run -e ENV=dev tests/${name}/${name}-load-test.js`,
};
let addedScripts = false;
for (const [k, v] of Object.entries(newScripts)) {
    if (!pkg.scripts[k] || force) {
        pkg.scripts[k] = v;
        addedScripts = true;
    }
}
if (addedScripts) {
    fs.writeFileSync(PACKAGE_JSON, JSON.stringify(pkg, null, 2) + '\n');
    console.log(`✔ npm scripts       -> ${Object.keys(newScripts).join(', ')}`);
}

console.log(`\nDone! Next steps:`);
console.log(`  1. Open tests/${name}/${name}.xlsx — sheet "${name}" for the request(s), "profiles" for smoke/load perf params`);
if (payloadFileRel) console.log(`  2. Edit ${payloadFileRel} with the real request body`);
console.log(`  ${payloadFileRel ? '3' : '2'}. Run: npm run ${name}:smoke   (or npm run ${name}:load)`);
