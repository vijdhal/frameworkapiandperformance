import axios from 'axios';
import { AuthStrategy } from './AuthStrategy';

export interface OAuth2ClientCredentialsConfig {
    tokenUrl: string;
    clientId: string;
    clientSecret: string;
    scope?: string;
}

interface TokenCache {
    accessToken: string;
    expiresAt: number; // ms epoch
}

export class OAuth2ClientCredentials implements AuthStrategy {
    private cache: TokenCache | null = null;

    constructor(private config: OAuth2ClientCredentialsConfig) {}

    async applyAuth(headers: Record<string, string>): Promise<void> {
        headers['Authorization'] = `Bearer ${await this.getAccessToken()}`;
    }

    private async getAccessToken(): Promise<string> {
        // Reuse cached token if still valid (30s safety buffer before expiry)
        if (this.cache && Date.now() < this.cache.expiresAt - 30_000) {
            return this.cache.accessToken;
        }

        const params = new URLSearchParams({
            grant_type: 'client_credentials',
            client_id: this.config.clientId,
            client_secret: this.config.clientSecret,
            ...(this.config.scope ? { scope: this.config.scope } : {})
        });

        const response = await axios.post(this.config.tokenUrl, params.toString(), {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            validateStatus: () => true
        });

        if (response.status !== 200) {
            throw new Error(
                `OAuth2 token request failed [${response.status}]: ${JSON.stringify(response.data)}`
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
