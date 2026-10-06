import { randomUUID } from 'crypto';

export class TemplateEngine {

    static resolve(value: any, context: Record<string, any> = {}): any {
        if (typeof value === 'string') {
            return value.replace(/\{\{([^}]+)\}\}/g, (match, expr) => {
                const token = expr.trim();

                if (token === 'timestamp') return String(Date.now());
                if (token === 'uuid')      return randomUUID();
                if (token === 'isoDate')   return new Date().toISOString();
                if (token === 'date')      return new Date().toISOString().split('T')[0];

                if (token.startsWith('env:')) {
                    return process.env[token.slice(4)] ?? '';
                }

                if (token.startsWith('ctx:')) {
                    const key = token.slice(4);
                    return context[key] !== undefined ? String(context[key]) : match;
                }

                return match;
            });
        }

        if (Array.isArray(value)) {
            return value.map(item => this.resolve(item, context));
        }

        if (typeof value === 'object' && value !== null) {
            const result: Record<string, any> = {};
            for (const [k, v] of Object.entries(value)) {
                result[k] = this.resolve(v, context);
            }
            return result;
        }

        return value;
    }
}
