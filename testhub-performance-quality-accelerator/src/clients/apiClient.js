import http from 'k6/http';

/**
 * Thin wrapper over k6/http, the load-test analog of api-test-framework's
 * APIClient. Every verb funnels through request() so headers, JSON encoding
 * and tagging behave identically no matter which method a scenario row uses.
 *
 * A scenario row never calls these directly — RequestBuilder produces a
 * { method, url, payload, headers } object and send() dispatches it.
 */
export class APIClient {

    /**
     * Generic dispatch. Mirrors http.request(method, url, body, params) but
     * JSON-encodes object payloads and always sets Content-Type for writes.
     *
     * @param {string} method  GET | POST | PUT | PATCH | DELETE | HEAD | OPTIONS
     * @param {string} url      fully-qualified URL
     * @param {*}      payload  object (JSON-encoded), pre-serialised string, or null
     * @param {object} params   extra k6 params merged last — { headers, tags, timeout }
     */
    static request(method, url, payload = null, params = {}) {
        const verb = String(method || 'GET').toUpperCase();
        const headers = { ...(params.headers || {}) };

        let body = null;
        if (payload !== null && payload !== undefined && verb !== 'GET' && verb !== 'HEAD') {
            if (typeof payload === 'string') {
                body = payload;
            } else {
                body = JSON.stringify(payload);
            }
            if (!hasHeader(headers, 'content-type')) {
                headers['Content-Type'] = 'application/json';
            }
        }

        return http.request(verb, url, body, { ...params, headers });
    }

    /** Convenience: run a RequestBuilder result straight through request(). */
    static send({ method, url, payload = null, headers = {}, tags = {} }) {
        return APIClient.request(method, url, payload, { headers, tags });
    }

    static get(url, params = {})              { return APIClient.request('GET', url, null, params); }
    static post(url, payload, params = {})    { return APIClient.request('POST', url, payload, params); }
    static put(url, payload, params = {})     { return APIClient.request('PUT', url, payload, params); }
    static patch(url, payload, params = {})   { return APIClient.request('PATCH', url, payload, params); }
    static del(url, payload = null, params = {}) { return APIClient.request('DELETE', url, payload, params); }
    static head(url, params = {})             { return APIClient.request('HEAD', url, null, params); }
    static options(url, params = {})          { return APIClient.request('OPTIONS', url, null, params); }
}

function hasHeader(headers, name) {
    return Object.keys(headers).some((h) => h.toLowerCase() === name.toLowerCase());
}
