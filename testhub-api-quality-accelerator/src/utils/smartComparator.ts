import { expect } from '@playwright/test';

export class SmartComparator {

    static compare(actual: any, expected: any, path: string = '') {

        // ── Scalar sentinels ────────────────────────────────────────────────

        // Skip field entirely
        if (expected === '__IGNORE__') return;

        // FIX: was only checking null — now also catches undefined
        if (expected === '__NOT_NULL__') {
            expect(actual, `${path} should not be null or undefined`).not.toBeNull();
            expect(actual, `${path} should not be null or undefined`).not.toBeUndefined();
            return;
        }

        // Stricter version: field must exist AND have a non-null/undefined value
        if (expected === '__DEFINED__') {
            expect(actual, `${path} should be defined`).not.toBeNull();
            expect(actual, `${path} should be defined`).not.toBeUndefined();
            return;
        }

        // Non-empty string, array, or object
        if (expected === '__NOT_EMPTY__') {
            if (typeof actual === 'string' || Array.isArray(actual)) {
                expect(actual.length, `${path} should not be empty`).toBeGreaterThan(0);
            } else if (typeof actual === 'object' && actual !== null) {
                expect(Object.keys(actual).length, `${path} should not be empty`).toBeGreaterThan(0);
            } else {
                throw new Error(`${path}: __NOT_EMPTY__ is not applicable to type "${typeof actual}"`);
            }
            return;
        }

        // ── String-prefixed operators ────────────────────────────────────────

        if (typeof expected === 'string') {

            // Regex match
            if (expected.startsWith('__REGEX__:')) {
                const pattern = expected.slice('__REGEX__:'.length);
                expect(String(actual), `${path} regex mismatch`).toMatch(new RegExp(pattern));
                return;
            }

            // Greater than
            if (expected.startsWith('__GT__:')) {
                const n = Number(expected.slice('__GT__:'.length));
                expect(actual, `${path} should be > ${n}`).toBeGreaterThan(n);
                return;
            }

            // Greater than or equal
            if (expected.startsWith('__GTE__:')) {
                const n = Number(expected.slice('__GTE__:'.length));
                expect(actual, `${path} should be >= ${n}`).toBeGreaterThanOrEqual(n);
                return;
            }

            // Less than
            if (expected.startsWith('__LT__:')) {
                const n = Number(expected.slice('__LT__:'.length));
                expect(actual, `${path} should be < ${n}`).toBeLessThan(n);
                return;
            }

            // Less than or equal
            if (expected.startsWith('__LTE__:')) {
                const n = Number(expected.slice('__LTE__:'.length));
                expect(actual, `${path} should be <= ${n}`).toBeLessThanOrEqual(n);
                return;
            }

            // Inclusive range  e.g. __BETWEEN__:1,100
            if (expected.startsWith('__BETWEEN__:')) {
                const [rawMin, rawMax] = expected.slice('__BETWEEN__:'.length).split(',');
                const min = Number(rawMin);
                const max = Number(rawMax);
                expect(actual, `${path} should be >= ${min}`).toBeGreaterThanOrEqual(min);
                expect(actual, `${path} should be <= ${max}`).toBeLessThanOrEqual(max);
                return;
            }

            // String/array contains value
            if (expected.startsWith('__CONTAINS__:')) {
                const val = expected.slice('__CONTAINS__:'.length);
                expect(actual, `${path} should contain "${val}"`).toContain(val);
                return;
            }

            // String starts with prefix
            if (expected.startsWith('__STARTS_WITH__:')) {
                const prefix = expected.slice('__STARTS_WITH__:'.length);
                if (!String(actual).startsWith(prefix)) {
                    throw new Error(`${path}: expected to start with "${prefix}", got "${actual}"`);
                }
                return;
            }

            // String ends with suffix
            if (expected.startsWith('__ENDS_WITH__:')) {
                const suffix = expected.slice('__ENDS_WITH__:'.length);
                if (!String(actual).endsWith(suffix)) {
                    throw new Error(`${path}: expected to end with "${suffix}", got "${actual}"`);
                }
                return;
            }

            // Allowed values (enum)  e.g. __ONE_OF__:active,inactive,pending
            if (expected.startsWith('__ONE_OF__:')) {
                const allowed = expected.slice('__ONE_OF__:'.length).split(',').map(s => s.trim());
                if (!allowed.includes(String(actual))) {
                    throw new Error(`${path}: "${actual}" is not one of [${allowed.join(', ')}]`);
                }
                return;
            }

            // Exact length of string or array  e.g. __LENGTH__:10
            if (expected.startsWith('__LENGTH__:')) {
                const len = Number(expected.slice('__LENGTH__:'.length));
                expect((actual as any).length, `${path} length should be ${len}`).toBe(len);
                return;
            }

            // Array contains a specific item  e.g. __ARRAY_CONTAINS__:admin
            if (expected.startsWith('__ARRAY_CONTAINS__:')) {
                const val = expected.slice('__ARRAY_CONTAINS__:'.length).trim();
                if (!Array.isArray(actual)) {
                    throw new Error(`${path}: expected an array for __ARRAY_CONTAINS__`);
                }
                const found = actual.some((item: any) => String(item) === val || item === val);
                if (!found) {
                    throw new Error(`${path}: array does not contain "${val}"`);
                }
                return;
            }

            // Type check  e.g. __TYPE__:string
            if (expected.startsWith('__TYPE__:')) {
                const type = expected.slice('__TYPE__:'.length);
                expect(typeof actual, `${path} type mismatch`).toBe(type);
                return;
            }
        }

        // ── Structural comparisons ───────────────────────────────────────────

        // Array: strict length + per-item recursive comparison
        if (Array.isArray(expected)) {
            expect(Array.isArray(actual), `${path} should be an array`).toBe(true);
            expect(actual.length, `${path} array length mismatch`).toBe(expected.length);
            for (let i = 0; i < expected.length; i++) {
                this.compare(actual[i], expected[i], `${path}[${i}]`);
            }
            return;
        }

        // Object: validate every key present in expected (extra keys in actual are allowed)
        if (typeof expected === 'object' && expected !== null) {
            for (const key of Object.keys(expected)) {
                if (!(key in actual)) {
                    throw new Error(`Missing field: ${path ? `${path}.${key}` : key}`);
                }
                this.compare(actual[key], expected[key], path ? `${path}.${key}` : key);
            }
            return;
        }

        // ── Default exact equality ───────────────────────────────────────────
        expect(actual, `${path} value mismatch`).toEqual(expected);
    }
}
