import { test, expect } from '@playwright/test';

import { APIClient } from '../../src/client/apiClient';
import { DataLoader } from '../../src/utils/dataLoader';
import { RequestBuilder } from '../../src/utils/requestBuilder';
import { ContractValidator } from '../../src/validators/contractValidator';
import { AuthStrategyResolver } from '../../src/auth/AuthStrategyResolver';
import { ReportHelper } from '../../src/utils/reportHelper';
import { Config } from '../../config/config';

const testData = DataLoader.loadExcel('test-data/excel/user.xlsx', 'Sheet1');

test.describe('Schema / Contract Validation', () => {

    for (const row of testData) {

        test(`[${row.method}] ${row.name}`, async ({}, testInfo) => {

            const client  = new APIClient();
            await client.init();

            const baseUrl = Config.getServiceUrl(row.service);
            const auth    = AuthStrategyResolver.resolve(row.authType);

            // ── STEP 1: Build Request ──────────────────────────────────────
            const request = await test.step('Build Request', () =>
                RequestBuilder.build(row, baseUrl, auth)
            );

            ReportHelper.attachRequest(testInfo, request);

            // ── STEP 2: Send Request ───────────────────────────────────────
            const response = await test.step('Send Request', () =>
                client.send(request)
            );

            const status = response.status();
            const body   = status !== 204 ? await response.json() : null;

            ReportHelper.attachResponse(testInfo, status, body);

            // ── STEP 3: Validate Status ────────────────────────────────────
            await test.step(`Validate Status → ${row.expected.status}`, () => {
                expect(
                    status,
                    `Expected ${row.expected.status}, got ${status} for ${row.method} ${row.endpoint}`
                ).toBe(row.expected.status);
            });

            // ── STEP 4: Validate Response Against OpenAPI Contract ─────────
            // Prefers contractFile from Excel row; falls back to legacy user.yaml
            const specPath = row.contractFile ?? 'contracts/openapi/user.yaml';

            if (body) {
                await test.step(`Validate Schema (${specPath})`, async () => {
                    try {
                        await ContractValidator.validate(specPath, row.endpoint, row.method, status, body);
                    } catch (err: any) {
                        if (err.message?.startsWith('No schema found')) {
                            testInfo.annotations.push({
                                type: 'Schema',
                                description: `No contract defined for ${row.method} ${row.endpoint} in ${specPath} — skipped`
                            });
                            return;
                        }
                        throw err;
                    }
                });
            }
        });
    }
});
