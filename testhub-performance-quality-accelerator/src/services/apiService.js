import { APIClient } from '../clients/apiClient.js';
import { ENV } from '../../config/environment.js';

/**
 * Generic, endpoint-parametrised service — the reusable core every test script
 * (smoke / load / stress / spike / soak) shares. Nothing here is user-specific:
 * pass an endpoint path and, for writes, a payload.
 *
 *   ApiService.get('/api/users?page=2');
 *   ApiService.post('/api/users', { name: 'x', job: 'y' });
 *   ApiService.patch('/api/users/2', { job: 'z' });
 *   ApiService.del('/api/users/2');
 *
 * The base URL comes from config/environments.json via ENV.BASE_URL. An endpoint
 * that already starts with http(s):// is used as-is so a row can hit a second host.
 */
export class ApiService {

    static url(endpoint) {
        if (/^https?:\/\//i.test(endpoint)) {
            return endpoint;
        }
        return `${ENV.BASE_URL}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
    }

    /**
     * True when `url` resolves to the configured ENV.BASE_URL host. A row's
     * `endpoint` may be an absolute URL to hit a second host (see url() above);
     * that second host must never receive the auth headers resolved for the
     * primary API — see requestBuilder.js.
     */
    static isPrimaryHost(url) {
        try {
            return new URL(url).hostname === new URL(ENV.BASE_URL).hostname;
        } catch {
            return false;
        }
    }

    /**
     * Verb-agnostic entry point — handy for data-driven loops.
     * @param {string} method   GET | POST | PUT | PATCH | DELETE | HEAD | OPTIONS
     * @param {string} endpoint path or absolute URL
     * @param {object} opts     { payload, headers, tags }
     */
    static call(method, endpoint, opts = {}) {
        const { payload = null, headers = {}, tags = {} } = opts;
        return APIClient.request(method, ApiService.url(endpoint), payload, { headers, tags });
    }

    static get(endpoint, opts = {})            { return ApiService.call('GET', endpoint, opts); }
    static post(endpoint, payload, opts = {})  { return ApiService.call('POST', endpoint, { ...opts, payload }); }
    static put(endpoint, payload, opts = {})   { return ApiService.call('PUT', endpoint, { ...opts, payload }); }
    static patch(endpoint, payload, opts = {}) { return ApiService.call('PATCH', endpoint, { ...opts, payload }); }
    static del(endpoint, opts = {})            { return ApiService.call('DELETE', endpoint, opts); }
    static head(endpoint, opts = {})           { return ApiService.call('HEAD', endpoint, opts); }
    static options(endpoint, opts = {})        { return ApiService.call('OPTIONS', endpoint, opts); }
}
