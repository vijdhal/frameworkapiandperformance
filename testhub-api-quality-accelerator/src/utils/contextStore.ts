export class ContextStore {
    private static store: Record<string, any> = {};

    static set(key: string, value: any): void {
        this.store[key] = value;
    }

    static get(key: string): any {
        return this.store[key];
    }

    static getAll(): Record<string, any> {
        return { ...this.store };
    }

    static clear(): void {
        this.store = {};
    }

    // Resolve a dotted field path from a response body: "data.id" → body.data.id
    static extract(obj: any, fieldPath: string): any {
        return fieldPath.split('.').reduce((acc, key) => acc?.[key], obj);
    }
}
