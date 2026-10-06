import { AuthStrategy } from './AuthStrategy';

export interface ApiKeyAuthConfig {
    apiKey: string;
    headerName?: string; // defaults to 'x-api-key'
}

export class ApiKeyAuth implements AuthStrategy {
    constructor(private config: ApiKeyAuthConfig) {}

    async applyAuth(headers: Record<string, string>): Promise<void> {
        headers[this.config.headerName || 'x-api-key'] = this.config.apiKey;
    }
}
