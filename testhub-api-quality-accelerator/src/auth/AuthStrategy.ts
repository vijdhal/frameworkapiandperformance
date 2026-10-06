export interface AuthStrategy {
    applyAuth(headers: Record<string, string>): Promise<void>;
}
