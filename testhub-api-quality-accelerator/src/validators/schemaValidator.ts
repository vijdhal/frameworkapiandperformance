import Ajv from "ajv";
import addFormats from "ajv-formats";

export class SchemaValidator {

    private static ajv = (() => {

        const ajv = new Ajv({
            allErrors: true,
            strict: false
        });

        addFormats(ajv);

        return ajv;

    })();

    static validate(schema: object, body: any): void {

        const validate = this.ajv.compile(schema);

        const valid = validate(body);

        if (!valid) {

            throw new Error(
                JSON.stringify(validate.errors, null, 2)
            );
        }
    }
}