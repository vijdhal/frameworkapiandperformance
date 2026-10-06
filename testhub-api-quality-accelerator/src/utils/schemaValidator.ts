import Ajv from 'ajv';

export class SchemaValidator {

    static validate(schema: any, data: any) {
        const ajv = new Ajv();
        const validate = ajv.compile(schema);

        const valid = validate(data);

        if (!valid) {
            throw new Error(JSON.stringify(validate.errors, null, 2));
        }
    }
}