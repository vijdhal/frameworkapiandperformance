# k6 Performance Framework

A reusable, Excel-driven load-testing framework for REST APIs, built on [k6](https://k6.io).
Every endpoint lives in its own self-contained folder under `tests/<name>/` — nothing is
shared between endpoints except the reusable `src/` modules (client, auth, request
builder, scenario runner). Adding or changing one endpoint never touches another's files.

Reference implementation: `tests/createuser/` (reqres.in's `POST /api/users`).

---

## Tech Stack

| Layer | Tool | Role |
|---|---|---|
| Load engine | [k6](https://k6.io) (Goja JS runtime) | Executes the actual test — VUs, iterations, checks, thresholds |
| Language | Plain JavaScript (ES modules) | k6's runtime doesn't support arbitrary npm/ESM bundling, so no framework/transpiler is used |
| Test authoring | Excel (`.xlsx`) via [SheetJS `xlsx`](https://www.npmjs.com/package/xlsx) | Human-editable source of truth for requests **and** performance params; compiled to JSON because Goja can't parse `.xlsx` directly |
| Config | JSON (`config/environments.json`) + `.env` | Environment base URLs, secrets exported to the shell |
| Env loading | [`dotenv`](https://www.npmjs.com/package/dotenv) | Local `.env` reference (k6 doesn't auto-load it — export the values into your shell) |
| Reporting | [`k6-reporter`](https://github.com/benc-uk/k6-reporter) + k6's `textSummary` | Self-contained HTML report per run, written to `reports/` |
| Scaffolding | Node.js scripts (`scripts/*.mjs`) | One-shot generator for a new endpoint's folder + npm scripts |
| Package manager | npm | Installs `dotenv`, `xlsx`, `html-reporter` (dev tooling only — never imported by k6 itself) |

k6 itself is a **standalone Go binary**, not an npm package — it's installed separately
from Node.

---

## Prerequisites

- [Node.js](https://nodejs.org/) 18+ (used for `npm install` and the scaffolding/compile
  scripts — never for running the tests themselves)
- [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) — the actual test runner

## Installation

```bash
# 1. Clone the repo
git clone <repo-url>
cd k6-performance-framework

# 2. Install Node dependencies (dotenv, xlsx, html-reporter)
npm install

# 3. Install k6 (one-time, machine-wide — not an npm package)
#    Windows (winget):
winget install k6 --source winget
#    Windows (Chocolatey):
choco install k6
#    macOS:
brew install k6
#    Linux / other options: https://grafana.com/docs/k6/latest/set-up/install-k6/

# 4. Verify both are on PATH
node -v
k6 version
```

### Configure environments

Base URLs per environment live in `config/environments.json`:

```json
{
  "dev": { "baseUrl": "https://your-api-dev.example.com" },
  "qa":  { "baseUrl": "https://your-api-qa.example.com" },
  "sit": { "baseUrl": "https://your-api-sit.example.com" }
}
```

Select one with `-e ENV=qa`, or bypass the file entirely with `-e BASE_URL=https://...`.

### Configure secrets (auth)

Secrets are never committed — `.env` is git-ignored. Create it locally and export the
values your endpoints need before running k6 (k6 does not auto-load `.env` files):

```bash
# .env (local only)
API_KEY=xxxxx
API_KEY_HEADER=x-api-key        # optional, defaults to x-api-key
OAUTH2_TOKEN_URL=https://...
CLIENT_ID=xxxxx
CLIENT_SECRET=xxxxx
OAUTH2_SCOPE=xxxxx              # optional
```

Then pass what a given run needs on the command line, e.g. `k6 run -e API_KEY=xxxxx ...`,
or export them into your shell first.

## Running the example endpoint

```bash
npm run createuser:smoke     # 1 VU / 1 iteration sanity check
npm run createuser:load      # VUs/duration from the "createuser-load" profile row
```

Each of these regenerates the compiled JSON from the workbook, then runs k6. Open the
generated report in `reports/<reportName>.html` afterwards.

### Command reference

| Command | What it does |
|---|---|
| `npm install` | Installs Node dev tooling (`xlsx`, `dotenv`, `html-reporter`) |
| `npm run new-endpoint -- <name> [--method GET] [--path /api/<name>] [--auth none]` | Scaffolds a brand-new endpoint folder (see below) |
| `npm run <name>:gen` | Compiles `tests/<name>/<name>.xlsx` → `<name>-scenario.json` + `profiles.json` |
| `npm run <name>:smoke` | Regenerates JSON, then `k6 run` the smoke test (1 VU / 1 iteration) |
| `npm run <name>:load` | Regenerates JSON, then `k6 run` the load test (perf params from the `<name>-load` profile row) |
| `node scripts/excel-to-scenario.mjs --file tests/<name>/<name>.xlsx --out-dir tests/<name>` | Manual compile step, if you don't want to go through `npm run <name>:gen` |
| `k6 run -e ENV=qa tests/<name>/<name>-load-test.js` | Run directly against a specific environment |
| `k6 run -e USERS=20 -e DURATION=1m tests/<name>/<name>-load-test.js` | Override VUs/duration at the command line (constant-VU profiles only — ignored if the profile uses `stages` or an arrival-rate executor) |

---

## Project Structure

```
k6-performance-framework/
├── config/
│   ├── environments.json      # baseUrl per environment
│   ├── config.js               # resolves baseUrl for the current -e ENV
│   ├── environment.js           # ENV export (BASE_URL, USERS, DURATION)
│   └── thresholds.js            # default pass/fail thresholds, merged under Excel's
├── scripts/
│   ├── new-endpoint.mjs        # scaffolds a whole tests/<name>/ folder in one shot
│   └── excel-to-scenario.mjs   # compiles <name>.xlsx -> <name>-scenario.json + profiles.json
├── src/
│   ├── clients/apiClient.js            # thin wrapper over k6/http
│   ├── auth/                           # AuthStrategy, AuthStrategyResolver, ApiKeyAuth, OAuth2ClientCredentials
│   ├── services/                       # ApiService (generic) + example domain services
│   └── utils/
│       ├── requestBuilder.js           # scenario row -> {method,url,payload,headers,expect}
│       ├── scenarioRunner.js           # build -> send -> validate -> chain context between rows
│       ├── responseValidator.js        # status / latency / body-field checks
│       ├── dataLoader.js               # loadScenario() — reads <name>-scenario.json
│       ├── optionsLoader.js            # loadOptions()/loadRunParams() — reads profiles.json
│       ├── authSetup.js                # resolveAuthContext() — fetches OAuth2 token once in setup()
│       ├── logger.js                   # console request/response logging
│       └── htmlReport.js               # handleSummary() -> reports/<reportName>.html
└── tests/
    └── <name>/                         # one self-contained folder per endpoint — see below
```

---

## Adding a New Endpoint — Full Worked Example

**The quick answer first, since it trips people up:** you only ever hand-edit two kinds
of files — the `.xlsx` workbook and the `*-requestpayload.json` body. `*-scenario.json`
and `profiles.json` are **not saved by Excel** — they only get rewritten when you run
the compile command, `npm run <name>:gen` (which `:smoke` and `:load` also run for you
automatically, first, every time). Saving the `.xlsx` file alone does nothing until
that command runs.

Below is the whole thing end-to-end for a brand-new endpoint, with every command and
every value spelled out. The example: **"Add a performance test for `POST /api/orders`,
expecting `201`, response under 2s, load = 20 VUs for 1 minute."**

### Step 1 — Scaffold the folder

Run this once, from the repo root:

```bash
npm run new-endpoint -- orders --method POST --path /api/orders
```

You'll see console output like:

```
✔ payload           -> tests/orders/orders-requestpayload.json
✔ workbook          -> tests/orders/orders.xlsx (sheets: orders, profiles)
  ✔ orders -> tests/orders/orders-scenario.json (1 row)
  ✔ profiles -> tests/orders/profiles.json (2 profiles)
✔ test file         -> tests/orders/orders-smoke-test.js
✔ test file         -> tests/orders/orders-load-test.js
✔ npm scripts       -> orders:gen, orders:smoke, orders:load
```

That created every file below and added `orders:gen` / `orders:smoke` / `orders:load`
to `package.json`. Nothing else needs creating by hand.

```
tests/orders/
  orders.xlsx                  # <- you fill this in next (Step 2)
  orders-requestpayload.json   # <- you fill this in next (Step 3)
  orders-scenario.json         # placeholder — Step 4 rewrites this from the xlsx
  profiles.json                 # placeholder — Step 4 rewrites this from the xlsx
  orders-smoke-test.js         # done — no edits needed
  orders-load-test.js          # done — no edits needed
```

### Step 2 — Add your test data: open `tests/orders/orders.xlsx`

**Sheet `orders`** already has one placeholder row. Replace its values with the real
request:

| name | endpoint | method | authType | payloadFile | expectedStatus | maxResponseMs | extractField | injectAs | weight |
|---|---|---|---|---|---|---|---|---|---|
| Create Order | `/api/orders` | POST | none | `orders-requestpayload.json` | 201 | 2000 | id | orderId | 1 |

(Leave `headers`/`payload` blank — the body comes from `payloadFile` instead. Add more
rows below this one if the load test should exercise more than one call per iteration —
e.g. a GET to read the order back — and give each a `weight`.)

**Sheet `profiles`** already has an `orders-smoke` and an `orders-load` row. Set the
real numbers on each:

| profile | vus | duration | iterations | p95_ms | errorRate | env | pick | reportName |
|---|---|---|---|---|---|---|---|---|
| orders-smoke | 1 | | 1 | 2000 | 0.01 | dev | sequential | orders-smoke-test-report |
| orders-load | 20 | 1m | | 1000 | 0.01 | dev | weighted | orders-load-test-report |

Save the file (keep it as `.xlsx`).

### Step 3 — Add the request body: `tests/orders/orders-requestpayload.json`

Open this file (plain JSON, not Excel) and replace the placeholder with the real body:

```json
{
  "customerId": 123,
  "item": "Widget",
  "quantity": 2
}
```

Save it.

### Step 4 — Compile: turn the Excel + payload into the JSON k6 actually reads

This is the command that answers "will `profiles.json`/`orders-scenario.json` update
automatically?" — **only when you run this:**

```bash
npm run orders:gen
```

Console output:

```
  ✔ orders -> tests/orders/orders-scenario.json (1 row)
  ✔ profiles -> tests/orders/profiles.json (2 profiles)

2 files generated from tests/orders/orders.xlsx
```

`orders-scenario.json` now contains your real request (with the payload inlined from
`orders-requestpayload.json`), and `profiles.json` now contains your real vus/duration/
thresholds. You never open or hand-edit either file.

### Step 5 — Sanity-check it (1 VU, 1 iteration)

```bash
npm run orders:smoke
```

This runs `orders:gen` again first (so it's always testing your latest edits), then
`k6 run tests/orders/orders-smoke-test.js`. Watch the console for the check results and
threshold pass/fail summary.

### Step 6 — Run the real load profile

```bash
npm run orders:load
```

Same idea, but drives the `orders-load` profile — 20 VUs for 1 minute, per what you put
in the `profiles` sheet in Step 2.

### Step 7 — Look at the results

- Console: k6 prints checks + thresholds directly.
- HTML report: `reports/orders-smoke-test-report.html` and
  `reports/orders-load-test-report.html` (the names came from the `reportName` column
  you set in Step 2) — open either in a browser.

---

## Updating an Existing Endpoint Later

Once an endpoint exists, there's no scaffolding step — just edit and recompile:

| You changed... | Do this | Command |
|---|---|---|
| A request row (endpoint, method, expectedStatus, …) | Edit `tests/<name>/<name>.xlsx`, sheet `<name>` | `npm run <name>:gen` |
| A perf param (vus, duration, thresholds, pick, …) | Edit `tests/<name>/<name>.xlsx`, sheet `profiles` | `npm run <name>:gen` |
| The request body | Edit `tests/<name>/<name>-requestpayload.json` | `npm run <name>:gen` |
| Nothing — just want to run it | — | `npm run <name>:smoke` or `npm run <name>:load` (each runs `:gen` first automatically) |

So in practice: **edit the `.xlsx` and/or the payload `.json` → run
`npm run <name>:gen` (or skip straight to `:smoke`/`:load`, which does it for you) →
`<name>-scenario.json` and `profiles.json` are overwritten to match → k6 runs against
the fresh data.**

If you ever run `k6 run tests/<name>/<name>-load-test.js` directly instead of through
`npm run`, k6 will use whatever `-scenario.json`/`profiles.json` was last generated —
your `.xlsx` edits won't be picked up until you run `:gen` (or `:smoke`/`:load`) again.

Commit all four files together: the `.xlsx`, the payload `.json`, and the two generated
JSON files — they're checked in so a teammate can run the test without a compile step,
even though every `:smoke`/`:load` run regenerates them anyway.

---

## Auth Types

| `authType` | Behavior |
|---|---|
| `none` (default) | No auth headers added |
| `apikey` | Adds a header from `__ENV.API_KEY` (header name from `__ENV.API_KEY_HEADER`, default `x-api-key`) |
| `oauth2` | Fetches a Bearer token once in `setup()` via client-credentials grant (`OAUTH2_TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, optional `OAUTH2_SCOPE`), reused for every VU/iteration |

## Design Principles (why the framework is shaped this way)

- **One self-contained folder per endpoint** — no shared workbook, no shared compiled
  JSON folder.
- **Excel is the single source of truth for performance inputs** — VUs, duration,
  stages, thresholds, pick strategy, think time never live in a `.js` file.
- **Reusable components stay in `src/`** — client, auth, request builder, scenario
  runner — the only things shared across endpoints.
- **Environment-driven configuration** — `config/environments.json`, overridable with
  `-e ENV=` / `-e BASE_URL=`.

See [FRAMEWORK_GUIDE.md](./FRAMEWORK_GUIDE.md) for a deeper module-by-module walkthrough.
