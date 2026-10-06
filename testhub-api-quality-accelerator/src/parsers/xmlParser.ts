import { XMLParser, XMLBuilder } from "fast-xml-parser";

export class XmlParser {

    private static parser = new XMLParser({
        ignoreAttributes: false,
        attributeNamePrefix: "@_",
        parseAttributeValue: true,
        trimValues: true
    });

    private static builder = new XMLBuilder({
        ignoreAttributes: false,
        attributeNamePrefix: "@_",
        format: true
    });

    static parse(xml: string): any {

        if (!xml || xml.trim() === "") {
            return {};
        }

        return this.parser.parse(xml);
    }

    static stringify(json: any): string {

        return this.builder.build(json);
    }

    static getValue(xml: string, path: string): any {

        const json = this.parse(xml);

        return path
            .split(".")
            .reduce((obj, key) => obj?.[key], json);
    }
}