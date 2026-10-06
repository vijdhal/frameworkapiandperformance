import { expect } from "@playwright/test";

export class JsonValidator {

    static async validate(response: any, expected?: any): Promise<any> {

        const body = await response.json();

        if (!expected) {
            return body;
        }

        if (expected.status !== undefined) {
            expect(response.status()).toBe(expected.status);
        }

        if (expected.body) {

            for (const [key, value] of Object.entries(expected.body)) {

                const actual = this.getValue(body, key);

                expect(actual).toEqual(value);
            }
        }

        return body;
    }

    private static getValue(obj: any, path: string): any {

        return path.split(".").reduce((o, k) => o?.[k], obj);
    }
}