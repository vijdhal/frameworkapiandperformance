import { test, expect } from '@playwright/test';
import fs from 'fs';

import { MockServer } from '../../mocks/mock-server';
import { APIClient } from '../../src/client/apiClient';
import { DataLoader } from '../../src/utils/dataLoader';
import { RequestBuilder } from '../../src/utils/requestBuilder';
import { SmartComparator } from '../../src/utils/smartComparator';
import { ReportHelper } from '../../src/utils/reportHelper';
import { AuthStrategyResolver } from '../../src/auth/AuthStrategyResolver';

const testData = DataLoader.loadMockExcel('test-data/excel/mock-tests.xlsx', 'MockTests');
const mock = new MockServer(4010);

test.describe('Mock Server Tests - Excel Driven', () => {

    test.beforeAll(async () => {

        // Register every route defined in the Excel sheet
        for (const row of testData) {
            const { flakyCallsToFail, ...mockConfig } = row.mock;

            if (flakyCallsToFail > 0) {
                // Stateful handler: return 503 for the first N calls, then the configured response
                mock.addRoute(row.method, row.endpoint, (callCount) =>
                    callCount <= flakyCallsToFail
                        ? { status: 503, body: { error: 'Service Unavailable' } }
                        : mockConfig
                );
            } else {
                mock.addRoute(row.method, row.endpoint, mockConfig);
            }
        }

        await mock.start();
    });

    test.afterAll(async () => await mock.stop());

    // Generate one test per Excel row
    for (const row of testData) {

        test(`[${row.method}] ${row.name}`, async ({ }, testInfo) => {

            const client = new APIClient();
            await client.init();

            const auth = AuthStrategyResolver.resolve(row.authType);

            // ── Build & send ───────────────────────────────────────────────
            const request = await test.step('Build Request', () =>
                RequestBuilder.build(row, mock.baseUrl, auth)
            );
            ReportHelper.attachRequest(testInfo, request);

            const start = Date.now();

            const response = await test.step('Send Request', () =>
                client.send(request)
            );

            const elapsed = Date.now() - start;
            const status = response.status();
            const body = status !== 204 ? await response.json() : null;

            ReportHelper.attachResponse(testInfo, status, body);

            // ── Status ─────────────────────────────────────────────────────
            await test.step(`Validate Status → ${row.expected.status}`, () =>
                expect(status).toBe(row.expected.status)
            );

            // ── Body (SmartComparator) ─────────────────────────────────────
            if (body && row.expected.file) {
                await test.step('Validate Body', () => {
                    const expectedJson = JSON.parse(fs.readFileSync(row.expected.file!, 'utf-8'));
                    SmartComparator.compare(body, expectedJson);
                });
            }

            // ── Response headers ───────────────────────────────────────────
            if (row.expected.headers) {
                await test.step('Validate Response Headers', () => {
                    const actual = response.headers();
                    for (const [key, value] of Object.entries(row.expected.headers!)) {
                        expect(actual[key.toLowerCase()], `Header: ${key}`).toBe(value);
                    }
                });
            }

            // ── Call count (retry validation) ──────────────────────────────
            if (row.expected.callCount !== undefined) {
                await test.step(`Validate Server Call Count = ${row.expected.callCount}`, () =>
                    expect(mock.callCount(row.method, row.endpoint)).toBe(row.expected.callCount)
                );
            }

            // ── Minimum response time (delay validation) ───────────────────
            if (row.expected.minDurationMs !== undefined) {
                await test.step(`Validate Response Time ≥ ${row.expected.minDurationMs}ms`, () =>
                    expect(elapsed, `Expected >= ${row.expected.minDurationMs}ms, got ${elapsed}ms`)
                        .toBeGreaterThanOrEqual(row.expected.minDurationMs!)
                );
            }
        });
    }
});
