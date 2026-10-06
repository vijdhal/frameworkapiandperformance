import { check } from 'k6';

/** Single status assertion — kept for existing call sites. */
export function validateStatus(response, expectedStatus) {
    return check(response, {
        [`status is ${expectedStatus}`]: (r) => r.status === expectedStatus,
    });
}

/**
 * Scenario-row assertion set, the k6 analog of api-test-framework's
 * responseValidator: status, optional latency budget, optional required
 * body fields. Returns true only if every declared check passed.
 *
 * @param {object} response  k6 response
 * @param {object} expect    { status, maxResponseMs, bodyContains: string[] }
 * @param {string} label     row name, prefixed onto each check for readable output
 */
export function validateResponse(response, expect = {}, label = '') {
    const prefix = label ? `${label} — ` : '';
    const checks = {};

    if (expect.status !== undefined && expect.status !== null && expect.status !== '') {
        checks[`${prefix}status is ${expect.status}`] = (r) => r.status === Number(expect.status);
    }

    if (expect.maxResponseMs) {
        checks[`${prefix}response < ${expect.maxResponseMs}ms`] =
            (r) => r.timings.duration <= Number(expect.maxResponseMs);
    }

    for (const field of expect.bodyContains || []) {
        checks[`${prefix}body has "${field}"`] = (r) => extract(safeJson(r), field) !== undefined;
    }

    if (Object.keys(checks).length === 0) {
        checks[`${prefix}response received`] = (r) => r.status !== 0;
    }

    return check(response, checks);
}

/** Dotted-path read: extract(body, 'data.id'), extract(body, 'items.0.name'). */
export function extract(obj, path) {
    if (!obj || !path) return undefined;
    return String(path).split('.').reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
}

function safeJson(response) {
    try {
        return response.json();
    } catch (_e) {
        return undefined;
    }
}
