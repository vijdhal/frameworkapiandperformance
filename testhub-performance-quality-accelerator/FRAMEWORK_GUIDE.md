# k6 Performance Framework — Human Guide

## What Is This?

A load-testing framework for REST APIs, built on [k6](https://k6.io). It mirrors the
folder structure of `api-test-framework` (env config, auth strategies, data-driven
tests, docs) so the two frameworks are easy to reason about together, and so a frontend
can eventually be layered on the same way it was for `api-test-framework`.

`frontend/` and a `scripts/scaffold.js` generator are deliberately **not** built yet —
this pass only lays the folders and reusable modules they'll need.

---

## Folder Structure

```
k6-performance-framework/
│
├── config/
│   ├── environments.json   # baseUrl per environment (dev, qa, sit)
│   ├── config.js            # resolves baseUrl for the current ENV
│   ├── environment.js        # ENV export — BASE_URL, USERS, DURATION
│   └── thresholds.js         # pass/fail thresholds shared by every test
│
├── src/
│   ├── clients/
│   │   └── apiClient.js      # thin wrapper over k6/http — generic request() +
│   │                           get/post/put/patch/del/head/options + send()
│   │
│   ├── auth/
│   │   ├── AuthStrategy.js            # documents the getHeaders() contract
│   │   ├── AuthStrategyResolver.js    # picks a strategy from an authType string
│   │   ├── ApiKeyAuth.js              # adds an x-api-key header
│   │   └── OAuth2ClientCredentials.js # fetches a Bearer token (call once in setup())
│   │
│   ├── services/
│   │   ├── apiService.js     # generic endpoint-parametrised service — the shared core
│   │   └── userService.js    # hand-written domain example built on apiService
│   │
│   └── utils/
│       ├── requestBuilder.js    # scenario row → {method,url,payload,headers,expect,…}
│       ├── scenarioRunner.js    # runs a scenario: build → send → validate → chain ctx
│       ├── optionsLoader.js     # loadOptions()/loadRunParams() ← profiles.json
│       ├── authSetup.js          # resolveAuthContext() — fetch OAuth2 token in setup()
│       ├── dataLoader.js         # loadScenario('load') → test-data/scenarios/load-scenario.json
│       ├── responseValidator.js  # validateResponse() / validateStatus() / extract()
│       ├── logger.js             # console request/response logging
│       └── htmlReport.js         # handleSummary() → self-contained HTML report
│
├── scripts/                   # Node-only tooling — never imported by k6
│   ├── seed-workbook.mjs      # `npm run seed:workbook` — write a starter scenarios.xlsx
│   ├── excel-to-scenario.mjs  # `npm run gen:scenarios` — .xlsx → JSON
│   └── run.mjs                # launcher — compile + resolve env + `k6 run`
│
├── tests/
│   ├── smoke/    smoke-test.js    # 1 VU, 1 iteration — sanity check
│   ├── load/     load-test.js     # steady load at expected traffic
│   ├── stress/   stress-test.js   # ramps past normal capacity
│   ├── spike/    spike-test.js    # sudden burst, then recovery
│   └── soak/     soak-test.js     # sustained load over a long duration
│
├── test-data/
│   ├── excel/
│   │   └── scenarios.xlsx  # authoring surface — request sheet per profile + "profiles" sheet
│   ├── payloads/          # request bodies referenced by a row's payloadFile column
│   └── scenarios/          # generated JSON (git-tracked): <sheet>-scenario.json per
│                            # request sheet, plus profiles.json from the "profiles" sheet
│
├── logs/                  # local run output (npm run load:dev > logs/load.log)
├── reports/                # generated HTML reports land here
├── .github/workflows/ci.yml
├── .env                    # BASE_URL / USERS / DURATION reference for local shell export
├── README.md
└── package.json
```

---

## How Configuration Resolves

1. `config/environments.json` defines `baseUrl` per environment.
2. `config/config.js` reads `__ENV.ENV` (default `dev`), looks it up, and exposes
   `Config.baseUrl`. An explicit `BASE_URL` env var always overrides the file.
3. `config/environment.js` re-exports that as `ENV.BASE_URL`, alongside `ENV.USERS` and
   `ENV.DURATION` — this is what existing tests import.

k6 has no bundler by default, so this uses JSON (native `JSON.parse` + `open()`) rather
than YAML — a hand-rolled or npm YAML parser would need a build step k6 doesn't have
here.

Why JSON instead of the YAML api-test-framework uses: same reason.

---

## Auth — How It Works

Call `AuthStrategyResolver.resolve(authType, context)` to get a headers object:

| `authType` | What happens |
|---|---|
| `apikey` | Reads `API_KEY` / `API_KEY_HEADER` from `__ENV`, returns `{ [header]: key }` |
| `oauth2` | Requires `context.token` — fetch it once via `OAuth2ClientCredentials.fetchToken()` inside `setup()`, then pass it through |
| `none` / blank | Returns `{}` |

OAuth2 is fetch-once-in-`setup()` by design: k6 VUs don't share JS state, so caching a
token per-VU (like api-test-framework's file-backed `TokenManager`) isn't meaningful
here — `setup()` runs exactly once regardless of VU count, and its return value is
handed to every VU's default function.

---

## Scenario-Driven Requests (how every test now works)

### 1. Author in Excel

`test-data/excel/scenarios.xlsx` (`npm run seed:workbook` writes a starter copy).

#### Request sheets — `smoke`, `load`, `stress`, `spike`, `soak`

One row = one HTTP call. Only `endpoint` is required.

| column | meaning |
|---|---|
| `name` | label shown in the k6 output group |
| `endpoint` | path (`/api/users/2`) or absolute URL; may contain `{{ctx:key}}` |
| `method` | GET / POST / PUT / PATCH / DELETE / HEAD / OPTIONS |
| `authType` | `apikey` / `oauth2` / `none` (see Auth section) |
| `headers` | JSON object literal, e.g. `{"Accept":"application/json"}` |
| `payload` | inline JSON request body |
| `payloadFile` | repo-relative path to a JSON file under `test-data/payloads/` (wins over `payload`) |
| `expectedStatus` | asserted status code |
| `maxResponseMs` | fail the check if the response is slower |
| `extractField` | dotted path read from the response body (`data.id`) |
| `injectAs` | context key that value is stored under, usable as `{{ctx:<injectAs>}}` in a later row |
| `weight` | relative pick frequency when `PICK=weighted` |

#### `profiles` sheet — every run parameter

One row per profile. **All k6 run parameters and framework knobs come from here** —
nothing is hard-coded in the test files. Only `profile` is required; blank cells are
ignored.

**Executor shape** (resolution order: `stages` → `rate` → `vus`+`iterations` → `vus`+`duration`)

| column | k6 option | notes |
|---|---|---|
| `executor` | `scenarios.default.executor` | optional explicit override |
| `vus` | `vus` | constant VU count |
| `startVus` | `startVUs` | for ramping (`stages`) |
| `duration` | `duration` | `30s`, `1m`, `2h` |
| `iterations` | `iterations` | fixed count instead of a duration |
| `stages` | `stages` | `"30s:20, 1m:50, 30s:0"` — `dur:targetVUs` pairs |
| `rate` / `timeUnit` / `preAllocatedVus` / `maxVus` | arrival-rate executor fields | e.g. 100 iters per `1s` |
| `maxDuration` / `gracefulStop` / `gracefulRampDown` | same | ramp/arrival-rate wind-down |

**Thresholds** (merged onto `config/thresholds.js` defaults)

| column | threshold produced |
|---|---|
| `p90_ms` `p95_ms` `p99_ms` `max_ms` `avg_ms` | `http_req_duration: ['p(95)<…', …]` |
| `errorRate` | `http_req_failed: ['rate<…']` |
| `checkRate` | `checks: ['rate>…']` |
| `rawThresholds` | JSON object, deep-merged last |

**HTTP / engine knobs** → `rps`, `maxRedirects`, `userAgent`, `minIterationDuration`,
`dns`, `insecureSkipTLSVerify`, `noConnectionReuse`, `noVuConnectionReuse`,
`throwOnError` (→ `throw`), `discardResponseBodies`, `summaryTrendStats` (csv),
`tags` (JSON), `hosts` (JSON), `blockHostnames` (csv), `setupTimeout`,
`teardownTimeout`. Bools accept `TRUE`/`FALSE`/`1`/`0`/`yes`/`no`.

| `rawOptions` | JSON object **deep-merged into the final options last** — the escape hatch for any k6 option without a dedicated column |

**Framework run knobs** (emitted under `run`, not k6 options)

| column | effect |
|---|---|
| `scenarioSheet` | request sheet to use (default = profile name) |
| `pick` | `sequential` / `weighted` / `random` (see below) |
| `think` | seconds to sleep between rows in `sequential` mode |
| `iterationSleep` | seconds to sleep at the end of each iteration |
| `env` | target environment (`dev`/`qa`/`sit`) when `--env` isn't passed |
| `baseUrl` | explicit base-URL override for this profile |
| `reportName` | HTML report filename (`reports/<reportName>.html`) |

`-e USERS=` / `-e DURATION=` still override `vus` / `duration` at runtime (ignored for
`stages` / arrival-rate profiles).

### 2. Compile to JSON

```bash
npm run gen:scenarios
```

`scripts/excel-to-scenario.mjs` (Node, uses SheetJS — never loaded by k6) writes
`test-data/scenarios/<sheet>-scenario.json` (inlining any `payloadFile`) and
`test-data/scenarios/profiles.json` (`{ <profile>: { options, run } }`).
`scripts/run.mjs` triggers this before every test.

### 3. Run

`scripts/run.mjs` is the launcher — it makes Excel the source for `ENV`/`BASE_URL`
too (those must be `-e` flags before k6 starts):

```
node scripts/run.mjs <profile> [--env <name>] [--sheet <name>] [--test <path>] [-- <k6 args>]
```

It compiles the workbook, reads `profiles.json`, resolves the env
(`--env` > profile `env` column > `dev`), then runs
`k6 run -e ENV=<…> -e PROFILE=<…> [-e BASE_URL=<…>] [-e SCENARIO=<…>] tests/<profile>/<profile>-test.js`.
The `npm run <profile>[:env]` scripts are thin wrappers over it.

Each test file just wires the profile name through:

```js
const PROFILE = 'load';
const run = loadRunParams(PROFILE);                    // pick / think / iterationSleep / reportName
const scenario = loadScenario(run.scenarioSheet || PROFILE);
export const options = loadOptions(PROFILE);           // full k6 options from Excel

export function setup() { return { auth: resolveAuthContext(scenario) }; }

export default function (data) {
    runScenario(scenario, { auth: data.auth, pick: run.pick, think: run.think });
    if (run.iterationSleep) sleep(run.iterationSleep);
}
export function handleSummary(data) { return buildSummary(data, run.reportName); }
```

`runScenario()` (`src/utils/scenarioRunner.js`) `pick` modes:

| `pick` | behaviour |
|---|---|
| `sequential` | run every row in order, threading `{{ctx:*}}` between them — used by smoke |
| `weighted` | one row per iteration, chosen by `weight` — load/stress/spike/soak |
| `random` | one row per iteration, uniform |

For each row it builds the request (`buildRequest`), sends it (`APIClient.send`),
asserts status + latency (`validateResponse`), and captures `extractField` → context.

---

## How to Run Tests

```bash
npm run smoke            # env from the profile's `env` column
npm run load:qa          # --env qa overrides it
node scripts/run.mjs stress -- --out json=out.json    # pass extra args to k6
```

Reports land at `reports/<reportName>.html` (the `reportName` column).

---

## Test Types

The shape of each (VUs / duration / stages / thresholds) is set in the workbook's
`profiles` sheet — the table below is just the intent.

| Type | Shape | Purpose |
|---|---|---|
| smoke | 1 VU, 1 iteration | Fast sanity check that the API + script work |
| load | constant VUs for a duration | Confirms behaviour at expected traffic |
| stress | ramping stages past normal | Finds the breaking point |
| spike | sharp ramp up/down | Checks recovery from a sudden burst |
| soak | moderate VUs, long duration | Finds leaks/degradation over time |

---

## Environment Variables Reference

Most run parameters live in the workbook's `profiles` sheet. These few stay as
runtime inputs (secrets, or per-run overrides):

| Variable | Used for | Where set |
|---|---|---|
| `ENV` | Selects the block in `config/environments.json` | `scripts/run.mjs --env qa`, or `-e ENV=qa` |
| `PROFILE` | Which profile row `scripts/run.mjs` resolved (informational) | set by the launcher |
| `SCENARIO` | Request sheet to load instead of the profile's default | `--sheet checkout` or `-e SCENARIO=checkout` |
| `BASE_URL` | Overrides `environments.json` entirely | profile `baseUrl` column, `.env`, or CI |
| `USERS` | Overrides the profile's `vus` (constant-VU profiles only) | `-e USERS=50` |
| `DURATION` | Overrides the profile's `duration` (constant-VU profiles only) | `-e DURATION=5m` |
| `API_KEY` / `API_KEY_HEADER` | API key auth | `.env` (exported) or CI |
| `OAUTH2_TOKEN_URL` / `CLIENT_ID` / `CLIENT_SECRET` / `OAUTH2_SCOPE` | OAuth2 auth | `.env` (exported) or CI |

Note: unlike Node-based `api-test-framework`, k6 does not auto-load `.env` — export the
variables to your shell first, or pass them with `-e KEY=value`.
