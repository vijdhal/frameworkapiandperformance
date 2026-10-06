import { ApiKeyAuth } from './ApiKeyAuth.js';

/**
 * Picks the right auth strategy from a string, same role as
 * api-test-framework's AuthStrategyResolver.ts.
 *
 * @param {string} authType  'apikey' | 'oauth2' | 'none' | undefined
 * @param {object} context   extra data a strategy needs — e.g. { token } for oauth2,
 *                            fetched once in setup() (see OAuth2ClientCredentials.js)
 */
export class AuthStrategyResolver {
    static resolve(authType, context = {}) {
        switch ((authType || 'none').toLowerCase()) {
            case 'apikey':
                return ApiKeyAuth.getHeaders();

            case 'oauth2':
                if (!context.token) {
                    throw new Error(
                        'oauth2 auth requires a pre-fetched token — call OAuth2ClientCredentials.fetchToken() ' +
                        'in setup() and pass it through as context.token.'
                    );
                }
                return { Authorization: `Bearer ${context.token}` };

            case 'none':
            default:
                return {};
        }
    }
}
