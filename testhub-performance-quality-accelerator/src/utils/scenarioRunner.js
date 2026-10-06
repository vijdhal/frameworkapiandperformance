import { group, sleep } from 'k6';
import { APIClient } from '../clients/apiClient.js';
import { buildRequest } from './requestBuilder.js';
import { validateResponse, extract } from './responseValidator.js';

/**
 * Executes an Excel-authored scenario (array of rows loaded from
 * test-data/scenarios/*.json). Every test profile — smoke / load / stress /
 * spike / soak — calls this; only the k6 `options` (VUs, stages, duration)
 * differ between them.
 *
 * @param {Array}  rows            scenario rows (see requestBuilder for the shape)
 * @param {object} opts
 *   - auth   {object}  auth context from setup() (e.g. { token }); default {}
 *   - pick   {string}  'sequential' (default) runs every row in order and threads
 *                      {{ctx:*}} values between them; 'random' / 'weighted' fire
 *                      exactly one row per iteration for pure load generation
 *   - think  {number}  seconds to sleep after each row (sequential only); default 0
 * @returns {boolean}  true only if every executed row passed its checks
 */
export function runScenario(rows, opts = {}) {
    const { auth = {}, pick = 'sequential', think = 0 } = opts;

    if (!Array.isArray(rows) || rows.length === 0) {
        throw new Error('runScenario: scenario is empty — did you run `npm run gen:scenarios`?');
    }

    if (pick === 'random' || pick === 'weighted') {
        return runRow(chooseRow(rows, pick), auth, {});
    }

    const context = {};
    let allPassed = true;

    for (const row of rows) {
        const ok = group(row.name || `${row.method} ${row.endpoint}`, () => runRow(row, auth, context));
        allPassed = allPassed && ok;
        if (think > 0) {
            sleep(think);
        }
    }

    return allPassed;
}

/** Build → send → validate → capture context for a single row. */
export function runRow(row, auth = {}, context = {}) {
    const req = buildRequest(row, auth, context);
    const res = APIClient.send(req);

    const passed = validateResponse(res, req.expect, req.name);

    if (req.extractField && req.injectAs) {
        let body;
        try {
            body = res.json();
        } catch (_e) {
            body = undefined;
        }
        const value = extract(body, req.extractField);
        if (value !== undefined && value !== null) {
            context[req.injectAs] = value;
        }
    }

    return passed;
}

function chooseRow(rows, pick) {
    if (pick === 'weighted' && rows.some((r) => Number(r.weight) > 0)) {
        const total = rows.reduce((sum, r) => sum + (Number(r.weight) || 0), 0);
        let dart = Math.random() * total;
        for (const r of rows) {
            dart -= Number(r.weight) || 0;
            if (dart <= 0) return r;
        }
    }
    return rows[Math.floor(Math.random() * rows.length)];
}
