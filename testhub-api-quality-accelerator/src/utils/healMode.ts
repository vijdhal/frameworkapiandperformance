import * as fs from 'fs';
import * as path from 'path';

/**
 * TestHub Automation Studio — Smart Run heal hooks (TypeScript side).
 *
 * This module ONLY gates and records. It deliberately contains no
 * accept/defect classification: `testhubui/heal.py` is the single source of
 * truth for the rules (proxy URL -> any status accepted; non proxy -> below
 * 500 accepted; 500 and above becomes a defect). Keep it that way, otherwise
 * the two sides can drift and the excel gets healed against a rule nobody
 * documented.
 *
 * Two passes, both driven by testhubui/runner.py:
 *
 *   HEAL_MODE=capture   HEAL_RUN_DIR=<dir>
 *     Every excel row runs without status assertions. `record()` drops one
 *     JSON capture per row into HEAL_RUN_DIR. heal.py reads them with
 *     sorted(dir.glob('*.json')).
 *
 *   HEAL_MODE=verify    HEAL_SKIP_FILE=<skiplist.json>
 *     The healed sheet runs for real. `openDefect()` tells a row whether it
 *     was parked as an open defect so the spec can skip it and keep the
 *     evidence run clean.
 *
 * Scope gate: dev / sit / uat / prod only, never mock. Kept in sync with
 * HEAL_ENVIRONMENTS in testhubui/heal.py and testhubui/runner.py, and with the
 * button gating in testhubui/static/index.html.
 */

/** Environments Smart Run may heal. Mock is intentionally excluded. */
export const HEAL_ENVIRONMENTS = ['dev', 'sit', 'uat', 'prod'] as const;

export type HealEnvironment = typeof HEAL_ENVIRONMENTS[number];

/** One row's capture, as read by testhubui/heal.py. */
export interface HealCapture {
    suite: string;
    excelName: string;
    sheetName: string;
    rowIndex: number;
    rowName: string;
    method: string;
    endpoint: string;
    resolvedUrl: string;
    proxy: boolean;
    expectedStatus: number;
    actualStatus: number;
    elapsedMs?: number;
    requestHeaders?: Record<string, string>;
    requestBody?: unknown;
    responseBody?: unknown;
    environment: string;
    capturedAt: string;
}

/** A row parked as an open defect by the heal step. */
export interface OpenDefect {
    key: string;
    id: string;
    status: number;
    reason?: string;
}

/** Header names whose values never reach an evidence file. */
const SECRET_HEADERS = [
    'authorization',
    'proxy-authorization',
    'x-api-key',
    'apikey',
    'api-key',
    'x-auth-token',
    'x-access-token',
    'x-client-secret',
    'client-secret',
    'cookie',
    'set-cookie'
];

/** Bodies are evidence, not archives. Anything longer is truncated. */
const MAX_BODY_CHARS = 64_000;

let skipListCache: Map<string, OpenDefect> | null = null;
let captureSeq = 0;

export class HealMode {

    // ───────────────────────── gating ─────────────────────────

    /** ENVIRONMENT the run was launched with, lower cased. */
    static environment(): string {
        return String(
            process.env.ENVIRONMENT ?? process.env.ENV ?? 'dev'
        ).trim().toLowerCase();
    }

    /** True when the current environment is inside the Smart Run scope. */
    static inScope(): boolean {
        return (HEAL_ENVIRONMENTS as readonly string[])
            .includes(this.environment());
    }

    private static mode(): string {
        return String(process.env.HEAL_MODE ?? '').trim().toLowerCase();
    }

    /**
     * True during pass 1. The spec records the actual status instead of
     * asserting it. False outside a Smart Run, and false on any environment
     * outside the scope even if HEAL_MODE was forced — a normal run must
     * never silently lose its assertions.
     */
    static capturing(): boolean {
        return this.mode() === 'capture' && this.inScope();
    }

    /** True during pass 2, the verification + evidence run. */
    static verifying(): boolean {
        return this.mode() === 'verify' && this.inScope();
    }

    // ───────────────────────── proxy rule ─────────────────────────

    /**
     * Mirror of is_proxy_url() in testhubui/heal.py: "proxy" anywhere in the
     * fully resolved URL — eproxy, experience proxy, salesforce proxy, any
     * of them. The classification that follows from it lives in heal.py.
     */
    static isProxyUrl(url: string): boolean {
        return /proxy/i.test(url ?? '');
    }

    // ───────────────────────── redaction ─────────────────────────

    /** Credential bearing headers are masked before they reach evidence. */
    static redactHeaders(
        headers?: Record<string, unknown>
    ): Record<string, string> {
        const out: Record<string, string> = {};
        if (!headers) return out;

        for (const [key, value] of Object.entries(headers)) {
            out[key] = SECRET_HEADERS.includes(key.trim().toLowerCase())
                ? '***redacted***'
                : HealMode.stringifyHeaderValue(value);
        }
        return out;
    }

    private static stringifyHeaderValue(value: unknown): string {
        if (value === null || value === undefined) return '';
        if (Array.isArray(value)) return value.map(String).join(', ');
        return String(value);
    }

    // ───────────────────────── recording ─────────────────────────

    /**
     * Writes one capture file for a row. Never throws: a recording problem
     * must not fail somebody's test run. Failures are logged and the run
     * simply heals fewer rows.
     */
    static record(capture: HealCapture): void {
        if (!this.capturing()) return;

        const dir = process.env.HEAL_RUN_DIR;
        if (!dir) {
            console.warn(
                '[healMode] HEAL_MODE=capture but HEAL_RUN_DIR is not set; ' +
                'nothing was recorded'
            );
            return;
        }

        try {
            fs.mkdirSync(dir, { recursive: true });

            const safe: HealCapture = {
                ...capture,
                proxy: Boolean(
                    capture.proxy || this.isProxyUrl(capture.resolvedUrl)
                ),
                expectedStatus: Number(capture.expectedStatus) || 0,
                actualStatus: Number(capture.actualStatus) || 0,
                requestHeaders: this.redactHeaders(capture.requestHeaders),
                requestBody: this.sanitizeBody(capture.requestBody),
                responseBody: this.sanitizeBody(capture.responseBody),
                environment: capture.environment || this.environment(),
                capturedAt: capture.capturedAt || new Date().toISOString()
            };

            fs.writeFileSync(
                path.join(dir, this.captureFileName(safe)),
                JSON.stringify(safe, null, 2),
                'utf-8'
            );
        } catch (err: any) {
            console.warn(
                `[healMode] could not record "${capture.rowName}": ` +
                `${err?.message ?? err}`
            );
        }
    }

    /**
     * Unique per row and per Playwright worker. playwright.config.ts runs 5
     * workers, and describe-level serial mode only orders tests inside one
     * file, so the pid and a monotonic counter are what keep two workers
     * from writing the same name. heal.py only globs the directory, so the
     * shape is free — it is built to be readable when debugging a run.
     */
    private static captureFileName(capture: HealCapture): string {
        const slug = (value: string, max = 40) =>
            String(value ?? '')
                .replace(/[^A-Za-z0-9._-]+/g, '-')
                .replace(/^-+|-+$/g, '')
                .slice(0, max) || 'row';

        const index = String(Number(capture.rowIndex) || 0).padStart(4, '0');
        const seq = String(++captureSeq).padStart(3, '0');

        return [
            slug(capture.sheetName, 30),
            index,
            slug(capture.rowName),
            process.pid,
            seq
        ].join('__') + '.json';
    }

    /**
     * Request and response bodies arrive in whatever shape the encoder and
     * axios produced. Buffers and FormData are summarised the way
     * RequestBuilder already logs them — JSON.stringify on a Buffer would
     * otherwise expand a PDF upload into a megabytes-long byte array inside
     * the capture and the defect report.
     */
    private static sanitizeBody(body: unknown): unknown {
        if (body === null || body === undefined || body === '') return null;

        if (Buffer.isBuffer(body)) {
            return `<Buffer ${body.length} bytes>`;
        }
        if (body instanceof ArrayBuffer) {
            return `<ArrayBuffer ${body.byteLength} bytes>`;
        }
        if (ArrayBuffer.isView(body)) {
            return `<${body.constructor?.name ?? 'TypedArray'} ` +
                `${body.byteLength} bytes>`;
        }

        const ctor = (body as any)?.constructor?.name;
        if (ctor === 'FormData') return '<multipart/form-data>';
        if (ctor === 'URLSearchParams') {
            return this.truncate(String(body));
        }
        if (typeof (body as any)?.pipe === 'function') {
            return '<stream>';
        }

        if (typeof body === 'string') return this.truncate(body);

        try {
            const json = JSON.stringify(body);
            if (json === undefined) return String(body);
            return json.length > MAX_BODY_CHARS
                ? this.truncate(json)
                : JSON.parse(json);
        } catch {
            // Circular or otherwise unserialisable — evidence still beats a
            // crashed capture.
            return this.truncate(String(body));
        }
    }

    private static truncate(value: string): string {
        return value.length > MAX_BODY_CHARS
            ? value.slice(0, MAX_BODY_CHARS) +
                `\n... [truncated, ${value.length} chars total]`
            : value;
    }

    // ───────────────────────── verify pass ─────────────────────────

    /**
     * Looks a row up in the skip list the heal step produced. `key` is
     * `${sheetName}::${TestName}`, the same shape heal.py writes.
     * Returns null when the row is not an open defect, or when this is not a
     * verification pass.
     */
    static openDefect(key: string): OpenDefect | null {
        const list = this.skipList();
        if (!list) return null;
        return list.get(String(key).trim()) ?? null;
    }

    /** All rows parked as open defects for this run. */
    static openDefects(): OpenDefect[] {
        const list = this.skipList();
        return list ? Array.from(list.values()) : [];
    }

    private static skipList(): Map<string, OpenDefect> | null {
        // Only the verification pass may skip rows. Defect packs are kept
        // indefinitely under defect-reports/, so a stale HEAL_SKIP_FILE left
        // in a shell would otherwise silently drop rows from an ordinary
        // ▶ Execute Tests run — on MOCK included. Pass 2 always sets
        // HEAL_MODE=verify, so nothing legitimate loses access here.
        if (!this.verifying()) return null;

        if (skipListCache) return skipListCache;

        const file = process.env.HEAL_SKIP_FILE;
        if (!file || !fs.existsSync(file)) return null;

        try {
            const parsed = JSON.parse(fs.readFileSync(file, 'utf-8'));
            const map = new Map<string, OpenDefect>();

            for (const entry of parsed?.defects ?? []) {
                if (!entry?.key) continue;
                map.set(String(entry.key).trim(), {
                    key: String(entry.key).trim(),
                    id: String(entry.id ?? 'DEFECT'),
                    status: Number(entry.status) || 0,
                    reason: entry.reason ? String(entry.reason) : undefined
                });
            }

            skipListCache = map;
            return map;
        } catch (err: any) {
            console.warn(
                `[healMode] could not read HEAL_SKIP_FILE "${file}": ` +
                `${err?.message ?? err}`
            );
            return null;
        }
    }

    /** Test-support hook: forget the cached skip list. */
    static resetCache(): void {
        skipListCache = null;
    }
}
