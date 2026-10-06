import axios from 'axios';
import { AuthStrategy } from './AuthStrategy';

export interface MulesoftAuthConfig {
    tokenUrl: string;
    clientId: string;
    clientSecret: string;
    scope?: string;
}

interface TokenCache {
    accessToken: string;
    expiresAt: number;
}

/**
 * MuleSoft OAuth2 Client Credentials.
 * Sends clientId:clientSecret as HTTP Basic Auth header (RFC 6749 §2.3.1)
 * rather than in the request body — this is the Anypoint Platform convention.
 */
export class MulesoftAuth implements AuthStrategy {
    private cache: TokenCache | null = null;

    constructor(private config: MulesoftAuthConfig) {}

    async applyAuth(headers: Record<string, string>): Promise<void> {
        headers['Authorization'] = `Bearer ${await this.getAccessToken()}`;
    }

    private async getAccessToken(): Promise<string> {
        if (this.cache && Date.now() < this.cache.expiresAt - 30_000) {
            return this.cache.accessToken;
        }

        const encoded = Buffer.from(
            `${this.config.clientId}:${this.config.clientSecret}`
        ).toString('base64');

        const body = new URLSearchParams({ grant_type: 'client_credentials' });
        if (this.config.scope) body.set('scope', this.config.scope);

        const response = await axios.post(this.config.tokenUrl, body.toString(), {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': `Basic ${encoded}`
            },
            validateStatus: () => true
        });

        if (response.status !== 200) {
            throw new Error(
                `MuleSoft token request failed [${response.status}]: ${JSON.stringify(response.data)}`
            );
        }

        const { access_token, expires_in } = response.data;

        this.cache = {
            accessToken: access_token,
            expiresAt: Date.now() + (expires_in ?? 3600) * 1000
        };

        return access_token;
    }
}
