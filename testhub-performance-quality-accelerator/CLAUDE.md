# k6 Performance Framework

## Purpose

Reusable performance-testing framework built using:

- k6 (JavaScript-based load testing)
- dotenv-style environment configuration

## Design Principles

- **One self-contained folder per endpoint** under `tests/<name>/` — no shared
  workbook, no shared compiled-JSON folder. Adding or changing one endpoint
  never touches another's files.
- Reusable components (`src/`) — client, auth, request builder, scenario
  runner — are the only things shared between endpoints.
- Environment-driven configuration (`config/environments.json`, override via `-e ENV=`)
- Every performance input (VUs, duration, stages, thresholds, pick strategy,
  think time) comes from that endpoint's own Excel workbook — never hardcoded
  in a test file.

## Structure Per Endpoint

```
tests/<name>/
  <name>.xlsx                 source — sheet "<name>": request row(s)
                                        sheet "profiles": "<name>-smoke" / "<name>-load" rows (perf params)
  <name>-requestpayload.json  source — POST/PUT/PATCH body, wired in via the payloadFile column
  <name>-scenario.json        generated — `npm run <name>:gen`, never hand-edited
  profiles.json                generated — ditto
  <name>-smoke-test.js        k6 test — 1 VU / 1 iteration
  <name>-load-test.js         k6 test — VUs/duration/stages from the "<name>-load" profile row
```

k6's Goja runtime can't parse `.xlsx`, so the workbook is compiled to JSON
ahead of the run by `scripts/excel-to-scenario.mjs`. The two `-test.js` files
are otherwise identical generic shells (loaders + `runScenario`) — only the
`PROFILE` constant differs between smoke and load.

`src/utils/dataLoader.js` / `optionsLoader.js` both take a `dir` parameter
(defaults to `test-data/scenarios` for backward compatibility, but every
current test passes `'tests/<name>'` explicitly) so each endpoint's compiled
JSON stays fully isolated from every other endpoint's.

## Scaffolding a New Endpoint

`npm run new-endpoint -- <name> [--method GET] [--path /api/<name>] [--auth none]`
(`scripts/new-endpoint.mjs`) creates the whole folder above in one shot,
plus `<name>:gen` / `<name>:smoke` / `<name>:load` npm scripts. It writes one
example request row — open the workbook afterwards to add auth, headers,
chaining (`extractField`/`injectAs`), or additional weighted rows for a load
mix, and tune the `profiles` sheet's vus/duration/stages/thresholds to the
endpoint's actual SLA.

Manual equivalent of the compile step (if you edit the workbook directly):
```
node scripts/excel-to-scenario.mjs --file tests/<name>/<name>.xlsx --out-dir tests/<name>
```

See `tests/createuser/` (reqres.in's `POST /api/users`) as a worked example.

## Future Enhancements

- `frontend/` — static HTML instruments to author scenarios visually (not yet built)
- Contract/schema validation for response shapes

## Coding Standards

- Plain JS (k6's Goja runtime does not support arbitrary npm/ESM the way Node does —
  avoid adding dependencies that need bundling)
- Static classes with static methods, matching api-test-framework's style
- Keep business logic (services) separate from test files (options/thresholds only)
- Fetch anything expensive (e.g. OAuth2 tokens) once in `setup()`, never per-iteration
