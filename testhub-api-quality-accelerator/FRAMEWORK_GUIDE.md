# API Test Framework — Human Guide

## What Is This?

This is a reusable framework for testing REST APIs automatically. Instead of writing the same boilerplate code over and over for every test, you describe your test cases in an Excel spreadsheet, and the framework handles sending the requests, checking the responses, and producing a report.

It is built on Playwright (a popular test runner) and Axios (an HTTP client), written in TypeScript, and produces HTML reports using Ortoni Report.

---

## What Problems Does It Solve?

| Problem | How This Framework Solves It |
|---|---|
| Writing repetitive HTTP test code | Tests are driven by Excel — no code changes needed for new cases |
| Managing tokens and credentials | Auth strategies are centralised and picked automatically |
| Running tests against different environments | One YAML config file, one command-line flag |
| Getting useful failure messages | SmartComparator tells you exactly which field failed and why |
| Testing without a real server | Built-in mock server simulates any API response |
| Keeping logs and reports | Every request/response is logged to file and attached to the HTML report |

---

## Folder Structure

```
api-test-framework/
│
├── config/
│   ├── config.ts          # Reads the environment config (baseUrl etc.)
│   └── env.yaml           # Defines base URLs per environment (dev, qa, sit)
│
├── src/
│   ├── client/
│   │   └── apiClient.ts   # Sends HTTP requests using Axios; handles retries
│   │
│   ├── auth/
│   │   ├── AuthStrategy.ts            # Interface that all auth strategies implement
│   │   ├── AuthStrategyResolver.ts    # Picks the right auth strategy from a string
│   │   ├── ApiKeyAuth.ts              # Adds an x-api-key header
│   │   ├── BasicAuth.ts               # Adds a Basic Authorization header
│   │   └── OAuth2ClientCredentials.ts # Fetches and caches a Bearer token
│   │
│   └── utils/
│       ├── requestBuilder.ts    # Assembles the final HTTP request (URL, headers, body)
│       ├── dataLoader.ts        # Reads test data from Excel or YAML files
│       ├── responseValidator.ts # Simple status + field checks
│       ├── smartComparator.ts   # Deep comparison with special operators (see below)
│       ├── schemaValidator.ts   # JSON schema validation using AJV
│       ├── tokenManager.ts      # Stores a Bearer token across tests (with file cache)
│       ├── logger.ts            # Writes request/response info to console and log file
│       └── reportHelper.ts      # Attaches request/response data to Ortoni report
│
├── mocks/
│   └── mock-server.ts     # A lightweight HTTP server for offline testing
│
├── tests/
│   └── api/
│       ├── crudExcel.spec.ts            # CRUD tests driven by an Excel file
│       ├── responsevalidateExcel.spec.ts # Response validation tests from Excel
│       └── mockServer.spec.ts           # Tests that run against the mock server
│
├── test-data/
│   ├── excel/
│   │   ├── crud-tests.xlsx    # Test cases for CRUD tests
│   │   ├── user.xlsx          # Test cases for response validation tests
│   │   └── mock-tests.xlsx    # Test cases and mock behaviour for mock server tests
│   ├── json/                  # Expected response bodies for SmartComparator
│   └── yaml/                  # Alternative test data format
│
├── contracts/
│   └── openapi/
│       └── user.yaml          # OpenAPI spec for contract/schema validation
│
├── logs/
│   └── api-test.log           # All request and response output written here
│
├── reports/                   # Generated HTML reports appear here
├── .env                       # Secrets (API keys, credentials) — never commit this
├── playwright.config.ts       # Playwright settings (reporter, testDir, baseURL)
└── tsconfig.json
```

---

## How to Set Up

### 1. Install dependencies

```bash
npm install
```

### 2. Configure your environment

Edit `config/env.yaml` to set the base URL for each environment:

```yaml
dev:
  baseUrl: https://your-api-dev.example.com

qa:
  baseUrl: https://your-api-qa.example.com
```

### 3. Set up credentials

Create or edit `.env` in the project root. This file is never committed to source control.

```env
# API Key auth
API_KEY=your-api-key-here

# Basic auth
BASIC_USERNAME=myuser
BASIC_PASSWORD=mypassword

# OAuth2 client credentials
OAUTH2_TOKEN_URL=https://auth.example.com/oauth/token
CLIENT_ID=my-client-id
CLIENT_SECRET=my-client-secret
OAUTH2_SCOPE=read:users

# Optional: override the base URL entirely
# BASE_URL=https://custom-override.example.com
```

---

## How to Run Tests

```bash
# Run against the dev environment
npm run test:dev

# Run against the QA environment
npm run test:qa
```

Reports are saved automatically to `reports/ortoni-report-<env>/<timestamp>/index.html`. Open that file in a browser to see results.

---

## How to Write Tests (Excel-Driven)

Most tests do not require any TypeScript code. You define everything in an Excel spreadsheet.

### CRUD Tests (`test-data/excel/crud-tests.xlsx`, sheet: `CRUD`)

Each row is one test case. The columns are:

| Column | What to put | Example |
|---|---|---|
| `name` | A human-readable name for the test | Get single user |
| `endpoint` | The API path (appended to the base URL) | /api/users/2 |
| `method` | HTTP verb | GET, POST, PUT, DELETE |
| `expectedStatus` | The HTTP status code you expect back | 200 |
| `requestBodyFile` | Path to a JSON file holding the request payload (optional) | test-data/request/json/create-user.json |
| `expectedFile` | Path to a JSON file to compare the response against (optional) | test-data/json/get-user.json |
| `authType` | Which authentication to use (optional — see below) | apikey |
| `headers` | Extra request headers as a JSON string (optional) | `{"Accept":"application/json"}` |

### Response Validation Tests (`test-data/excel/user.xlsx`, sheet: `Sheet1`)

Same columns as above. For each test, if a JSON file exists at `test-data/json/<test-name>.json`, the response body is also compared against it using SmartComparator.

---

## Authentication — How It Works

You choose the auth method per test row using the `authType` column. Leave it blank to use the defaults from `.env`.

| `authType` value | What happens |
|---|---|
| `apikey` | Reads `API_KEY` from `.env`, adds it as `x-api-key` header |
| `basic` | Reads `BASIC_USERNAME` + `BASIC_PASSWORD`, adds a `Basic` Authorization header |
| `oauth2` | Reads `CLIENT_ID`, `CLIENT_SECRET`, `OAUTH2_TOKEN_URL` from `.env`, fetches a Bearer token, caches it so it is only fetched once, and adds it as `Authorization: Bearer ...` |
| `none` | No auth headers added at all |
| *(blank)* | Uses whatever is in `.env` — API key and/or Bearer token from TokenManager |

The OAuth2 token is automatically refreshed 30 seconds before it expires so you never get mid-run failures because a token expired.

---

## Smart Response Comparison

When you point a test at an expected JSON file, the framework uses `SmartComparator` to compare the actual response against it. This is more powerful than a simple equality check — you can use special marker values in your expected file to express flexible assertions.

| Marker | Meaning | Example |
|---|---|---|
| `"__IGNORE__"` | Skip this field entirely — don't check it | `"id": "__IGNORE__"` |
| `"__NOT_NULL__"` | Field must exist and not be null | `"token": "__NOT_NULL__"` |
| `"__DEFINED__"` | Field must be present and non-null | `"email": "__DEFINED__"` |
| `"__NOT_EMPTY__"` | String, array, or object must not be empty | `"items": "__NOT_EMPTY__"` |
| `"__TYPE__:string"` | Check that the field is a specific type | `"age": "__TYPE__:number"` |
| `"__REGEX__:^[A-Z]"` | Value must match the regular expression | `"code": "__REGEX__:^[A-Z]{3}"` |
| `"__GT__:0"` | Value must be greater than a number | `"count": "__GT__:0"` |
| `"__GTE__:18"` | Greater than or equal | `"age": "__GTE__:18"` |
| `"__LT__:100"` | Less than | `"score": "__LT__:100"` |
| `"__LTE__:100"` | Less than or equal | `"score": "__LTE__:100"` |
| `"__BETWEEN__:1,100"` | Value must fall within an inclusive range | `"rating": "__BETWEEN__:1,5"` |
| `"__CONTAINS__:hello"` | String or array must contain this value | `"message": "__CONTAINS__:success"` |
| `"__STARTS_WITH__:usr_"` | String must start with this prefix | `"id": "__STARTS_WITH__:usr_"` |
| `"__ENDS_WITH__:.com"` | String must end with this suffix | `"email": "__ENDS_WITH__:.com"` |
| `"__ONE_OF__:active,inactive"` | Value must be one of a comma-separated list | `"status": "__ONE_OF__:active,inactive"` |
| `"__LENGTH__:10"` | String or array must have exactly this length | `"pin": "__LENGTH__:4"` |
| `"__ARRAY_CONTAINS__:admin"` | Array must contain this specific item | `"roles": "__ARRAY_CONTAINS__:admin"` |

Any field that has a plain value (a string, number, boolean) is compared for exact equality. Extra fields in the actual response that are not in your expected file are allowed and silently ignored.

**Example expected JSON file:**

```json
{
  "id": "__IGNORE__",
  "name": "Alice",
  "email": "__ENDS_WITH__:.com",
  "age": "__BETWEEN__:18,99",
  "status": "__ONE_OF__:active,inactive",
  "token": "__NOT_NULL__"
}
```

---

## Mock Server

The mock server lets you run tests entirely offline — no real API needed. It is a lightweight HTTP server that starts up before your tests, responds to registered routes, and shuts down after.

You define the mock behaviour in `test-data/excel/mock-tests.xlsx` (sheet: `MockTests`). Extra columns beyond the standard ones:

| Column | What it does |
|---|---|
| `mockStatus` | The HTTP status the mock returns |
| `mockBody` | The JSON body the mock returns (as a string) |
| `mockHeaders` | Extra response headers to return (JSON string) |
| `mockDelayMs` | Adds an artificial delay in milliseconds (useful for timeout testing) |
| `flakyCallsToFail` | Returns 503 for the first N calls, then responds normally (simulates flaky services) |
| `expectedCallCount` | Asserts how many times the mock endpoint was actually called |
| `expectedMinDurationMs` | Asserts the response took at least this many milliseconds |

This is particularly useful for:
- Testing retry logic (use `flakyCallsToFail`)
- Testing timeout handling (use `mockDelayMs`)
- Testing without network access (fully offline)
- Simulating error scenarios (set `mockStatus` to 500, 503, etc.)

---

## Retry Logic

The API client automatically retries failed requests for transient errors. It retries up to 3 times when it receives:

- `429` Too Many Requests
- `502` Bad Gateway
- `503` Service Unavailable
- `504` Gateway Timeout

Each retry waits longer than the previous one (1 second, then 2 seconds, then 3 seconds). This is built in — you do not need to configure anything.

---

## Logging

Every HTTP request and response is written to two places simultaneously:

1. **Console** — visible while tests are running
2. **`logs/api-test.log`** — a persistent file you can inspect after the run

Log format:
```
[2026-06-07T10:23:45.123Z] [REQUEST] GET https://reqres.in/api/users/2
[2026-06-07T10:23:45.456Z] [RESPONSE] 200 https://reqres.in/api/users/2
[2026-06-07T10:23:45.457Z] [RESPONSE] Body: {"data":{"id":2,"email":"janet.weir@reqres.in",...}}
```

---

## Reports

After each test run, an HTML report is created at:

```
reports/ortoni-report-<env>/<timestamp>/index.html
```

Each test entry in the report shows:
- Pass / Fail status
- Each named step (Build Request, Send Request, Validate Status, Validate Response Body)
- The full request that was sent (method, URL, headers, body)
- The full response that came back (status code, body)

---

## Adding a New Test

1. Open the relevant Excel file (e.g., `test-data/excel/crud-tests.xlsx`)
2. Add a new row with the endpoint, method, expected status, and any optional fields
3. If you want body validation, create a JSON file in `test-data/json/` and reference its path in the `expectedFile` column
4. Run `npm run test:dev` — your new test appears automatically

No TypeScript changes required.

---

## Environment Variables Reference

| Variable | Used for | Where set |
|---|---|---|
| `ENV` | Selects the config block in `env.yaml` | Command line or CI |
| `BASE_URL` | Overrides the YAML config entirely | `.env` or CI |
| `API_KEY` | API Key auth header value | `.env` |
| `API_KEY_HEADER` | Header name for API key (default: `x-api-key`) | `.env` |
| `API_KEY_QUERY` | Appends API key as a URL query param | `.env` |
| `BASIC_USERNAME` | Username for Basic Auth | `.env` |
| `BASIC_PASSWORD` | Password for Basic Auth | `.env` |
| `OAUTH2_TOKEN_URL` | Token endpoint for OAuth2 | `.env` |
| `CLIENT_ID` | Client ID for OAuth2 | `.env` |
| `CLIENT_SECRET` | Client Secret for OAuth2 | `.env` |
| `OAUTH2_SCOPE` | Optional scope for OAuth2 token request | `.env` |
| `AUTH_TOKEN` | Value for a custom auth header | `.env` |
| `AUTH_HEADER_NAME` | Name of the custom auth header (e.g., `X-Auth-Token`) | `.env` |

---

## Technology Stack

| Tool | Version | Why |
|---|---|---|
| TypeScript | 6.x | Type safety, better editor support |
| Playwright | 1.59+ | Test runner, parallel execution, rich reporting |
| Axios | 1.17+ | HTTP client with interceptors and full response access |
| Ortoni Report | 4.x | HTML test reports |
| AJV | 8.x | JSON schema validation |
| xlsx | 0.18.x | Reading Excel test data files |
| js-yaml | 4.x | Reading YAML config and test data files |
| dotenv | 17.x | Loading `.env` credentials |
