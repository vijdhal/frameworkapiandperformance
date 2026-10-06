import fs from 'fs';
import path from 'path';

const TOKEN_CACHE = path.join(process.cwd(), '.token-cache.json');

export class TokenManager {
    private static token: string | undefined;

    static setToken(token: string) {
        this.token = token;
        try {
            fs.writeFileSync(TOKEN_CACHE, JSON.stringify({ token }), 'utf-8');
        } catch {
            // in-memory only if file write fails
        }
    }

    static getToken(): string | undefined {
        if (this.token) return this.token;
        try {
            if (fs.existsSync(TOKEN_CACHE)) {
                const cache = JSON.parse(fs.readFileSync(TOKEN_CACHE, 'utf-8'));
                this.token = cache.token;
                return this.token;
            }
        } catch {
            // fall through to undefined
        }
        return undefined;
    }

    static clearToken() {
        this.token = undefined;
        try {
            if (fs.existsSync(TOKEN_CACHE)) fs.unlinkSync(TOKEN_CACHE);
        } catch {
            // ignore
        }
    }
}