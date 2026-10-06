import { OAuth2ClientCredentials } from '../auth/OAuth2ClientCredentials.js';

/**
 * Builds the auth context passed to runScenario(). OAuth2 tokens are fetched
 * once here (call from a test's setup(), which k6 runs a single time) rather
 * than per iteration — see OAuth2ClientCredentials.js. apikey / none need no
 * setup work and resolve per-request in AuthStrategyResolver.
 *
 * @param {Array} scenario  the loaded scenario rows
 * @returns {object}  e.g. { token } when any row uses oauth2, otherwise {}
 */
export function resolveAuthContext(scenario) {
    const needsOAuth = Array.isArray(scenario)
        && scenario.some((row) => String(row.authType || '').toLowerCase() === 'oauth2');

    return needsOAuth ? { token: OAuth2ClientCredentials.fetchToken() } : {};
}
