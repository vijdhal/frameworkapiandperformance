/**
 * Usage:  npm run new-api <api-name>
 * Example: npm run new-api orders
 *
 * Creates:
 *   test-data/excel/<api-name>-tests.xlsx   — Excel template with all columns pre-filled
 *   test-data/json/<api-name>/              — folder for expected response JSON files
 *   test-data/request/json/<api-name>/      — folder for request payload JSON files
 *   contracts/openapi/<api-name>.yaml       — OpenAPI spec stub
 *   tests/api/<api-name>.spec.ts            — ready-to-run Playwright spec
 */

import fs from 'fs';
import path from 'path';
import xlsx from 'xlsx';

const apiName = process.argv[2];

if (!apiName || !/^[a-z][a-z0-9-]*$/.test(apiName)) {
    console.error('Usage: npm run new-api <api-name>');
    console.error('       api-name must be lowercase letters, digits, or hyphens (e.g. "orders")');
    process.exit(1);
}

const root          = path.resolve(__dirname, '..');
const excelPath     = path.join(root, 'test-data', 'excel', `${apiName}-tests.xlsx`);
const jsonDir       = path.join(root, 'test-data', 'json', apiName);
const requestJsonDir = path.join(root, 'test-data', 'request', 'json', apiName);
const contractPath  = path.join(root, 'contracts', 'openapi', `${apiName}.yaml`);
const specPath      = path.join(root, 'tests', 'api', `${apiName}.spec.ts`);

// ── 1. Excel template ──────────────────────────────────────────────────────
const headers = [
    'name', 'endpoint', 'method', 'expectedStatus',
    'service', 'authType', 'headers', 'requestBodyFile',
    'expectedFile', 'maxResponseMs',
    'cleanupEndpoint', 'cleanupMethod',
    'extractField', 'injectAs',
    'contractFile'
];

const exampleRow = [
    `Get ${apiName}`, `/api/${apiName}/1`, 'GET', 200,
    '', 'none', '', '',
    '', '',
    '', '',
    '', '',
    `contracts/openapi/${apiName}.yaml`
];

const wb = xlsx.utils.book_new();
const ws = xlsx.utils.aoa_to_sheet([headers, exampleRow]);

// Column width hints
ws['!cols'] = headers.map(h => ({ wch: Math.max(h.length + 4, 18) }));

xlsx.utils.book_append_sheet(wb, ws, apiName.toUpperCase());
xlsx.writeFile(wb, excelPath);
console.log(`✓ Excel template   → ${excelPath}`);

// ── 2. JSON expected-response folder ──────────────────────────────────────
fs.mkdirSync(jsonDir, { recursive: true });
const placeholderJson = {
    id: '__GT__:0',
    _comment: 'Replace these with real SmartComparator expectations. See README for operators.'
};
fs.writeFileSync(
    path.join(jsonDir, `get-${apiName}.json`),
    JSON.stringify(placeholderJson, null, 2)
);
console.log(`✓ JSON folder      → ${jsonDir}/`);

// ── 2b. JSON request-payload folder ────────────────────────────────────────
fs.mkdirSync(requestJsonDir, { recursive: true });
const placeholderRequest = {
    _comment: 'Add request payload JSON files here and reference them via the requestBodyFile column.'
};
fs.writeFileSync(
    path.join(requestJsonDir, `create-${apiName}.json`),
    JSON.stringify(placeholderRequest, null, 2)
);
console.log(`✓ Request folder   → ${requestJsonDir}/`);

// ── 3. OpenAPI contract stub ───────────────────────────────────────────────
if (!fs.existsSync(contractPath)) {
    const contractStub = `openapi: "3.0.0"
info:
  title: ${apiName} API
  version: "1.0.0"
paths:
  /api/${apiName}/{id}:
    get:
      summary: Get ${apiName} by id
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: integer
`;
    fs.writeFileSync(contractPath, contractStub);
    console.log(`✓ OpenAPI stub     → ${contractPath}`);
} else {
    console.log(`  OpenAPI spec already exists — skipped: ${contractPath}`);
}

// ── 4. Playwright spec ─────────────────────────────────────────────────────
const specContent = `import { test, expect } from '@playwright/test';
import fs from 'fs';

import { APIClient } from '../../src/client/apiClient';
import { DataLoader } from '../../src/utils/dataLoader';
import { RequestBuilder } from '../../src/utils/requestBuilder';
import { SmartComparator } from '../../src/utils/smartComparator';
import { AuthStrategyResolver } from '../../src/auth/AuthStrategyResolver';
import { ReportHelper } from '../../src/utils/reportHelper';
import { ContractValidator } from '../../src/validators/contractValidator';
import { ContextStore } from '../../src/utils/contextStore';
import { Config } from '../../config/config';

const testData = DataLoader.loadExcel('test-data/excel/${apiName}-tests.xlsx', '${apiName.toUpperCase()}');

// Parallel by default. Serial ONLY when this sheet actually chains: a row that
// extracts a value into ContextStore for a later row to consume needs a single
// worker, because ContextStore is process-local and a parallel describe is spread
// across worker processes. Chaining is declared in the data (extractField +
// injectAs), so the mode is read from the data instead of assumed.
// A missing ctx: token resolves to the literal "{{ctx:key}}" rather than throwing,
// so getting this wrong reads as a pass. That is why it is not hard-coded.
// For unconditional parallel, replace the ternary with 'parallel'.
const CHAINS_BETWEEN_TESTS = testData.some(row => row.extractField && row.injectAs);

test.describe.configure({ mode: CHAINS_BETWEEN_TESTS ? 'serial' : 'parallel' });

test.describe('${apiName.charAt(0).toUpperCase() + apiName.slice(1)} API Tests', () => {

    for (const row of testData) {

        test(\`[\${row.method}] \${row.name}\`, async ({}, testInfo) => {

            const client  = new APIClient();
            await client.init();

            const baseUrl = Config.getServiceUrl(row.service);
            const auth    = AuthStrategyResolver.resolve(row.authType);

            const request = await test.step('Build Request', async () =>
                RequestBuilder.build(row, baseUrl, auth)
            );
            ReportHelper.attachRequest(testInfo, request);

            const response = await test.step('Send Request', async () =>
                client.send(request)
            );

            const status = response.status();
            const body   = status !== 204 ? await response.json() : null;
            ReportHelper.attachResponse(testInfo, status, body);

            await test.step('Validate Status', async () => {
                expect(status, \`Expected \${row.expected.status}, got \${status}\`).toBe(row.expected.status);
            });

            if (row.expected.maxResponseMs !== undefined) {
                await test.step(\`Validate Response Time ≤ \${row.expected.maxResponseMs}ms\`, async () => {
                    expect(response.elapsedMs).toBeLessThanOrEqual(row.expected.maxResponseMs!);
                });
            }

            if (body && row.expected.file) {
                await test.step('Validate Response Body', async () => {
                    const expectedJson = JSON.parse(fs.readFileSync(row.expected.file!, 'utf-8'));
                    SmartComparator.compare(body, expectedJson);
                });
            }

            if (body && row.contractFile) {
                await test.step('Validate Schema (OpenAPI)', async () => {
                    try {
                        await ContractValidator.validate(row.contractFile!, row.endpoint, row.method, status, body);
                    } catch (err: any) {
                        if (err.message?.startsWith('No schema found')) {
                            testInfo.annotations.push({ type: 'Schema', description: \`No contract for \${row.method} \${row.endpoint} — skipped\` });
                            return;
                        }
                        throw err;
                    }
                });
            }

            if (body && row.extractField && row.injectAs) {
                await test.step(\`Extract "\${row.extractField}" → ctx:\${row.injectAs}\`, async () => {
                    const value = ContextStore.extract(body, row.extractField!);
                    if (value === undefined || value === null) {
                        throw new Error(\`extractField "\${row.extractField}" not found in response body\`);
                    }
                    ContextStore.set(row.injectAs!, value);
                });
            }

            if (row.cleanupEndpoint) {
                await test.step(\`Cleanup: \${row.cleanupMethod} \${row.cleanupEndpoint}\`, async () => {
                    const cleanupRequest = await RequestBuilder.build(
                        { endpoint: row.cleanupEndpoint, method: row.cleanupMethod ?? 'DELETE', headers: row.headers },
                        baseUrl, auth
                    );
                    await client.send(cleanupRequest);
                });
            }
        });
    }
});
`;

if (fs.existsSync(specPath)) {
    console.log(`  Spec already exists — skipped: ${specPath}`);
} else {
    fs.writeFileSync(specPath, specContent);
    console.log(`✓ Playwright spec  → ${specPath}`);
}

console.log(`\nDone! Next steps:`);
console.log(`  1. Open test-data/excel/${apiName}-tests.xlsx and add your test rows`);
console.log(`  2. Add expected JSON files to test-data/json/${apiName}/`);
console.log(`  3. Add request payload JSON files to test-data/request/json/${apiName}/ and reference them via requestBodyFile`);
console.log(`  4. Update contracts/openapi/${apiName}.yaml with your API schema`);
console.log(`  5. Run: npm run test:dev -- --grep "${apiName}"`);
