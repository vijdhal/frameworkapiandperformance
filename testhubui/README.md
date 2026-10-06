# testhubui — TestHub Automation Studio

**Start here. Two files matter to a client (6 Sep 2026):**

1. `build_exe.bat` — run once on a Windows machine; it produces `dist\TestHubStudio.exe`.
2. `Start TestHub Studio.bat` — starts the Studio from source (first run creates a venv and installs
   flask + openpyxl); or double-click the exe. Either opens the web UI on the local machine.

Everything else in this folder is the Studio's source: `app.py` (Flask), `generator.py`,
`runner.py`, `heal.py`, `engines/` (the 10 capabilities), `static/index.html` (the UI) and `tests/`.

The Studio must sit inside the repo layout — it finds the accelerators beside it
(`../testhub-api-quality-accelerator`, `../testhub-performance-quality-accelerator`, …) by walking up
from wherever it runs, exe included. Move the exe out of `testhubui/dist/` and it cannot find them.


Connects the Studio frontend to a local Flask backend that writes test assets
**directly into your accelerator repo paths** (no zip download).

## Launching (pick one — easiest first)

**Option A — TestHubStudio.exe (recommended for testers)**
Run `build_exe.bat` once on any machine with Python; distribute the resulting
`dist\TestHubStudio.exe`. End users just double-click it — no Python, no pip,
no terminal. The Studio opens in their browser automatically.

**Option B — Start TestHub Studio.bat**
Double-click it. First run auto-creates a private environment and installs
dependencies (~1 min); every run after that launches in seconds and opens the
browser for you.

**Option C — manual (developers)**
```
pip install flask openpyxl
python app.py
```

In all cases the app picks a free port, opens the browser itself, and if a
Studio instance is already running it simply focuses that one instead of
starting a second copy.

## How it works

- **Save Draft** → POST `/api/draft` — form state saved to `drafts/draft.json` on disk; auto-restored on page load.
- **Generate Test Assets** → POST `/api/generate` — the backend follows the four paths from the Paths modal (e.g. `C:/Users/Melokuhle/testhub-api-quality-accelerator/...`) and writes:
  1. `<Request Payload>/<Asset Name>/<Service Name>.data.ts` — payload builder generated from your actual payload fields (createX, mandatoryOnly, emptyPayload, missingField, invalidField, invalidJson + build switch).
  2. `<Test Script>/<Asset Name>/<Service Name>.test.ts` — excel-driven Playwright spec with correct imports, sheet name and negative-matrix assertions.
  3. `<Test Data (Excel)>/<Asset Name>.xlsx` — sheet named `<Service Name>` with the full governed matrix (happy path, mandatory-only, empty payload, missing/invalid per field, invalid JSON, invalid endpoint, unsupported methods, invalid Accept headers, invalid content type).
  4. `<Response>/<Asset Name>/<Service Name>.json` — the expected response body.

## Test Runner (Generated Files tab → Test Runner)

The right-hand tab is now a live CLI runner that monitors your framework:

- **Framework Monitor** — lists every `*.test.ts` (from your Test Script path) and
  `*.data.ts` (from your Request Payload path), grouped by asset, straight off disk.
  ↻ Refresh or reopen the tab to pick up newly generated files.
- Select a `.test.ts`, press **▶ Execute Tests** — the backend runs
  `npx cross-env ENVIRONMENT=<env> playwright test src/tests/<asset>/<service>.test.ts`
  from the accelerator repo root (auto-detected via `package.json`), with the
  environment taken from the Environment dropdown in the header.
- Output streams **live** into the terminal pane (pass/fail colorized), with a
  ■ Stop button to kill a run mid-flight.

Requires Node.js on the machine, plus `cross-env` and `@playwright/test`
installed in the accelerator repo (they already are if the repo runs today).

## Supported body formats

Every format flows through the **same pipeline** — the payload you enter drives
the `.data.ts` builder, the excel scenario matrix, and the expected-response
file. The **Body Format** dropdown selects the request wire format and sets the
`Content-Type`; **Accept is the *response* format** (form/urlencoded/binary
requests still receive JSON responses, so their Accept stays `application/json`).
The invalid-Accept negative rows adjust so the active format is never itself
listed as invalid.

| Body Format | Dropdown | Content-Type | What you enter in the payload box | Generated builder output |
|---|---|---|---|---|
| **JSON** | `JSON` | `application/json` | `{ name: 'morpheus', job: 'leader' }` (JS-style accepted) | object passthrough; the `invalidJson` row is preserved verbatim |
| **XML / SOAP** | `XML` | `application/xml` (also `text/xml`, `application/soap+xml`) | `<root><name>morpheus</name><job>leader</job></root>` | raw XML string built from excel data |
| **Multipart** | `FORM` | `multipart/form-data` | JSON fields; a value like `{ file: 'test-data/files/sample.pdf', type: 'application/pdf' }` becomes a file part | `{ fields, files }` — files streamed from disk; boundary set automatically |
| **URL-encoded** | `URLENCODED` | `application/x-www-form-urlencoded` | JSON fields, e.g. `{ name: 'morpheus', job: 'leader' }` | `{ fields }` → `URLSearchParams` string (same builder as multipart) |
| **Binary** | `BINARY` | `application/octet-stream` (or the file's own type) | `{ file: 'test-data/files/sample.pdf', type: 'application/pdf' }` | fixture path read into a `Buffer`; negatives = empty / corrupt / non-binary body |
| **ETL** *(draft)* | `ETL` | `text/plain` | `name\|job` then `morpheus\|leader` | delimited flat record from excel data |

On the framework side these are dispatched by `PayloadEncoder.encode(rawBody,
contentType)`; responses are parsed by their Content-Type in
`responseValidator.ts` (XML via `fast-xml-parser`, binary via size + magic-byte
signature, JSON as before).

**ETL is a DRAFT MODEL pending stakeholder approval** before final backend
inclusion. Proposed convention: delimited flat record — line 1 = field names,
line 2 = values, delimiter auto-detected from `|`, `;`, `,` or tab. It
generates a `.data.ts` that builds records from excel data (mandatoryOnly,
emptyPayload, missingField drop columns; invalid body = column-count
mismatch), a text/plain scenario matrix, and the expected response stored
verbatim as `<Service>.txt`. Every generated ETL file is marked DRAFT MODEL
in its header. If the stakeholder prefers a different record convention (fixed-width,
multi-row, trailer records), only `etl_field_parse` and `render_data_ts_etl`
in `generator.py` change — the rest of the pipeline is format-agnostic.

> **Note:** the governed **negative** rows (e.g. *Invalid Body → 400*) assert
> against a properly validating API. Public demo endpoints like `reqres.in` are
> permissive and return `201`, so negative rows only go green against a real
> governed endpoint — which is the point of piloting through Cloud23.

## Excel: append & update, never replace

Per the 21 Jul session: if `<Asset>.xlsx` exists it is opened and the new
service is added as a sheet; if that service sheet exists it is updated in
place. Other sheets are never touched. One workbook per asset, one sheet per
service, all formats side by side.

## Generic by design

- **Any payload fields** — columns and payload methods are derived from whatever JSON you enter (JS-style `{ name: 'x' }` is accepted too).
- **Duplicate field names** → renamed `Field`, `Field_1`, `Field_2`… consistently in both the excel sheet and the `.data.ts`, so the right cell always feeds the right payload key.
- **GET services** — with the "GET with body" toggle on, the payload is treated as a request body; otherwise it becomes a `Params` column read via a `params()` helper, and `build()` returns `undefined` for the body.
- **No duplicates** — existing folders are reused and existing files overwritten in place; re-generating never creates copies.
