import { AuthStrategyResolver } from '../auth/AuthStrategyResolver.js';
import { ApiService } from '../services/apiService.js';

/**
 * Turns one scenario row (from test-data/scenarios/*.json, generated out of the
 * Excel workbook) into a ready-to-send request — the k6 equivalent of
 * api-test-framework's RequestBuilder.ts.
 *
 * Row fields (all optional except endpoint):
 *   name, endpoint, method, authType, headers, payload,
 *   expectedStatus, maxResponseMs, extractField, injectAs
 *
 * {{ctx:key}} tokens in endpoint / headers / payload are replaced from `context`,
 * so a POST can feed an id into a later GET/PATCH/DELETE within the same iteration.
 *
 * @param {object} row          one scenario entry
 * @param {object} authContext  passed to AuthStrategyResolver (e.g. { token } from setup())
 * @param {object} context      values captured earlier this iteration via extractField/injectAs
 */
export function buildRequest(row, authContext = {}, context = {}) {
    const method = String(row.method || 'GET').toUpperCase();
    const endpoint = resolveTokens(row.endpoint || '', context);
    const url = ApiService.url(endpoint);

    // A row's endpoint may be an absolute URL to a second host (see ApiService.url);
    // the primary API's auth headers must never follow it there.
    const authHeaders = ApiService.isPrimaryHost(url)
        ? AuthStrategyResolver.resolve(row.authType, authContext)
        : {};
    const headers = resolveTokens({ ...authHeaders, ...(row.headers || {}) }, context);

    const payload = row.payload !== undefined && row.payload !== null && row.payload !== ''
        ? resolveTokens(row.payload, context)
        : null;

    return {
        name: row.name || `${method} ${endpoint}`,
        method,
        url,
        payload,
        headers,
        expect: {
            status: row.expectedStatus,
            maxResponseMs: row.maxResponseMs,
        },
        extractField: row.extractField || null,
        injectAs: row.injectAs || null,
    };
}

/** Recursively replace {{ctx:key}} tokens in strings / objects / arrays. */
export function resolveTokens(value, context) {
    if (typeof value === 'string') {
        return value.replace(/\{\{ctx:([^}]+)\}\}/g, (_m, key) => {
            const v = context[key.trim()];
            return v === undefined || v === null ? '' : String(v);
        });
    }
    if (Array.isArray(value)) {
        return value.map((v) => resolveTokens(v, context));
    }
    if (value && typeof value === 'object') {
        const out = {};
        for (const [k, v] of Object.entries(value)) {
            out[k] = resolveTokens(v, context);
        }
        return out;
    }
    return value;
}
