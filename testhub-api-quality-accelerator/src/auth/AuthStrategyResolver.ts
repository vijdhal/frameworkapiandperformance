import { AuthStrategy } from './AuthStrategy';
import { ApiKeyAuth } from './ApiKeyAuth';
import { BasicAuth } from './BasicAuth';
import { OAuth2ClientCredentials } from './OAuth2ClientCredentials';
import { MulesoftAuth } from './MulesoftAuth';
import { SalesforceAuth } from './SalesforceAuth';

/**
 * Maps an authType string (from Excel / YAML) to the correct AuthStrategy.
 *
 * Supported values:
 *   apikey  — x-api-key header from API_KEY env var
 *   basic   — Basic Auth from BASIC_USERNAME / BASIC_PASSWORD env vars
 *   oauth2  — OAuth2 Client Credentials from OAUTH2_TOKEN_URL / CLIENT_ID / CLIENT_SECRET env vars
 *   none    — no auth headers added
 *   (empty) — RequestBuilder default: API_KEY + TokenManager Bearer
 */
export class AuthStrategyResolver {

    static resolve(authType?: string): AuthStrategy | undefined {

        switch (authType?.trim().toLowerCase()) {

            // case 'apikey':
            //     return new ApiKeyAuth({
            //         apiKey:     process.env.API_KEY!,
            //         headerName: process.env.API_KEY_HEADER || 'x-api-key'
            //     });
            case 'apikey':
                return new ApiKeyAuth({
                    apiKey: process.env.API_KEY!,
                    headerName: process.env.API_KEY_HEADER || 'x-api-key'
                });

            // Negative-test variant: sends a deliberately wrong key so the
            // server responds 401. Used by the "Invalid API Key" scenario.
            case 'apikeyinvalid':
            case 'invalidapikey':
                return new ApiKeyAuth({
                    apiKey: 'invalid-key-000',
                    headerName: process.env.API_KEY_HEADER || 'x-api-key'
                });

            case 'basic':
                return new BasicAuth({
                    username: process.env.BASIC_USERNAME!,
                    password: process.env.BASIC_PASSWORD!
                });

            case 'oauth2':
                return new OAuth2ClientCredentials({
                    tokenUrl:     process.env.OAUTH2_TOKEN_URL!,
                    clientId:     process.env.CLIENT_ID!,
                    clientSecret: process.env.CLIENT_SECRET!,
                    scope:        process.env.OAUTH2_SCOPE
                });

            case 'mulesoft':
                return new MulesoftAuth({
                    tokenUrl:     process.env.MULESOFT_TOKEN_URL!,
                    clientId:     process.env.MULESOFT_CLIENT_ID!,
                    clientSecret: process.env.MULESOFT_CLIENT_SECRET!,
                    scope:        process.env.MULESOFT_SCOPE
                });

            case 'salesforce':
                return new SalesforceAuth({
                    tokenUrl:     process.env.SF_TOKEN_URL!,
                    clientId:     process.env.SF_CLIENT_ID!,
                    clientSecret: process.env.SF_CLIENT_SECRET!,
                    username:     process.env.SF_USERNAME,
                    password:     process.env.SF_PASSWORD
                });

            case 'none':
                // Explicitly no auth — no headers added
                return { applyAuth: async () => {} };

            default:
                // undefined → RequestBuilder applies its defaults (API_KEY + TokenManager)
                return undefined;
        }
    }
}
