# API Test Framework

A reusable, data-driven API automation framework built with **TypeScript**, **Playwright**, and **Axios**, designed for MuleSoft, Salesforce, and generic REST APIs.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Quick Start — Add a New API Test in 3 Steps](#quick-start--add-a-new-api-test-in-3-steps)
- [Tester Onboarding Guide](#tester-onboarding-guide)
  - [Option A: Scaffold Command (Fastest)](#option-a-scaffold-command-fastest)
  - [Option B: Excel-Only (Zero Code)](#option-b-excel-only-zero-code)
  - [Option C: Manual Spec File (Full Control)](#option-c-manual-spec-file-full-control)
- [Excel Column Reference](#excel-column-reference)
- [Environment & Multi-Service Configuration](#environment--multi-service-configuration)
- [Authentication](#authentication)
- [Template Variables](#template-variables)
- [Test Chaining — Pass Values Between Tests](#test-chaining--pass-values-between-tests)
- [Response Time Assertions](#response-time-assertions)
- [Auto-Cleanup After POST](#auto-cleanup-after-post)
- [Response Validation](#response-validation)
- [OpenAPI Contract Validation](#openapi-contract-validation)
- [Mock Server](#mock-server)
- [Reporting](#reporting)
- [Running Tests](#running-tests)
- [CI/CD](#cicd)
- [Framework Architecture](#framework-architecture)
- [What a Tester Needs to Do — by Scenario](#what-a-tester-needs-to-do--by-scenario)

---

## Tech Stack

| Library | Version | Purpose |
|---|---|---|
| `@playwright/test` | ^1.59.1 | Test runner and assertions |
| `axios` | ^1.17.0 | HTTP client with retry + elapsed time |
| `typescript` | ^6.0.3 | Type safety |
| `ajv` | ^8.20.0 | JSON Schema validation |
| `xlsx` | ^0.18.5 | Excel test data loading |
| `js-yaml` | ^4.1.1 | YAML test data and config |
| `swagger-parser` | ^10.0.3 | OpenAPI contract parsing |
| `openapi-response-validator` | ^12.1.3 | Contract response validation |
| `ortoni-report` | ^4.0.8 | HTML test reports |
| `dotenv` | ^17.4.2 | Environment variable management |
| `cross-env` | ^10.1.0 | Cross-platform env variables |

---

## Project Structure

Since 6 September 2026 the tree has three layers: the Studio in `testhubui/`, the Playwright + Axios
accelerator at the root (api, ui and Salesforce specs share it so Ortoni gives one report), and one
folder per standalone framework under `frameworks/`.

```
testhubui/                                # TestHub Automation Studio: UI, backend, 10 engines
frameworks/
├── testhub-performance-quality-accelerator/            # the client's k6 framework, vendored as sent (see VENDORED.md)
│   ├── test-data/excel/<slug>.xlsx      #   ← the Studio writes one workbook per endpoint here
│   ├── tests/<slug>/                    #   ← and its smoke + profile tests
│   └── studio/                          #   ← self-contained k6 scripts + workbooks + options sheet
├── mobile/                              # Mobilewright workspaces
├── security/                            # ZAP plans and gates
├── llm-security/                        # garak scans
├── agentforce/                          # Agentforce test specs
└── contract/                            # SDD-vs-RAML assurance suites

api-test-framework/                      # the accelerator, at the repo root
├── config/
│   ├── config.ts                        # Environment + service URL loader
│   └── env.yaml                         # Base URLs and service URLs per environment
├── contracts/openapi/
│   └── user.yaml                        # OpenAPI spec for user endpoints
│   └── <api-name>.yaml                  # One spec per API domain
├── mocks/
│   └── mock-server.ts                   # In-process HTTP mock server
├── scripts/
│   └── scaffold.ts                      # CLI generator: npm run new-api <name>
├── src/
│   ├── auth/
│   │   ├── AuthStrategy.ts              # Interface all auth strategies implement
│   │   ├── ApiKeyAuth.ts                # x-api-key header auth
│   │   ├── BasicAuth.ts                 # Basic Auth (Base64 username:password)
│   │   ├── OAuth2ClientCredentials.ts   # OAuth2 standard client credentials
│   │   ├── MulesoftAuth.ts              # MuleSoft OAuth2 (Basic Auth header for credentials)
│   │   ├── SalesforceAuth.ts            # Salesforce Connected App OAuth2
│   │   └── AuthStrategyResolver.ts      # Maps authType string → strategy class
│   ├── client/
│   │   └── apiClient.ts                 # Axios HTTP client with retry + elapsedMs
│   ├── utils/
│   │   ├── requestBuilder.ts            # Builds request objects with auth + template resolution
│   │   ├── dataLoader.ts                # Loads Excel / YAML / Mock Excel test data
│   │   ├── templateEngine.ts            # Resolves {{uuid}}, {{timestamp}}, {{ctx:key}} etc.
│   │   ├── contextStore.ts              # In-memory store for cross-test value passing
│   │   ├── tokenManager.ts              # Token caching and persistence across workers
│   │   ├── responseValidator.ts         # Basic status + field validation
│   │   ├── smartComparator.ts           # Advanced response comparison (15+ operators)
│   │   ├── schemaValidator.ts           # AJV JSON Schema validation
│   │   ├── logger.ts                    # File + console request/response logger
│   │   └── reportHelper.ts              # Attaches request/response to Ortoni report
│   ├── services/
│   │   └── userService.ts               # Token and user ID extractors
│   └── validators/
│       └── contractValidator.ts         # OpenAPI contract validation
├── test-data/
│   ├── excel/                           # Excel test data files (one per API domain)
│   ├── json/                            # Expected response files for SmartComparator
│   └── yaml/                            # YAML test scenarios
├── tests/api/
│   ├── crudExcel.spec.ts                # Excel-driven CRUD tests (GET/POST/PUT/DELETE)
│   ├── mockServer.spec.ts               # Excel-driven mock server tests
│   ├── responsevalidateExcel.spec.ts    # Excel + SmartComparator response validation
│   └── schemaValidation.spec.ts         # Excel-driven OpenAPI contract validation
├── reports/                             # Generated Ortoni reports (gitignored)
├── logs/                                # Runtime request/response logs (gitignored)
├── .env                                 # Secrets — never commit this file
├── playwright.config.ts
├── tsconfig.json
└── package.json
```

---

## Setup

### Prerequisites

- Node.js 18+
- npm

### Install

```bash
npm install
npx playwright install --with-deps chromium
```

### Configure your `.env` file

Create a `.env` file in the project root. This file is gitignored — never commit it.

```env
# ── Generic / REST Auth ───────────────────────────────────────────────
API_KEY=your_api_key_here
API_KEY_HEADER=x-api-key          # optional: override default header name

# Basic Auth
BASIC_USERNAME=your_username
BASIC_PASSWORD=your_password

# OAuth2 Standard Client Credentials
OAUTH2_TOKEN_URL=https://your-domain/oauth/token
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
OAUTH2_SCOPE=read:api

# Custom token header
AUTH_TOKEN=your_token
AUTH_HEADER_NAME=X-Auth-Token

# API key as query param
API_KEY_QUERY=your_key

# ── MuleSoft Auth ─────────────────────────────────────────────────────
MULESOFT_TOKEN_URL=https://anypoint.mulesoft.com/accounts/api/v2/oauth2/token
MULESOFT_CLIENT_ID=your_mulesoft_client_id
MULESOFT_CLIENT_SECRET=your_mulesoft_client_secret
MULESOFT_SCOPE=                   # optional

# ── Salesforce Auth ───────────────────────────────────────────────────
SF_TOKEN_URL=https://login.salesforce.com/services/oauth2/token
SF_CLIENT_ID=your_connected_app_consumer_key
SF_CLIENT_SECRET=your_connected_app_consumer_secret
SF_USERNAME=                      # only for password grant — leave blank for client_credentials
SF_PASSWORD=                      # password + security token concatenated
```

---

## Quick Start — Add a New API Test in 3 Steps

This is the fastest path for any tester with a new API endpoint.

**Step 1 — Generate the skeleton**

```bash
npm run new-api orders
```

This creates:
- `test-data/excel/orders-tests.xlsx` — Excel template with all columns pre-filled
- `test-data/json/orders/` — folder for expected response JSON files
- `test-data/request/json/orders/` — folder for request payload JSON files
- `contracts/openapi/orders.yaml` — OpenAPI spec stub
- `tests/api/orders.spec.ts` — ready-to-run Playwright spec

**Step 2 — Fill in the Excel file**

Open `test-data/excel/orders-tests.xlsx` and add one row per test case (see [Excel Column Reference](#excel-column-reference)).

**Step 3 — Run**

```bash
npm run test:dev -- --grep "orders"
```

That's it. No TypeScript editing required for most test cases.

---

## Tester Onboarding Guide

There are three ways to add tests, ordered from least effort to most control.

---

### Option A: Scaffold Command (Fastest)

Use this when testing a brand-new API domain (e.g., Orders, Payments, Inventory).

```bash
npm run new-api <api-name>
```

**What gets created:**

| File | Purpose |
|---|---|
| `test-data/excel/<api-name>-tests.xlsx` | Excel file with all column headers ready |
| `test-data/json/<api-name>/` | Folder for SmartComparator expected JSON files |
| `test-data/request/json/<api-name>/` | Folder for request payload JSON files |
| `contracts/openapi/<api-name>.yaml` | OpenAPI spec stub to fill in |
| `tests/api/<api-name>.spec.ts` | Fully wired Playwright spec — ready to run |

**After scaffolding:**

1. Open the Excel file — add one row per test case
2. Fill in `contracts/openapi/<api-name>.yaml` if you want contract validation
3. For each row with an `expectedFile`, create the JSON file under `test-data/json/<api-name>/`
4. For each row with a `requestBodyFile` (POST/PUT/PATCH), create the payload JSON file under `test-data/request/json/<api-name>/`
5. Run: `npm run test:dev -- --grep "<api-name>"`

---

### Option B: Excel-Only (Zero Code)

Use this when adding tests to an **existing** API (e.g., adding more CRUD rows to `crud-tests.xlsx`).

**Step 1 — Open the Excel file**

File: `test-data/excel/crud-tests.xlsx`, sheet: `CRUD`

**Step 2 — Add a row**

| Column | Example value |
|---|---|
| `name` | `Get Order by ID` |
| `endpoint` | `/api/orders/123` |
| `method` | `GET` |
| `expectedStatus` | `200` |
| `service` | `mulesoft` *(or leave blank for default baseUrl)* |
| `authType` | `oauth2` |
| `headers` | `{"Accept":"application/json"}` |
| `requestBodyFile` | *(leave blank for GET)* |
| `expectedFile` | `test-data/json/get-order.json` *(optional)* |
| `maxResponseMs` | `3000` *(optional — fail if response takes longer)* |
| `extractField` | `data.id` *(optional — extract value for chaining)* |
| `injectAs` | `orderId` *(optional — store extracted value as ctx:orderId)* |
| `cleanupEndpoint` | `/api/orders/{{ctx:orderId}}` *(optional — auto-delete after test)* |
| `cleanupMethod` | `DELETE` *(optional — defaults to DELETE)* |
| `contractFile` | `contracts/openapi/orders.yaml` *(optional — OpenAPI validation)* |

**Step 3 — Create the expected JSON file** *(only if `expectedFile` is set)*

Create `test-data/json/get-order.json`:
```json
{
    "id": "__GT__:0",
    "status": "__ONE_OF__:pending,shipped,delivered",
    "customerId": "__NOT_NULL__",
    "total": "__GTE__:0"
}
```

**Step 3b — Create the request payload JSON file** *(only if `requestBodyFile` is set, e.g. POST/PUT/PATCH)*

Create `test-data/request/json/create-order.json`:
```json
{
    "customerId": "{{ctx:customerId}}",
    "items": [{ "sku": "ABC123", "qty": 2 }]
}
```

Then set `requestBodyFile` in the Excel row to `test-data/request/json/create-order.json`.

**Step 4 — Run**

```bash
npm run test:dev
```

---

### Option C: Manual Spec File (Full Control)

Use this when you need custom logic that Excel cannot express — e.g., conditional flows, loops, or complex setup steps.

**Step 1 — Create the spec file**

Create `tests/api/<api-name>.spec.ts`:

```typescript
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

// Load test data from Excel
const testData = DataLoader.loadExcel('test-data/excel/<api-name>-tests.xlsx', 'SHEET_NAME');

// serial mode is required when tests chain values via ContextStore
test.describe.configure({ mode: 'serial' });

test.describe('<API Name> Tests', () => {

    for (const row of testData) {

        test(`[${row.method}] ${row.name}`, async ({}, testInfo) => {

            const client  = new APIClient();
            await client.init();

            // Resolves service URL from env.yaml (falls back to baseUrl if service is blank)
            const baseUrl = Config.getServiceUrl(row.service);
            const auth    = AuthStrategyResolver.resolve(row.authType);

            // ── STEP 1: Build Request ──────────────────────────────────────
            // Template variables ({{uuid}}, {{ctx:orderId}} etc.) are resolved here
            const request = await test.step('Build Request', async () =>
                RequestBuilder.build(row, baseUrl, auth)
            );
            ReportHelper.attachRequest(testInfo, request);

            // ── STEP 2: Send Request ───────────────────────────────────────
            const response = await test.step('Send Request', async () =>
                client.send(request)
            );

            const status = response.status();
            const body   = status !== 204 ? await response.json() : null;
            ReportHelper.attachResponse(testInfo, status, body);

            // ── STEP 3: Validate Status ────────────────────────────────────
            await test.step('Validate Status', async () => {
                expect(status, `Expected ${row.expected.status}, got ${status}`).toBe(row.expected.status);
            });

            // ── STEP 4: Validate Response Time ─────────────────────────────
            if (row.expected.maxResponseMs !== undefined) {
                await test.step(`Validate Response Time ≤ ${row.expected.maxResponseMs}ms`, async () => {
                    expect(response.elapsedMs).toBeLessThanOrEqual(row.expected.maxResponseMs!);
                });
            }

            // ── STEP 5: Validate Response Body (SmartComparator) ──────────
            if (body && row.expected.file) {
                await test.step('Validate Response Body', async () => {
                    const expectedJson = JSON.parse(fs.readFileSync(row.expected.file!, 'utf-8'));
                    SmartComparator.compare(body, expectedJson);
                });
            }

            // ── STEP 6: Contract Validation (OpenAPI) ─────────────────────
            if (body && row.contractFile) {
                await test.step('Validate Schema (OpenAPI)', async () => {
                    try {
                        await ContractValidator.validate(
                            row.contractFile!, row.endpoint, row.method, status, body
                        );
                    } catch (err: any) {
                        if (err.message?.startsWith('No schema found')) {
                            testInfo.annotations.push({
                                type: 'Schema',
                                description: `No contract for ${row.method} ${row.endpoint} — skipped`
                            });
                            return;
                        }
                        throw err;
                    }
                });
            }

            // ── STEP 7: Extract Value for Chaining ────────────────────────
            if (body && row.extractField && row.injectAs) {
                await test.step(`Extract "${row.extractField}" → ctx:${row.injectAs}`, async () => {
                    const value = ContextStore.extract(body, row.extractField!);
                    if (value === undefined || value === null) {
                        throw new Error(`extractField "${row.extractField}" not found in response`);
                    }
                    ContextStore.set(row.injectAs!, value);
                });
            }

            // ── STEP 8: Cleanup ────────────────────────────────────────────
            if (row.cleanupEndpoint) {
                await test.step(`Cleanup: ${row.cleanupMethod} ${row.cleanupEndpoint}`, async () => {
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
```

**Step 2 — Create the Excel file**

Either run `npm run new-api <api-name>` to generate it, or create `test-data/excel/<api-name>-tests.xlsx` manually with the columns listed in the [Excel Column Reference](#excel-column-reference).

**Step 3 — Run**

```bash
npm run test:dev -- --grep "<API Name>"
```

---

## Excel Column Reference

All columns supported in `DataLoader.loadExcel()`. Use in any Excel test data file.

| Column | Required | Type | Description |
|---|---|---|---|
| `name` | Yes | string | Test case name — shown in Playwright output and reports |
| `endpoint` | Yes | string | API path e.g. `/api/orders/{{ctx:orderId}}` — supports template variables |
| `method` | Yes | string | `GET` / `POST` / `PUT` / `PATCH` / `DELETE` |
| `expectedStatus` | Yes | number | Expected HTTP status code e.g. `200`, `201`, `204` |
| `service` | No | string | Named service key from `env.yaml` e.g. `mulesoft`, `salesforce`, `generic`. Leave blank to use `baseUrl` |
| `authType` | No | string | See [Authentication](#authentication). Leave blank to use RequestBuilder defaults |
| `headers` | No | JSON | Custom request headers e.g. `{"Accept":"application/json","X-Tenant":"abc"}` |
| `requestBodyFile` | No | string | Path to a JSON file holding the request body for POST/PUT/PATCH e.g. `test-data/request/json/create-order.json` — contents support template variables |
| `expectedFile` | No | string | Path to SmartComparator JSON file e.g. `test-data/json/orders/get-order.json` |
| `maxResponseMs` | No | number | Maximum allowed response time in milliseconds. Test fails if exceeded |
| `extractField` | No | string | Dotted path to extract from response body e.g. `data.id`, `result.token` |
| `injectAs` | No | string | Variable name to store extracted value under (used as `{{ctx:<name>}}` in later rows) |
| `cleanupEndpoint` | No | string | Endpoint to call after test completes e.g. `/api/orders/{{ctx:orderId}}` |
| `cleanupMethod` | No | string | HTTP method for cleanup. Defaults to `DELETE` |
| `contractFile` | No | string | Path to OpenAPI spec for this row e.g. `contracts/openapi/orders.yaml` |

---

## Environment & Multi-Service Configuration

### `config/env.yaml`

Define base URLs and named service URLs per environment:

```yaml
dev:
  baseUrl: https://your-dev-api.com        # default when no service column is set
  services:
    generic:     https://your-dev-api.com
    mulesoft:    https://mulesoft-dev.yourcompany.com
    salesforce:  https://login.salesforce.com

qa:
  baseUrl: https://your-qa-api.com
  services:
    generic:     https://your-qa-api.com
    mulesoft:    https://mulesoft-qa.yourcompany.com
    salesforce:  https://login.salesforce.com

sit:
  baseUrl: https://your-sit-api.com
  services:
    generic:     https://your-sit-api.com
    mulesoft:    https://mulesoft-sit.yourcompany.com
    salesforce:  https://login.salesforce.com
```

### Adding a new service

1. Add the service URL under each environment in `env.yaml`
2. Set the `service` column in your Excel row to the new key
3. Optionally add a CI override: `SERVICE_URL_<NAME>` env var takes precedence over the YAML

### URL resolution order

```
1. SERVICE_URL_<NAME> env var  ← CI/CD override (highest priority)
2. env.yaml services[service]  ← named service URL
3. env.yaml baseUrl            ← default (when service column is blank)
4. BASE_URL env var            ← legacy CI override for baseUrl
```

### In a spec file

```typescript
import { Config } from '../../config/config';

// Uses service column from Excel row — falls back to baseUrl if blank
const baseUrl = Config.getServiceUrl(row.service);

// Or directly by name
const mulesoftUrl = Config.getServiceUrl('mulesoft');
```

---

## Authentication

All auth strategies are pluggable. Set the `authType` column in Excel to choose which one to use.

### Available auth types

| `authType` value | Class | Required `.env` variables |
|---|---|---|
| `apikey` | `ApiKeyAuth` | `API_KEY`, `API_KEY_HEADER` *(optional, default: x-api-key)* |
| `basic` | `BasicAuth` | `BASIC_USERNAME`, `BASIC_PASSWORD` |
| `oauth2` | `OAuth2ClientCredentials` | `OAUTH2_TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, `OAUTH2_SCOPE` |
| `mulesoft` | `MulesoftAuth` | `MULESOFT_TOKEN_URL`, `MULESOFT_CLIENT_ID`, `MULESOFT_CLIENT_SECRET` |
| `salesforce` | `SalesforceAuth` | `SF_TOKEN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET` *(+ `SF_USERNAME`, `SF_PASSWORD` for password grant)* |
| `none` | No-op | *(no credentials added)* |
| *(blank)* | RequestBuilder defaults | Tries API_KEY → Bearer → Basic → custom header in order |

### MuleSoft vs OAuth2

- `oauth2` — sends `client_id` and `client_secret` in the **request body** (standard RFC 6749)
- `mulesoft` — sends them as an **HTTP Basic Auth header** (`Authorization: Basic base64(id:secret)`) — this is the Anypoint Platform convention

### Salesforce grant types

- **Client credentials** (default) — set `SF_CLIENT_ID` and `SF_CLIENT_SECRET` only
- **Password grant** — also set `SF_USERNAME` and `SF_PASSWORD` (password + security token concatenated)

### Token caching

All OAuth2 strategies cache the token in memory and reuse it until 30 seconds before expiry. No repeated token fetches within a single test run.

### Adding a custom auth strategy

1. Create `src/auth/MyCustomAuth.ts` implementing the `AuthStrategy` interface:

```typescript
import { AuthStrategy } from './AuthStrategy';

export class MyCustomAuth implements AuthStrategy {
    async applyAuth(headers: Record<string, string>): Promise<void> {
        headers['X-My-Token'] = process.env.MY_TOKEN!;
    }
}
```

2. Register it in `src/auth/AuthStrategyResolver.ts`:

```typescript
case 'mycustom':
    return new MyCustomAuth();
```

3. Use `authType = mycustom` in your Excel row.

---

## Template Variables

Template variables are resolved automatically in the `endpoint` and `headers` Excel columns, and in the contents of the JSON file referenced by `requestBodyFile`, at test runtime.

### Supported tokens

| Token | Resolves to | Example value |
|---|---|---|
| `{{uuid}}` | A random UUID | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| `{{timestamp}}` | Current Unix timestamp (ms) | `1720000000000` |
| `{{isoDate}}` | Current ISO 8601 datetime | `2026-07-04T13:00:00.000Z` |
| `{{date}}` | Current date (YYYY-MM-DD) | `2026-07-04` |
| `{{env:VAR_NAME}}` | Value of an environment variable | *(value of `process.env.VAR_NAME`)* |
| `{{ctx:key}}` | Value stored by a previous test via `injectAs` | *(extracted from prior response)* |

### Example usage in Excel

**JSON file referenced by `requestBodyFile`:**
```json
{"name": "User_{{uuid}}", "createdAt": "{{isoDate}}", "tenantId": "{{env:TENANT_ID}}"}
```

**`endpoint` column:**
```
/api/orders/{{ctx:orderId}}
```

**`headers` column:**
```json
{"X-Correlation-Id": "{{uuid}}", "X-Date": "{{date}}"}
```

---

## Test Chaining — Pass Values Between Tests

Use `extractField` and `injectAs` columns to pass a value extracted from one test's response into the next test's request.

### How it works

1. Test row A has `extractField = data.id` and `injectAs = orderId`
2. After row A's response, the value at `body.data.id` is stored as `ctx:orderId`
3. Test row B uses `{{ctx:orderId}}` in its endpoint or body
4. The template engine resolves it automatically at request build time

### Excel example — CRUD chain

| name | endpoint | method | expectedStatus | extractField | injectAs | cleanupEndpoint |
|---|---|---|---|---|---|---|
| Create Order | `/api/orders` | POST | 201 | `data.id` | `orderId` | |
| Get Order | `/api/orders/{{ctx:orderId}}` | GET | 200 | | | |
| Update Order | `/api/orders/{{ctx:orderId}}` | PUT | 200 | | | |
| Delete Order | `/api/orders/{{ctx:orderId}}` | DELETE | 204 | | | |

> **Important:** Tests must run in serial order for chaining to work. The spec file generated by `npm run new-api` already includes `test.describe.configure({ mode: 'serial' })`.

### ContextStore API (advanced use in spec files)

```typescript
import { ContextStore } from '../../src/utils/contextStore';

// Store a value
ContextStore.set('orderId', body.data.id);

// Read a value
const id = ContextStore.get('orderId');

// Extract a dotted path from a response body
const token = ContextStore.extract(body, 'auth.token');

// Clear all stored values (use in test.afterAll if needed)
ContextStore.clear();
```

---

## Response Time Assertions

Add `maxResponseMs` to any Excel row to assert the API responds within a time threshold.

| Column | Value |
|---|---|
| `maxResponseMs` | `2000` |

If the response takes longer than 2000 ms, the test fails with:
```
Response time 3145ms exceeded limit of 2000ms
```

This uses `response.elapsedMs` which is measured from the moment the request is sent to when the response body is received. Retry delays are included in the total if retries occur.

---

## Auto-Cleanup After POST

Use `cleanupEndpoint` and `cleanupMethod` to automatically delete data created during a test.

| Column | Value |
|---|---|
| `cleanupEndpoint` | `/api/orders/{{ctx:orderId}}` |
| `cleanupMethod` | `DELETE` |

The cleanup step runs at the end of the test, regardless of pass or fail. `cleanupMethod` defaults to `DELETE` if left blank.

**Typical pattern — create then clean up:**

| name | endpoint | method | extractField | injectAs | cleanupEndpoint | cleanupMethod |
|---|---|---|---|---|---|---|
| Create Order | `/api/orders` | POST | `data.id` | `orderId` | `/api/orders/{{ctx:orderId}}` | DELETE |

---

## Response Validation

### SmartComparator

Validates response bodies against a JSON file using special operator strings. Extra fields in the actual response are ignored — only keys present in the expected file are validated.

**Usage:**

Create a JSON file at the path set in the `expectedFile` column:

```json
{
    "data": {
        "id":         "__GT__:0",
        "email":      "__REGEX__:.*@example.com",
        "first_name": "__NOT_NULL__",
        "status":     "__ONE_OF__:active,inactive,pending",
        "avatar":     "__STARTS_WITH__:https",
        "score":      "__BETWEEN__:0,100",
        "roles":      "__ARRAY_CONTAINS__:user",
        "token":      "__LENGTH__:32"
    }
}
```

**All supported operators:**

| Operator | Example | What it checks |
|---|---|---|
| `__IGNORE__` | `"field": "__IGNORE__"` | Skip this field entirely |
| `__NOT_NULL__` | `"field": "__NOT_NULL__"` | Not null and not undefined |
| `__DEFINED__` | `"field": "__DEFINED__"` | Exists, not null, not undefined |
| `__NOT_EMPTY__` | `"field": "__NOT_EMPTY__"` | Non-empty string / array / object |
| `__REGEX__:pattern` | `"email": "__REGEX__:.*@test.com"` | Matches regex pattern |
| `__GT__:n` | `"age": "__GT__:18"` | Greater than n |
| `__GTE__:n` | `"count": "__GTE__:1"` | Greater than or equal to n |
| `__LT__:n` | `"price": "__LT__:100"` | Less than n |
| `__LTE__:n` | `"score": "__LTE__:10"` | Less than or equal to n |
| `__BETWEEN__:min,max` | `"id": "__BETWEEN__:1,1000"` | Inclusive numeric range |
| `__CONTAINS__:val` | `"msg": "__CONTAINS__:success"` | String or array contains value |
| `__STARTS_WITH__:val` | `"url": "__STARTS_WITH__:https"` | String starts with prefix |
| `__ENDS_WITH__:val` | `"file": "__ENDS_WITH__:.jpg"` | String ends with suffix |
| `__ONE_OF__:a,b,c` | `"status": "__ONE_OF__:active,inactive"` | Value is one of the listed options |
| `__LENGTH__:n` | `"token": "__LENGTH__:32"` | Exact string or array length |
| `__ARRAY_CONTAINS__:val` | `"roles": "__ARRAY_CONTAINS__:admin"` | Array includes the given item |
| `__TYPE__:type` | `"id": "__TYPE__:number"` | JavaScript `typeof` check |

---

## OpenAPI Contract Validation

Validates the response structure against an OpenAPI 3.0 specification.

### Per-API spec (recommended)

Add the `contractFile` column to your Excel row:

| Column | Value |
|---|---|
| `contractFile` | `contracts/openapi/orders.yaml` |

### Spec file structure

```yaml
openapi: "3.0.0"
info:
  title: Orders API
  version: "1.0.0"
paths:
  /api/orders/{id}:
    get:
      summary: Get order by ID
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
                required: [id, status, total]
                properties:
                  id:
                    type: integer
                  status:
                    type: string
                    enum: [pending, shipped, delivered]
                  total:
                    type: number
```

### In a spec file (direct usage)

```typescript
import { ContractValidator } from '../../src/validators/contractValidator';

await ContractValidator.validate(
    'contracts/openapi/orders.yaml',
    '/api/orders/123',
    'GET',
    200,
    responseBody
);
```

If no schema is defined for an endpoint, the validation step is skipped with an annotation rather than failing the test.

---

## Mock Server

The in-process mock server starts and stops within a test suite — no external process needed.

### Static responses

```typescript
import { MockServer } from '../../mocks/mock-server';

const mock = new MockServer(4010);

test.beforeAll(async () => {
    mock
        .addRoute('GET', '/api/orders/1', {
            status: 200,
            body:   { id: 1, status: 'shipped' },
            headers: { 'X-Request-Id': 'abc-123' },
            delayMs: 100
        })
        .addRoute('POST', '/api/orders', {
            status: 201,
            body: { id: 999, status: 'pending' }
        });

    await mock.start();
});

test.afterAll(async () => await mock.stop());
```

### Stateful / flaky responses

```typescript
// Returns 503 on the first call, 200 on subsequent calls
mock.addRoute('GET', '/api/flaky', (callCount) =>
    callCount === 1
        ? { status: 503, body: { error: 'Unavailable' } }
        : { status: 200, body: { result: 'recovered' } }
);

// Assert the server was called a specific number of times
expect(mock.callCount('GET', '/api/flaky')).toBe(2);
```

### Excel-driven mock tests

Add rows to `test-data/excel/mock-tests.xlsx` (sheet: `MockTests`):

| Column | Description |
|---|---|
| `mockStatus` | HTTP status the mock returns |
| `mockBody` | JSON string — mock response body |
| `mockHeaders` | JSON string — mock response headers |
| `mockDelayMs` | Simulated response delay (ms) |
| `flakyCallsToFail` | How many initial calls return 503 before success |
| `expectedCallCount` | Assert total number of times the mock was hit |
| `expectedMinDurationMs` | Assert minimum response time |

---

## Reporting

Each test run generates a timestamped Ortoni HTML report:

```
reports/
└── ortoni-report-dev/
    └── 2026-07-04_13-00-00/
        └── index.html
```

The report shows:
- Named **steps** (Build Request, Send Request, Validate Status, etc.)
- Full **request** (URL, method, headers, body)
- Full **response** (status, body)
- Pass/fail **per suite** with durations
- A sticky **summary banner** (total, passed, failed, pass rate)

### Attach request/response in any spec

```typescript
import { ReportHelper } from '../../src/utils/reportHelper';

ReportHelper.attachRequest(testInfo, request);
ReportHelper.attachResponse(testInfo, status, body);
```

---

## Running Tests

### All tests

```bash
npm run test:dev     # dev environment
npm run test:qa      # QA environment
npm run test:sit     # SIT environment
```

### One spec file

```bash
npx cross-env ENV=dev npx playwright test tests/api/crudExcel.spec.ts
```

### Filter by test name

```bash
npx cross-env ENV=dev npx playwright test --grep "Get Order"
```

### Filter by spec and name

```bash
npx cross-env ENV=dev npx playwright test tests/api/orders.spec.ts --grep "Create"
```

---

## CI/CD

GitHub Actions runs tests against `dev` and `qa` in parallel on every push to `main`.

### Required GitHub Secrets

| Secret | Used for |
|---|---|
| `BASE_URL_dev` | Default base URL for dev |
| `BASE_URL_qa` | Default base URL for QA |
| `API_KEY` | API key auth |
| `CLIENT_ID` | OAuth2 / standard client ID |
| `CLIENT_SECRET` | OAuth2 / standard client secret |
| `OAUTH2_TOKEN_URL` | OAuth2 token endpoint |
| `MULESOFT_CLIENT_ID` | MuleSoft client ID |
| `MULESOFT_CLIENT_SECRET` | MuleSoft client secret |
| `MULESOFT_TOKEN_URL` | MuleSoft token endpoint |
| `SF_CLIENT_ID` | Salesforce Connected App consumer key |
| `SF_CLIENT_SECRET` | Salesforce Connected App consumer secret |
| `SF_TOKEN_URL` | Salesforce token endpoint |

### Per-service URL override in CI

For each named service, set `SERVICE_URL_<NAME>` in GitHub Secrets:

```
SERVICE_URL_MULESOFT=https://mulesoft-prod.yourcompany.com
SERVICE_URL_SALESFORCE=https://your-instance.salesforce.com
```

This takes precedence over `env.yaml` without any code changes.

---

## Framework Architecture

### How a test runs end-to-end

```
Excel row
  │
  ▼
DataLoader.loadExcel()         ← parses columns into typed objects
  │
  ▼
Config.getServiceUrl(service)  ← resolves base URL from env.yaml or CI env var
  │
  ▼
AuthStrategyResolver.resolve() ← picks auth strategy from authType column
  │
  ▼
RequestBuilder.build()         ← applies auth + resolves {{template}} variables
  │
  ▼
APIClient.send()               ← sends HTTP request, retries on 429/502/503/504
  │                               measures elapsedMs
  ▼
Validate Status                ← expect(status).toBe(expectedStatus)
  │
  ▼
Validate Response Time         ← if maxResponseMs set: expect(elapsedMs).toBeLessThanOrEqual(...)
  │
  ▼
SmartComparator.compare()      ← if expectedFile set: compare body against JSON operators
  │
  ▼
ContractValidator.validate()   ← if contractFile set: validate against OpenAPI spec
  │
  ▼
ContextStore.set()             ← if extractField + injectAs set: store value for next test
  │
  ▼
Cleanup request                ← if cleanupEndpoint set: send DELETE (or cleanupMethod)
```

### Key design principles

- **Credentials never in Excel** — only the `authType` string. All secrets stay in `.env` or CI secrets.
- **Retry built-in** — automatic exponential backoff on `429`, `502`, `503`, `504`. Up to 3 attempts.
- **Token caching** — OAuth2 tokens cached in memory for the run duration; refreshed 30s before expiry.
- **Template resolution** — `{{uuid}}`, `{{ctx:key}}` resolved at request build time, not at load time.
- **Serial execution** — spec files generated by `npm run new-api` use `mode: 'serial'` so chaining works.
- **Isolated reports** — each run writes to a timestamped folder; history is never overwritten.

---

## What a Tester Needs to Do — by Scenario

Use this as a quick reference whenever a new endpoint is handed to you.

---

### Scenario 1: New endpoint on an existing API

> The base URL and auth type are already configured (e.g., another endpoint on the same MuleSoft service or reqres.in).

You need **only two things**:

| Step | What to do | File |
|---|---|---|
| 1 | Add a row for the new endpoint | Existing Excel file e.g. `test-data/excel/crud-tests.xlsx` |
| 2 | Add expected JSON file *(optional — only if validating response body)* | `test-data/json/<filename>.json` |

No spec.ts changes needed. The existing spec loops over every Excel row automatically — your new row becomes a new test immediately.

---

### Scenario 2: Brand new API domain (different base URL or new service)

> The API lives on a different server, or uses an auth type not yet configured.

Follow these steps **in order**:

| Step | What to do | File to touch | Required? |
|---|---|---|---|
| 1 | Run `npm run new-api <name>` | Auto-generates spec, Excel, JSON folder, OpenAPI stub | Yes |
| 2 | Add the service base URL under `services:` for each environment | `config/env.yaml` | Only if the base URL is different from `baseUrl` |
| 3 | Add credentials for the new auth type | `.env` (local) + GitHub Secrets (CI) | Only if using an auth type not configured before |
| 4 | Fill in Excel rows — one row per test case | `test-data/excel/<name>-tests.xlsx` | Yes |
| 5 | Add expected response JSON files | `test-data/json/<name>/` | Only if using SmartComparator (`expectedFile` column) |
| 6 | Fill in the OpenAPI spec | `contracts/openapi/<name>.yaml` | Only if using contract validation (`contractFile` column) |

Steps 2 and 3 are **one-time per service** — once done, every future tester adding endpoints to that API only needs Step 4.

---

### What a tester never needs to touch

| File / Folder | Reason |
|---|---|
| `src/` | No source code changes needed to add tests |
| `playwright.config.ts` | No runner config changes needed |
| `src/auth/AuthStrategyResolver.ts` | All auth types already registered: `apikey`, `basic`, `oauth2`, `mulesoft`, `salesforce`, `none` |
| `src/utils/dataLoader.ts` | All Excel columns already supported |

The `service` and `authType` columns in Excel drive both `Config.getServiceUrl()` and `AuthStrategyResolver.resolve()` — the tester controls both through the spreadsheet, not through code.
