import axios from 'axios';
import { AuthStrategy } from './AuthStrategy';

export interface SalesforceAuthConfig {
    tokenUrl: string;       // e.g. https://login.salesforce.com/services/oauth2/token
    clientId: string;       // Connected App Consumer Key
    clientSecret: string;   // Connected App Consumer Secret
    username?: string;      // only required for password grant
    password?: string;      // password + security token concatenated
}

interface TokenCache {
    accessToken: string;
    expiresAt: number;
}

/**
 * Salesforce Connected App OAuth2.
 * Uses client_credentials grant when username/password are absent,
 * otherwise falls back to the resource-owner password grant.
 * Salesforce tokens have no expires_in — session lifetime defaults to 2 h.
 */
export class SalesforceAuth implements AuthStrategy {
    private cache: TokenCache | null = null;

    constructor(private config: SalesforceAuthConfig) {}

    async applyAuth(headers: Record<string, string>): Promise<void> {
        headers['Authorization'] = `Bearer ${await this.getAccessToken()}`;
    }

    private async getAccessToken(): Promise<string> {
        if (this.cache && Date.now() < this.cache.expiresAt - 30_000) {
            return this.cache.accessToken;
        }

        const usePassword = !!(this.config.username && this.config.password);

        const body = new URLSearchParams({
            grant_type: usePassword ? 'password' : 'client_credentials',
            client_id: this.config.clientId,
            client_secret: this.config.clientSecret
        });

        if (usePassword) {
            body.set('username', this.config.username!);
            body.set('password', this.config.password!);
        }

        const response = await axios.post(this.config.tokenUrl, body.toString(), {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            validateStatus: () => true
        });

        if (response.status !== 200) {
            throw new Error(
                `Salesforce token request failed [${response.status}]: ${JSON.stringify(response.data)}`
            );
        }

        const { access_token, issued_at } = response.data;

        this.cache = {
            accessToken: access_token,
            expiresAt: issued_at ? Number(issued_at) + 7_200_000 : Date.now() + 7_200_000
        };

        return access_token;
    }
}
