import { test } from '@playwright/test';
import fs from 'fs';
import path from 'path';

import { APIClient } from '../../src/client/apiClient';
import { DataLoader } from '../../src/utils/dataLoader';
import { RequestBuilder } from '../../src/utils/requestBuilder';
import { ResponseValidator } from '../../src/utils/responseValidator';
import { Config } from '../../config/config';
import { SmartComparator } from '../../src/utils/smartComparator';

const testData = DataLoader.loadExcel('test-data/excel/user.xlsx', 'Sheet1');

test.describe('Excel Driven Response Validation', () => {

    for (const step of testData) {
        test(step.name, async () => {

            const client = new APIClient();
            await client.init();
            const env = Config.getEnv();
            //BUILD REQUEST
            const request = await RequestBuilder.build(step, env.baseUrl);

            const response = await client.send(request);

            const body = await response.json();

            console.log(JSON.stringify(body, null, 2));

            await ResponseValidator.validate(response, step.expected);

            const fileName = step.name.toLowerCase().replace(/\s+/g, '-');

            const jsonPath = path.join(process.cwd(), 'test-data', 'json', `${fileName}.json`);

            if (fs.existsSync(jsonPath)) {
                const expected = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));

                SmartComparator.compare(body, expected);

                console.log('Smart compare passed');
            }
        }
        );
    }
}
);