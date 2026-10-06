import { AuthStrategy } from './AuthStrategy';

export interface BasicAuthConfig {
    username: string;
    password: string;
}

export class BasicAuth implements AuthStrategy {
    constructor(private config: BasicAuthConfig) {}

    async applyAuth(headers: Record<string, string>): Promise<void> {
        const encoded = Buffer.from(`${this.config.username}:${this.config.password}`).toString('base64');
        headers['Authorization'] = `Basic ${encoded}`;
    }
}
