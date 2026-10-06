import fs from 'fs';
import path from 'path';

const LOG_FILE = path.join(process.cwd(), 'logs', 'api-test.log');

function timestamp(): string {
    return new Date().toISOString();
}

function ensureLogDir() {
    const dir = path.dirname(LOG_FILE);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
}

const SENSITIVE_HEADER_RE = /^(authorization|x-api-key|api-key|x-auth-token|cookie|set-cookie)$/i;

/** Copies `headers`, replacing values of well-known secret-carrying headers with a marker. */
export function redactHeaders(headers: Record<string, string>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(headers || {})) {
        out[key] = SENSITIVE_HEADER_RE.test(key) ? '[REDACTED]' : value;
    }
    return out;
}

function write(level: string, message: string) {
    const line = `[${timestamp()}] [${level}] ${message}`;
    console.log(line);
    try {
        ensureLogDir();
        fs.appendFileSync(LOG_FILE, line + '\n', 'utf-8');
    } catch {
        // don't fail tests if logging fails
    }
}

export const Logger = {
    info:  (msg: string) => write('INFO', msg),
    warn:  (msg: string) => write('WARN', msg),
    error: (msg: string) => write('ERROR', msg),

    request(method: string, url: string, headers: Record<string, string>, body: any) {
        write('REQUEST', `${method.toUpperCase()} ${url}`);
        if (body) write('REQUEST', `Body: ${JSON.stringify(body)}`);
    },

    response(status: number, url: string, body: any) {
        write('RESPONSE', `${status} ${url}`);
        write('RESPONSE', `Body: ${JSON.stringify(body)}`);
    }
};
