import { test, expect } from '@playwright/test';
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

const testData = DataLoader.loadExcel('test-data/excel/crud-tests.xlsx', 'CRUD');

// Serial mode ensures test-chaining (extractField → injectAs) runs in order
test.describe.configure({ mode: 'serial' });

test.describe('CRUD API Tests - Excel Driven', () => {

    for (const row of testData) {

        test(`[${row.method}] ${row.name}`, async ({}, testInfo) => {

            const client  = new APIClient();
            await client.init();

            const baseUrl = Config.getServiceUrl(row.service);
            const auth    = AuthStrategyResolver.resolve(row.authType);

            // ── STEP 1: Build Request ──────────────────────────────────────
            const request = await test.step('Build Request', async () => {
                return await RequestBuilder.build(row, baseUrl, auth);
            });

            ReportHelper.attachRequest(testInfo, request);

            // ── STEP 2: Send Request ───────────────────────────────────────
            const response = await test.step('Send Request', async () => {
                return await client.send(request);
            });

            const status = response.status();
            const body   = status !== 204 ? await response.json() : null;

            ReportHelper.attachResponse(testInfo, status, body);

            // ── STEP 3: Validate Status ────────────────────────────────────
            await test.step('Validate Status', async () => {
                expect(
                    status,
                    `Expected ${row.expected.status}, got ${status} for ${row.method} ${row.endpoint}`
                ).toBe(row.expected.status);
            });

            // ── STEP 4: Validate Response Time ─────────────────────────────
            if (row.expected.maxResponseMs !== undefined) {
                await test.step(`Validate Response Time ≤ ${row.expected.maxResponseMs}ms`, async () => {
                    expect(
                        response.elapsedMs,
                        `Response time ${response.elapsedMs}ms exceeded limit of ${row.expected.maxResponseMs}ms`
                    ).toBeLessThanOrEqual(row.expected.maxResponseMs!);
                });
            }

            // ── STEP 5: Validate Response Body ─────────────────────────────
            if (body && row.expected.file) {
                await test.step('Validate Response Body', async () => {
                    const expectedJson = JSON.parse(fs.readFileSync(row.expected.file!, 'utf-8'));
                    SmartComparator.compare(body, expectedJson);
                });
            }

            // ── STEP 6: Contract Validation ────────────────────────────────
            if (body && row.contractFile) {
                await test.step('Validate Response Schema (OpenAPI)', async () => {
                    try {
                        await ContractValidator.validate(
                            row.contractFile!,
                            row.endpoint,
                            row.method,
                            status,
                            body
                        );
                    } catch (err: any) {
                        if (err.message?.startsWith('No schema found')) {
                            testInfo.annotations.push({
                                type: 'Schema',
                                description: `No contract defined for ${row.method} ${row.endpoint} — skipped`
                            });
                            return;
                        }
                        throw err;
                    }
                });
            }

            // ── STEP 7: Extract & Store Context Value ──────────────────────
            if (body && row.extractField && row.injectAs) {
                await test.step(`Extract "${row.extractField}" → ctx:${row.injectAs}`, async () => {
                    const value = ContextStore.extract(body, row.extractField!);
                    if (value === undefined || value === null) {
                        throw new Error(
                            `extractField "${row.extractField}" not found in response body`
                        );
                    }
                    ContextStore.set(row.injectAs!, value);
                });
            }

            // ── STEP 8: Cleanup ────────────────────────────────────────────
            if (row.cleanupEndpoint) {
                await test.step(`Cleanup: ${row.cleanupMethod} ${row.cleanupEndpoint}`, async () => {
                    const cleanupRow = {
                        endpoint:    row.cleanupEndpoint,
                        method:      row.cleanupMethod ?? 'DELETE',
                        headers:     row.headers,
                        requestBody: undefined
                    };
                    const cleanupRequest = await RequestBuilder.build(cleanupRow, baseUrl, auth);
                    await client.send(cleanupRequest);
                });
            }
        });
    }
});
