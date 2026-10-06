import { XMLParser } from "fast-xml-parser";
import { expect } from "@playwright/test";

export class XmlValidator {

    private static parser = new XMLParser({
        ignoreAttributes: false,
        attributeNamePrefix: "@_"
    });

    static validate(xml: string, expected?: any): any {

        const json = this.parser.parse(xml);

        if (!expected) {
            return json;
        }

        if (expected.body) {

            for (const [key, value] of Object.entries(expected.body)) {

                const actual = this.getValue(json, key);

                expect(actual).toEqual(value);
            }
        }

        return json;
    }

    private static getValue(obj: any, path: string): any {

        return path.split(".").reduce((o, k) => o?.[k], obj);
    }
}