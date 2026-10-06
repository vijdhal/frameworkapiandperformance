import { expect } from "@playwright/test";
import { JsonValidator } from "./jsonValidator";
import { XmlValidator } from "./xmlValidator";
import { SchemaValidator } from "./schemaValidator";

export class ResponseValidator {

    static async validate(
        response: any,
        expected?: any,
        schema?: object
    ): Promise<any> {

        if (expected?.status !== undefined) {
            expect(response.status()).toBe(expected.status);
        }

        const headers = response.headers();

        const contentType = String(
            headers["content-type"] ?? ""
        ).toLowerCase();

        let body: any;

        if (contentType.includes("json")) {

            body = await JsonValidator.validate(response, expected);

        }
        else if (
            contentType.includes("xml") ||
            contentType.includes("soap+xml") ||
            contentType.includes("text/xml")
        ) {

            const raw =
                typeof response.text === "function"
                    ? await response.text()
                    : await response.data();

            body = XmlValidator.validate(raw, expected);

        }
        else {

            body =
                typeof response.data === "function"
                    ? await response.data()
                    : await response.json();
        }

        if (schema) {
            SchemaValidator.validate(schema, body);
        }

        return body;
    }
}