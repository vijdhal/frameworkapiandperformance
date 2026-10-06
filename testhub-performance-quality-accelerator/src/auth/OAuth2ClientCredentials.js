import http from 'k6/http';

/**
 * Fetches a Bearer token via the OAuth2 client-credentials grant.
 *
 * Unlike api-test-framework's TokenManager, this does NOT cache the token across VUs —
 * k6 VUs don't share JS state. Call fetchToken() once inside setup(), which runs once
 * per test regardless of VU count, then pass the token to default() via setup()'s
 * return value:
 *
 *   export function setup() {
 *       return { token: OAuth2ClientCredentials.fetchToken() };
 *   }
 *   export default function (data) {
 *       const headers = AuthStrategyResolver.resolve('oauth2', { token: data.token });
 *       ...
 *   }
 */
export class OAuth2ClientCredentials {
    static fetchToken() {
        const tokenUrl = __ENV.OAUTH2_TOKEN_URL;
        const clientId = __ENV.CLIENT_ID;
        const clientSecret = __ENV.CLIENT_SECRET;
        const scope = __ENV.OAUTH2_SCOPE;

        if (!tokenUrl || !clientId || !clientSecret) {
            throw new Error('OAUTH2_TOKEN_URL, CLIENT_ID and CLIENT_SECRET must be set for oauth2 auth.');
        }

        const body = {
            grant_type: 'client_credentials',
            client_id: clientId,
            client_secret: clientSecret,
        };
        if (scope) {
            body.scope = scope;
        }

        const res = http.post(tokenUrl, body);

        if (res.status !== 200) {
            throw new Error(`OAuth2 token request failed: ${res.status} ${res.body}`);
        }

        return JSON.parse(res.body).access_token;
    }
}
