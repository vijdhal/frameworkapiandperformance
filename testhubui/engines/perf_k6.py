"""
TestHub Automation Studio — Performance Testing engine (Grafana k6).

Emits the k6-performance-framework drop (workbook, payload, smoke/load test
files) plus the compiled JSON pair his excel-to-scenario.mjs would normally
produce (profiles.json, <slug>-scenario.json) — written directly from the same
data as the workbook, so a run needs no separate `npm run <slug>:gen` step.
Everything lands together under <Performance accelerator (k6) root>/tests/<slug>/.

The intent surface deliberately overlaps the API accelerator's — endpoint,
method, headers, payload, auth — because that is the whole argument for the
Studio: capture the test once, emit it for whichever engine has to prove it.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from .base import ACCEL, GENERATED_MARKER, Assets, Row, field, register, section


def _js(s) -> str:
    return json.dumps(str(s))


def _safe(s: str) -> str:
    return ''.join(c for c in str(s or '').strip() if c.isalnum() or c in '-_') or 'asset'


def _k6_install_hint() -> str:
    """Install command for the platform the Studio is actually running on.

    A preflight that says "brew install k6" to someone on Windows has told them
    nothing — the whole point of these strings is that they can be pasted.
    """
    if sys.platform == 'win32':
        return 'winget install k6  (or: choco install k6)'
    if sys.platform == 'darwin':
        return 'brew install k6'
    return 'see https://k6.io/docs/get-started/installation/'


# ── The k6-performance-framework export ────────────────────────────────────
#
# The client's framework (testhub-performance-quality-accelerator, the 6 Sep 2026 evening
# drop in TestHUbAutomationStudio.zip) is Excel-driven end to end: a test file is
# ten lines that name a profile and a directory, and everything else — endpoint,
# method, payload, thresholds, VUs, duration — lives in a workbook that
# `scripts/excel-to-scenario.mjs` compiles to JSON before the run. His rule from
# the call: everything for one endpoint lives in tests/<assetname>/ and nothing is
# shared. This emits exactly that into the vendored copy of his framework at
# `testhub-performance-quality-accelerator/` (VENDORED.md there):
#
#   tests/<slug>/<slug>.xlsx                    sheet <slug> (request) + sheet profiles
#   tests/<slug>/<slug>-requestpayload.json     body, only when the request has one
#   tests/<slug>/<slug>-smoke-test.js           fixed-work sanity run, sequential
#   tests/<slug>/<slug>-<profile>-test.js       the shape configured in the Studio
#   + <slug>:gen / <slug>:smoke / <slug>:<profile> merged into his package.json
#
# The slug is lowercase because his compiler lowercases a sheet name to derive
# the JSON filename, while the test asks for the scenario by the name it was
# given. A camelCase name compiles to a file the test never opens. One lowercase
# slug everywhere and that mismatch cannot happen.
#
# The two compiled JSON files are NOT emitted. His workflow, stated on the call:
# the only files a person creates or edits are the .xlsx and the payload .json;
# `npm run <slug>:gen` compiles them. The Studio adds those npm scripts to his
# package.json (app.py does the edit, render() stays pure — same rule as afc).
#
# The tests import from `../../src/utils/…`, which resolves because they land
# inside his tree. Verified 2026-09-06: both emitted tests ran green under k6
# from there (smoke 2/2 checks, load 20/20 over 2 VUs × 5s) against a 201 mock.

FW_RESERVED_SLUGS = {
    'createuser': 'tests/createuser/ is his shipped example.',
    'profiles': 'his compiler reads a sheet by that name as the profiles sheet, not as requests.',
    'profile': 'his compiler reads a sheet by that name as the profiles sheet, not as requests.',
    'config': 'his compiler reads a sheet by that name as the profiles sheet, not as requests.',
    'options': 'his compiler reads a sheet by that name as the profiles sheet, not as requests.',
}

FW_REQUEST_COLS = ['name', 'endpoint', 'method', 'authType', 'headers', 'payload',
                   'payloadFile', 'expectedStatus', 'maxResponseMs', 'extractField',
                   'injectAs', 'weight']

# The profile columns the Studio fills, in his order. His compiler reads any
# subset (a blank or absent column means "not this lever"), and on the 6 Sep
# call he asked for exactly this: "you don't need to have all these [46]; take
# the values which are available". The full header is in his FRAMEWORK_GUIDE.md.
FW_PROFILE_COLS = ['profile', 'vus', 'iterations', 'duration', 'stages', 'p95_ms', 'errorRate',
                   'checkRate', 'scenarioSheet', 'pick', 'think', 'iterationSleep', 'env', 'reportName']


def _fw_slug(name) -> str:
    """The compiler's own rule: lowercase, runs of non-alphanumerics to '-'."""
    return re.sub(r'[^a-z0-9]+', '-', str(name or '').lower()).strip('-') or 'asset'


def _has(v) -> bool:
    return v is not None and str(v).strip() != ''


def _num(v):
    """JS `Number(String(v).trim())`, rendered the way JSON.stringify would."""
    f = float(str(v).strip())
    return int(f) if f == int(f) else f


def _fw_profile_row(key: str, slug: str, *, vus='', duration='', iterations='', stages='',
                    p95_ms, error_rate, check_rate='', pick: str, think='',
                    iteration_sleep, report_name: str) -> dict:
    row = {c: '' for c in FW_PROFILE_COLS}
    row.update({'profile': key, 'vus': vus, 'duration': duration, 'iterations': iterations,
                'stages': stages, 'p95_ms': p95_ms, 'errorRate': error_rate,
                'checkRate': check_rate, 'scenarioSheet': slug, 'pick': pick, 'think': think,
                'iterationSleep': iteration_sleep, 'env': 'dev', 'reportName': report_name})
    return row


def _fw_workbook(slug: str, request_row: dict, profile_rows: list[dict]) -> bytes:
    """His per-endpoint workbook: one request sheet named after the endpoint,
    one profiles sheet. Blank cells are left truly empty — his compiler treats
    a blank as "this profile does not use that lever"."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    wb.properties.creator = GENERATED_MARKER + ' Automation Studio'
    wb.properties.description = (
        f'{GENERATED_MARKER} Automation Studio — k6-performance-framework workbook for {slug}. '
        f'Compile: node scripts/excel-to-scenario.mjs --file tests/{slug}/{slug}.xlsx '
        f'--out-dir tests/{slug}  (npm run {slug}:gen)')
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='FF6A1A')

    def sheet(ws, cols, rows):
        ws.append(cols)
        for cell in ws[1]:
            cell.font, cell.fill = header_font, header_fill
        for r in rows:
            ws.append([None if not _has(r.get(c)) else r[c] for c in cols])
        for i, name in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, min(40, len(name) + 6))

    ws = wb.active
    ws.title = slug
    sheet(ws, FW_REQUEST_COLS, [request_row])
    sheet(wb.create_sheet('profiles'), FW_PROFILE_COLS, profile_rows)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _fw_test_js(slug: str, key: str, env_var: str) -> str:
    """One of his ten-line tests: profile + directory, everything else in Excel."""
    L = ["import { sleep } from 'k6';",
         "import { loadScenario } from '../../src/utils/dataLoader.js';",
         "import { loadOptions, loadRunParams } from '../../src/utils/optionsLoader.js';",
         "import { resolveAuthContext } from '../../src/utils/authSetup.js';",
         "import { runScenario } from '../../src/utils/scenarioRunner.js';",
         "import { buildSummary } from '../../src/utils/htmlReport.js';",
         '',
         '// GENERATED by TestHub Automation Studio, in testhub-performance-quality-accelerator shape.',
         '// Self-contained endpoint, same layout as tests/createuser/. Everything this file',
         f'// needs lives right next to it in tests/{slug}/:',
         f'//   {slug}.xlsx                 — source: the "{slug}" request row +',
         f'//                                 the "{key}" row of its "profiles" sheet',
         f'//   {slug}-requestpayload.json  — source: the body (via the payloadFile column), if any',
         f'//   {slug}-scenario.json        — generated: `npm run {slug}:gen`',
         f'//   profiles.json               — generated: `npm run {slug}:gen`',
         '// Run gen once before k6, and again after editing the workbook or the payload:',
         f'//   node scripts/excel-to-scenario.mjs --file tests/{slug}/{slug}.xlsx --out-dir tests/{slug}',
         f"const DIR = 'tests/{slug}';",
         f"const PROFILE = '{key}';",
         'const run = loadRunParams(PROFILE, DIR);',
         f"const scenario = loadScenario(run.scenarioSheet || '{slug}', DIR);",
         '',
         'export const options = loadOptions(PROFILE, DIR);',
         '',
         'export function setup() {']
    if env_var:
        L += [f'    // The Studio was told the bearer token lives in ${env_var}. The row is',
              '    // authType oauth2 so AuthStrategyResolver sends it as `Authorization: Bearer …`,',
              '    // but the token is read from the environment here instead of being fetched',
              '    // by client-credentials. The value is never written into a generated asset;',
              '    // an unset variable fails loudly in the resolver rather than sending nothing.',
              f'    return {{ auth: {{ token: __ENV.{env_var} }} }};']
    else:
        L.append('    return { auth: resolveAuthContext(scenario) };')
    L += ['}',
          '',
          'export default function (data) {',
          '    runScenario(scenario, {',
          '        auth: data.auth,',
          "        pick: run.pick || 'sequential',",
          '        think: run.think || 0,',
          '    });',
          '    if (run.iterationSleep) {',
          '        sleep(run.iterationSleep);',
          '    }',
          '}',
          '',
          'export function handleSummary(data) {',
          f"    return buildSummary(data, run.reportName || '{key}-test-report');",
          '}',
          '']
    return '\n'.join(L)


# ── The compiled JSON pair, emitted directly ────────────────────────────────
#
# The client's excel-to-scenario.mjs normally compiles <slug>.xlsx into these two
# files before a run (npm run <slug>:gen). The functions below are a Python
# reading of that compiler's normaliseRow()/buildProfile()/buildThresholds(),
# limited to the columns this engine ever fills — so the Studio can write the
# compiled shape directly and a run needs no separate compile step first.
def _fw_scenario_json(request_row: dict, payload_obj) -> str:
    out = {
        'name': request_row['name'],
        'endpoint': request_row['endpoint'],
        'method': request_row['method'],
    }
    if _has(request_row.get('authType')):
        out['authType'] = request_row['authType']
    if _has(request_row.get('headers')):
        out['headers'] = json.loads(request_row['headers'])
    if payload_obj is not None:
        out['payload'] = payload_obj
    if _has(request_row.get('expectedStatus')):
        out['expectedStatus'] = _num(request_row['expectedStatus'])
    if _has(request_row.get('maxResponseMs')):
        out['maxResponseMs'] = _num(request_row['maxResponseMs'])
    if _has(request_row.get('extractField')):
        out['extractField'] = request_row['extractField']
    if _has(request_row.get('injectAs')):
        out['injectAs'] = request_row['injectAs']
    if _has(request_row.get('weight')):
        out['weight'] = _num(request_row['weight'])
    return json.dumps([out], indent=2) + '\n'


def _fw_thresholds(p95_ms, error_rate, check_rate) -> dict:
    t = {}
    if _has(p95_ms):
        t['http_req_duration'] = [f'p(95)<{_num(p95_ms)}']
    if _has(error_rate):
        t['http_req_failed'] = [f'rate<{_num(error_rate)}']
    if _has(check_rate):
        t['checks'] = [f'rate>{_num(check_rate)}']
    return t


def _fw_profiles_json(profile_rows: list[dict]) -> str:
    out = {}
    for row in profile_rows:
        options: dict = {}
        if _has(row.get('stages')):
            options['stages'] = [{'duration': d, 'target': v} for d, v in _parse_stages(row['stages'])]
        elif _has(row.get('iterations')):
            if _has(row.get('vus')):
                options['vus'] = _num(row['vus'])
            options['iterations'] = _num(row['iterations'])
        else:
            if _has(row.get('vus')):
                options['vus'] = _num(row['vus'])
            if _has(row.get('duration')):
                options['duration'] = row['duration']
        thresholds = _fw_thresholds(row.get('p95_ms'), row.get('errorRate'), row.get('checkRate'))
        if thresholds:
            options['thresholds'] = thresholds

        run = {}
        if _has(row.get('scenarioSheet')):
            run['scenarioSheet'] = row['scenarioSheet']
        if _has(row.get('pick')):
            run['pick'] = str(row['pick']).lower()
        if _has(row.get('think')):
            run['think'] = _num(row['think'])
        if _has(row.get('iterationSleep')):
            run['iterationSleep'] = _num(row['iterationSleep'])
        if _has(row.get('env')):
            run['env'] = row['env']
        if _has(row.get('reportName')):
            run['reportName'] = row['reportName']

        out[row['profile']] = {'options': options, 'run': run}
    return json.dumps(out, indent=2) + '\n'


PROFILES = {
    'smoke':  [('30s', 1)],
    'load':   [('1m', 10), ('3m', 10), ('1m', 0)],
    'stress': [('1m', 10), ('2m', 50), ('2m', 100), ('1m', 0)],
    'soak':   [('2m', 20), ('30m', 20), ('2m', 0)],
    'spike':  [('10s', 5), ('30s', 200), ('10s', 5), ('10s', 0)],
}


def _parse_stages(raw):
    """Parse an explicit ramp: 'duration:VUs' pairs, comma-separated.

    '1m:10, 3m:50, 1m:0' -> [('1m', 10), ('3m', 50), ('1m', 0)]

    Returns [] when nothing usable is given, so the caller falls back to the
    profile. Raises ValueError on a malformed pair rather than emitting a k6
    script that silently does the wrong thing.
    """
    text = str(raw or '').strip()
    if not text:
        return []
    out = []
    for i, part in enumerate(p.strip() for p in text.split(',') if p.strip()):
        if ':' not in part:
            raise ValueError(
                f'Stage {i + 1} ("{part}") must be duration:VUs, e.g. 1m:50')
        dur, vus = (x.strip() for x in part.rsplit(':', 1))
        if not dur:
            raise ValueError(f'Stage {i + 1} is missing a duration')
        try:
            vus_n = int(vus)
        except ValueError:
            raise ValueError(f'Stage {i + 1} VUs ("{vus}") must be a whole number')
        if vus_n < 0:
            raise ValueError(f'Stage {i + 1} VUs cannot be negative')
        out.append((dur, vus_n))
    return out


class PerfK6Engine:
    id = 'perf'
    title = 'Performance Testing'
    emits_assets = True

    @property
    def can_execute(self) -> bool:
        return shutil.which('k6') is not None

    def preflight(self) -> tuple[bool, str]:
        k6 = shutil.which('k6')
        if k6:
            return True, f'k6 found at {k6} — scripts can be generated and run.'
        return True, ('k6 is not installed, so scripts are generated but cannot be run here. '
                      f'Install with:  {_k6_install_hint()}')

    def schema(self):
        return [
            section('Target', [
                field('assetName', 'Asset Name', required=True, placeholder='clients'),
                field('serviceName', 'Service Name', required=True, placeholder='customer-service'),
                field('method', 'HTTP Method', 'select', options=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], default='GET'),
                field('baseUrl', 'Base URL', required=True, placeholder='https://api.example.com'),
                field('endpoint', 'Endpoint', required=True, placeholder='/v1/clients', width='full'),
            ]),
            # The columns of his request sheet, in his order: name | endpoint | method |
            # authType | headers | payload/payloadFile | expectedStatus | maxResponseMs |
            # extractField | injectAs | weight. Asked for on the 6 Sep call: "you have
            # the matching of response also, maximum response, inject as and weight".
            section('Request row', [
                field('rowName', 'Name', placeholder='Create user',
                      hint='The request row\'s name column and the group name in the k6 output. Defaults to the Test Name.'),
                field('fwAuthType', 'authType', 'select', options=['none', 'apikey', 'oauth2'], default='none',
                      hint='apikey reads API_KEY / API_KEY_HEADER from the environment at run time; oauth2 fetches a '
                           'client-credentials token in setup(). none with a bearer env var below sends that bearer.'),
                field('headersJson', 'Headers (JSON)', 'textarea', width='full',
                      placeholder='{ "Accept": "application/json" }'),
                field('payload', 'Body (JSON)', 'textarea', width='full', placeholder='{ "name": "demo" }',
                      hint='Written to <name>-requestpayload.json and referenced from the payloadFile column.'),
                field('authEnvVar', 'Bearer token env var', placeholder='API_TOKEN',
                      hint='Name only — the value is read from the environment at run time, never written into a script.'),
                field('expectedStatus', 'expectedStatus', default='200'),
                field('maxResponseMs', 'maxResponseMs', default='2000',
                      hint='Per-request budget checked on every call. The p95 gate below is the distribution threshold.'),
                field('extractField', 'extractField', placeholder='id',
                      hint='Dotted path in the response to capture, e.g. id or data.token.'),
                field('injectAs', 'injectAs', placeholder='userId',
                      hint='Context key the captured value is stored under, for {{ctx:key}} in later rows.'),
                field('weight', 'weight', default='1',
                      hint='Relative pick weight when a profile runs in weighted mode.'),
            ], note='One row per endpoint. extractField/injectAs only matter once a second row is added to the sheet by hand.'),
            section('Smoke profile', [
                field('smokeVus', 'vus', default='1'),
                field('smokeIterations', 'iterations', default='1'),
                field('smokeP95', 'p95_ms', default='2000'),
                field('smokeErrorRate', 'errorRate', default='0.01'),
                field('smokeCheckRate', 'checkRate', default='0.99'),
            ], note='The <name>-smoke row of the profiles sheet: a fixed-work sanity run, sequential.'),
            section('Load profile', [
                field('p95', 'p95_ms', default='800', required=True),
                field('errorRate', 'errorRate', default='0.01',
                      hint='Max fraction of failed requests, e.g. 0.01 = 1%'),
                field('vus', 'vus', placeholder='(profile default)',
                      hint='Peak concurrent users. Scales the profile, or sets the target for Duration / Stages.'),
                field('duration', 'duration', placeholder='e.g. 30s, 5m',
                      hint='Total run time at vus. A k6 duration string. Overrides the profile when Stages is empty.'),
                field('stages', 'stages', width='full', placeholder='1m:10, 3m:50, 1m:0',
                      hint='Explicit ramp as duration:VUs pairs, comma-separated. Highest precedence — overrides duration and profile.'),
                field('profile', 'Profile', 'select', options=list(PROFILES), default='load',
                      hint='Names the second row and test: <name>-load, -stress, -spike or -soak.'),
                field('iterations', 'iterations', placeholder='(duration-driven)',
                      hint='Total iterations shared across VUs. Fixed-work run — replaces the ramp; k6 cannot do both at once.'),
            ], note='The <name>-<profile> row: weighted pick, 1s sleep between iterations. Thresholds are the pass/fail gate — '
                    'k6 exits non-zero when breached, so CI fails honestly. Precedence: Iterations > Stages > Duration > Profile. '
                    'The same shape drives the Studio\'s own self-contained k6 script.'),
            section('Framework Export', [
                field('testName', 'Test Name', width='full',
                      placeholder='(defaults to asset-service)',
                      hint='Lowercased into the slug that names the endpoint folder and everything '
                           'in it: tests/<slug>/<slug>.xlsx, <slug>-requestpayload.json, '
                           '<slug>-smoke-test.js, <slug>-<profile>-test.js. One slug, so nothing can drift apart.'),
            ], note='Writes the four files of a self-contained endpoint into testhub-performance-quality-accelerator/tests/<slug>/ '
                    '(the shape of its tests/createuser) and adds <slug>:gen, <slug>:smoke and <slug>:<profile> to that '
                    'package.json. Then, as the client put it: the only two files you edit are the .xlsx and the payload .json; '
                    'npm run <slug>:gen compiles them into <slug>-scenario.json and profiles.json before k6 runs. '
                    'The self-contained script and its Ortoni gate still land in that folder\'s studio/ and still run here.'),
        ]

    def build_matrix(self, cfg: dict) -> list[Row]:
        # The Test Name becomes a sheet name, a folder and a workbook filename in
        # the client's tree, and some of those words already mean something there.
        # Refuse them at generate time, where a human is still reading the screen,
        # rather than let the overwrite guard bounce a confusing path later.
        slug = _fw_slug(str(cfg.get('testName') or '').strip() or
                        f"{_safe(cfg.get('assetName'))}-{_safe(cfg.get('serviceName'))}")
        if slug in FW_RESERVED_SLUGS:
            raise ValueError(f'Test Name "{cfg.get("testName") or slug}" is reserved in the k6 framework: '
                             f'{FW_RESERVED_SLUGS[slug]} Pick another name.')
        profile = (cfg.get('profile') or 'load').lower()
        if profile not in PROFILES:
            raise ValueError(f'unknown load profile: {profile}')
        stages = PROFILES[profile]
        peak = max(v for _, v in stages) or 1
        override = str(cfg.get('vus') or '').strip()
        vus_target = None
        if override:
            try:
                vus_target = int(override)
                scale = vus_target / peak
                stages = [(d, max(0, round(v * scale))) for d, v in stages]
            except ValueError:
                raise ValueError('Virtual Users must be a whole number')

        # Explicit Stages and Duration override the profile ramp. Precedence,
        # highest first: Iterations (below) > Stages > Duration > Profile.
        # k6's own executor rules force the exclusivity — a run's end is either
        # duration-driven or work-driven, never both.
        explicit_stages = _parse_stages(cfg.get('stages'))
        ramp_source = 'profile'
        if explicit_stages:
            stages = explicit_stages
            ramp_source = 'stages'
        else:
            duration = str(cfg.get('duration') or '').strip()
            if duration:
                target = vus_target if vus_target is not None else peak
                if target < 1:
                    target = 1
                stages = [(duration, target)]
                ramp_source = 'duration'

        # k6 rejects `stages` and `iterations` together — a ramp is duration-driven
        # and iterations are work-driven, and the two cannot both define when the
        # run ends. Rather than emit a script k6 refuses, iterations switches the
        # executor to shared-iterations and the ramp is dropped, which is stated
        # in the row detail so nobody has to infer it from the output.
        iterations = str(cfg.get('iterations') or '').strip()
        if iterations:
            try:
                iterations_n = int(iterations)
                if iterations_n < 1:
                    raise ValueError
            except ValueError:
                raise ValueError('Iterations must be a whole number of 1 or more')
            vus_n = max(v for _, v in stages) or 1
            rows = [Row(
                name=f'{profile} — {iterations_n} iterations',
                kind='positive',
                detail=f'{iterations_n} iterations shared across {vus_n} VU(s); '
                       f'the {profile} ramp is not used when iterations are set.',
                data={'stages': stages, 'profile': profile,
                      'iterations': iterations_n, 'vus': vus_n,
                      'ramp_source': 'iterations'},
            )]
        else:
            label = {'stages': 'explicit stages', 'duration': 'duration',
                     'profile': f'{profile} — staged ramp'}[ramp_source]
            rows = [Row(
                name=label,
                kind='positive',
                detail=' → '.join(f'{v} VU for {d}' for d, v in stages),
                data={'stages': stages, 'profile': profile,
                      'ramp_source': ramp_source},
            )]
        for tname, expr in (('p95 duration', f"p(95)<{cfg.get('p95') or 800}"),
                            ('error rate', f"rate<{cfg.get('errorRate') or 0.01}")):
            rows.append(Row(name=f'threshold — {tname}', kind='threshold',
                            detail=expr, data={'threshold': expr}))
        return rows

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        asset = _safe(cfg.get('assetName'))

        # Everything this engine emits lands in ONE folder:
        # <Performance accelerator (k6) root>/tests/<slug>/. The slug is the Test
        # Name (Framework Export section) when given, else the Asset Name alone —
        # Service Name never enters the file/folder naming.
        display = str(cfg.get('testName') or '').strip() or asset
        slug = _fw_slug(display)
        row_name = str(cfg.get('rowName') or '').strip() or display
        fw = Path((cfg.get('paths') or {}).get('perfFramework') or ACCEL['perf'])
        ep_dir = fw / 'tests' / slug

        stages = rows[0].data['stages']
        profile = rows[0].data['profile']
        method = (cfg.get('method') or 'GET').upper()

        headers = {}
        raw = (cfg.get('headersJson') or '').strip()
        if raw:
            try:
                headers = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f'Headers must be valid JSON: {e}')
        body = (cfg.get('payload') or '').strip()
        if body:
            try:
                json.loads(body)
            except json.JSONDecodeError as e:
                raise ValueError(f'Body must be valid JSON: {e}')

        # _safe() falls back to 'asset' for empty input — fine for a filename, wrong
        # here, because 'asset' is truthy and an env-var-less request would then
        # carry a dead `__ENV.asset` Authorization check. Guard on the raw value.
        env_var = _safe(cfg.get('authEnvVar')) if str(cfg.get('authEnvVar') or '').strip() else ''
        status = cfg.get('expectedStatus') or '200'

        ep = '/' + (cfg.get('endpoint') or '').lstrip('/')
        data0 = rows[0].data
        p95_n = _num(cfg.get('p95') or 800)
        err_n = _num(cfg.get('errorRate') or 0.01)

        # A payload file is only honest when the request actually carries a body.
        # Emitting an empty {} for a GET would put an artifact in the tree that the
        # run never reads — the kind of thing a reviewer counts as evidence.
        has_payload = bool(body) and method in ('POST', 'PUT', 'PATCH')
        payload_obj = json.loads(body) if has_payload else None

        # His resolver knows apikey, oauth2 and none. An explicit apikey/oauth2 is
        # his framework's own strategy and needs no help from the test. A bearer
        # token named by env var has no strategy of its own, so it rides the oauth2
        # path with the token supplied by the emitted test's setup() (_fw_test_js).
        fw_auth = str(cfg.get('fwAuthType') or 'none').strip().lower()
        if fw_auth not in ('none', 'apikey', 'oauth2'):
            raise ValueError('authType must be none, apikey or oauth2')
        bearer_from_env = env_var if fw_auth == 'none' else ''

        def cell(key, default):
            v = str(cfg.get(key) or '').strip()
            return _num(v) if v else default
        try:
            request_row = {
                'name': row_name, 'endpoint': ep, 'method': method,
                'authType': fw_auth if fw_auth != 'none' else ('oauth2' if env_var else 'none'),
                'headers': json.dumps({str(k): str(v) for k, v in headers.items()}) if headers else '',
                'payload': '',
                'payloadFile': f'tests/{slug}/{slug}-requestpayload.json' if has_payload else '',
                'expectedStatus': int(status) if str(status).isdigit() else 200,
                'maxResponseMs': cell('maxResponseMs', 2000),
                'extractField': str(cfg.get('extractField') or '').strip(),
                'injectAs': str(cfg.get('injectAs') or '').strip(),
                'weight': cell('weight', 1),
            }
            smoke = dict(vus=cell('smokeVus', 1), iterations=cell('smokeIterations', 1),
                         p95_ms=cell('smokeP95', 2000), error_rate=cell('smokeErrorRate', 0.01),
                         check_rate=cell('smokeCheckRate', 0.99))
        except ValueError as e:
            raise ValueError(f'maxResponseMs, weight and the smoke profile values must be numbers: {e}')
        if bool(request_row['extractField']) != bool(request_row['injectAs']):
            raise ValueError('extractField and injectAs go together: a captured value needs a context key, and a key needs a value')

        # The configured shape, resolved by build_matrix — iterations, an explicit
        # or profile ramp, or VUs for a duration — as his compiler's columns.
        if data0.get('iterations'):
            shape = {'vus': data0.get('vus') or 1, 'iterations': data0['iterations']}
        elif data0.get('ramp_source') == 'duration' and len(stages) == 1:
            shape = {'vus': stages[0][1], 'duration': stages[0][0]}
        else:
            shape = {'stages': ', '.join(f'{d}:{v}' for d, v in stages)}

        profile_rows = [_fw_profile_row(f'{slug}-smoke', slug, **smoke, pick='sequential', think=0,
                                        iteration_sleep=0, report_name=f'{slug}-smoke-test-report')]
        keys = [f'{slug}-smoke']
        if profile != 'smoke':
            keys.append(f'{slug}-{profile}')
            profile_rows.append(_fw_profile_row(
                f'{slug}-{profile}', slug, **shape, p95_ms=p95_n, error_rate=err_n,
                pick='weighted', iteration_sleep=1, report_name=f'{slug}-{profile}-test-report'))

        assets = Assets(rows=len(rows), sheet=f'{asset}Perf')
        if has_payload:
            assets.add(ep_dir / f'{slug}-requestpayload.json',
                       json.dumps(payload_obj, indent=4) + '\n')
        assets.add(ep_dir / f'{slug}.xlsx', _fw_workbook(slug, request_row, profile_rows))
        for key in keys:
            assets.add(ep_dir / f'{key}-test.js', _fw_test_js(slug, key, bearer_from_env))

        # The compiled JSON pair — normally `npm run <slug>:gen`'s output — written
        # directly from the same data as the workbook above, so a run needs no
        # separate compile step first.
        assets.add(ep_dir / f'{slug}-scenario.json', _fw_scenario_json(request_row, payload_obj))
        assets.add(ep_dir / 'profiles.json', _fw_profiles_json(profile_rows))

        # No Ortoni/Playwright gate spec is emitted here on purpose: every asset
        # this engine writes must stay inside the performance accelerator's own
        # tests/<slug>/ folder — nothing performance-related lands under the API
        # accelerator. Performance evidence is the k6 HTML report the framework's
        # own handleSummary() writes (see htmlReport.js), not an Ortoni entry.

        # Not files: the three package.json entries his scaffold would have added.
        # app.py merges them into the accelerator's package.json after the write —
        # editing his file is an app concern, render() stays pure (same rule as afc).
        scripts = {f'{slug}:gen': (f'node scripts/excel-to-scenario.mjs --file tests/{slug}/{slug}.xlsx '
                                   f'--out-dir tests/{slug}')}
        for key in keys:
            scripts[key.replace(f'{slug}-', f'{slug}:', 1)] = \
                f'npm run {slug}:gen && k6 run -e ENV=dev tests/{slug}/{key}-test.js'
        assets.extras = {'npmScripts': scripts, 'packageJson': str(fw / 'package.json')}
        return assets


engine = register(PerfK6Engine())
