import { AuthStrategy } from './AuthStrategy.js';

/**
 * Adds an API key header, read from __ENV (populated from .env / -e flags / CI secrets).
 */
export class ApiKeyAuth extends AuthStrategy {
    static getHeaders() {
        const apiKey = __ENV.API_KEY;
        const headerName = __ENV.API_KEY_HEADER || 'x-api-key';

        if (!apiKey) {
            throw new Error('API_KEY is not set. Pass it via .env or -e API_KEY=...');
        }

        return { [headerName]: apiKey };
    }
}
