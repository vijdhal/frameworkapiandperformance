// import { expect } from '@playwright/test';

// export class ResponseValidator {

//     static async validate(response: any, expected: any) {

//         expect(response.status()).toBe(expected.status);

//         const body = await response.json();

//         if (expected.body) {
//             for (const key in expected.body) {
//                 const actual = this.getValue(body, key);
//                 expect(actual).toBe(expected.body[key]);
//             }
//         }

//         return body;
//     }

//     static getValue(obj: any, path: string) {
//         return path.split('.').reduce((o, k) => o?.[k], obj);
//     }
// }

import { expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { XMLParser } from "fast-xml-parser";
import { isXmlContentType, isBinaryContentType, normalizeContentType } from "./payloadEncoder";

// Magic-byte signatures keyed by media type, for binary response verification.
const BINARY_SIGNATURES: Record<string, number[]> = {
    "application/pdf": [0x25, 0x50, 0x44, 0x46],       // %PDF
    "application/zip": [0x50, 0x4b, 0x03, 0x04],       // PK\x03\x04
    "image/png": [0x89, 0x50, 0x4e, 0x47],             // \x89PNG
    "image/jpeg": [0xff, 0xd8, 0xff],                  // JPEG SOI
    "image/gif": [0x47, 0x49, 0x46, 0x38],             // GIF8
};

export class ResponseValidator {

    static async validate(response: any, expected: any) {

        //----------------------------------------
        // Status
        //----------------------------------------

        if (expected?.status !== undefined) {

            expect(
                response.status(),
                `Expected status ${expected.status} but got ${response.status()}`
            ).toBe(Number(expected.status));

        }

        //----------------------------------------
        // Response Body — parsed by response Content-Type
        //----------------------------------------

        const contentType =
            typeof response.contentType === "function" ? response.contentType() : "";

        let body: any;

        if (isXmlContentType(contentType)) {
            const text = await response.text();
            body = new XMLParser({ ignoreAttributes: false }).parse(text);
        } else if (isBinaryContentType(contentType)) {
            // Binary responses are verified structurally (size + magic bytes),
            // not by field matching — return the Buffer for callers that need it.
            const buffer = response.buffer();
            this.validateBinary(buffer, contentType, expected);
            return buffer;
        } else {
            body = await response.json();
        }

        //----------------------------------------
        // Expected Body Object
        //----------------------------------------

        if (expected?.body) {

            for (const key in expected.body) {

                const actual = this.getValue(body, key);

                expect(
                    actual,
                    `Mismatch for field "${key}"`
                ).toEqual(expected.body[key]);

            }

        }

        //----------------------------------------
        // Expected File
        //----------------------------------------

        if (expected?.file) {

            const filePath = path.join(
                process.cwd(),
                expected.file
            );

            if (fs.existsSync(filePath)) {

                const expectedBody = JSON.parse(
                    fs.readFileSync(filePath, "utf8")
                );

                expect(body).toMatchObject(expectedBody);

            } else {

                console.warn(
                    `Expected response file not found: ${filePath}`
                );

            }

        }

        return body;
    }

    static getValue(obj: any, property: string) {

        return property
            .split(".")
            .reduce((o, k) => o?.[k], obj);

    }

    //----------------------------------------
    // Binary verification: size + magic-byte signature
    //----------------------------------------

    static validateBinary(buffer: Buffer, contentType: string, expected: any) {

        expect(buffer.length, "Binary response body should not be empty").toBeGreaterThan(0);

        if (expected?.minSize !== undefined) {
            expect(
                buffer.length,
                `Binary response smaller than expected minimum ${expected.minSize} bytes`
            ).toBeGreaterThanOrEqual(Number(expected.minSize));
        }

        const signature = BINARY_SIGNATURES[normalizeContentType(contentType)];

        if (signature) {
            const head = Array.from(buffer.subarray(0, signature.length));
            expect(
                head,
                `Magic-byte signature mismatch for "${contentType}"`
            ).toEqual(signature);
        }

        return buffer;
    }

}