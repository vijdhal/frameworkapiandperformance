/**
 * Auth strategy contract (documentation only — plain JS has no interfaces).
 * Every strategy exposes a static getHeaders() that returns a headers object
 * to merge into the outgoing request. Mirrors api-test-framework's AuthStrategy.ts.
 */
export class AuthStrategy {
    static getHeaders() {
        throw new Error('Not implemented — extend AuthStrategy and implement getHeaders().');
    }
}
