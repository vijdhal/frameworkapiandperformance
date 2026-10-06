// eslint-disable-next-line @typescript-eslint/no-require-imports
const SwaggerParser = require('swagger-parser');
import OpenAPIResponseValidator from 'openapi-response-validator';

export class ContractValidator {

    static async validate(specPath: string, endpoint: string, method: string, status: number, responseBody: any) {

        const api: any = await SwaggerParser.parse(specPath);

        const path = api.paths[endpoint];
        const operation = path[method.toLowerCase()];

        const responseSchema = operation.responses[status];

        if (!responseSchema) {
            throw new Error(`No schema found for ${endpoint} ${method} ${status}`);
        }

        const validator = new OpenAPIResponseValidator({
            responses: {
                [status]: responseSchema
            }
        });

        const result = validator.validateResponse(status, responseBody);

        if (result) {
            throw new Error(JSON.stringify(result.errors, null, 2));
        }
    }
}
