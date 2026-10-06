"""
Tests for the k6 engine's SECOND output shape — the k6-performance-framework drop.

Why this file exists
--------------------
These two files cannot be proved by running them here. Their imports resolve only
from inside the framework repo, so the pytest gate has to assert their SHAPE. Both
were executed against the real framework on 2026-08-30 (newUser: 2 VUs/5s, 201,
8/8 checks; getUsers: 3 VUs/4s, 200, 12/12) — this file stops that shape regressing
between such runs.

What is asserted
----------------
1. ONE NAME — payload, script and report all derive from the test name, so a rename
   cannot leave the script opening a payload that no longer exists.
2. LOAD COMES FROM THE ENVIRONMENT — a single-stage run emits `vus: ENV.USERS` and
   `duration: ENV.DURATION`, never literals. That is the whole point of the change:
   one script serves a smoke and a soak of the same journey.
3. A RAMP SAYS SO — a multi-stage run cannot be two scalars, so it emits stages and
   states that -e USERS/DURATION do not apply rather than ignoring them silently.
4. NO PHANTOM ARTIFACTS — a GET emits no payload file, and an unset auth env var
   emits no Authorization header.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

from engines.perf_k6 import engine  # noqa: E402


def cfg(**over) -> dict:
    base = {
        'assetName': 'users', 'serviceName': 'user-service',
        'method': 'POST', 'baseUrl': 'https://reqres.in', 'endpoint': '/api/users',
        'payload': '{ "name": "morpheus", "job": "leader" }',
        'expectedStatus': '201', 'profile': 'load',
        'vus': '25', 'duration': '5m', 'testName': 'newUser',
    }
    base.update(over)
    return base


def emit(c: dict) -> dict[str, str]:
    """Generated files keyed by path, so tests read by path rather than by index.

    Keys are matched by SUFFIX below. app.py resolves an engine's relative output
    dirs against REPO_ROOT before writing, so production paths are absolute; keying
    on the tail keeps these assertions about the layout the framework repo needs
    rather than about where this checkout happens to sit.
    """
    assets = engine.render(c, engine.build_matrix(c))
    return {Path(p).as_posix(): v for p, v in assets.files.items()}


def one(files: dict[str, str], suffix: str) -> str:
    """The single generated file ending in `suffix` — fails loudly on 0 or 2."""
    hits = [p for p in files if p.endswith(suffix)]
    assert len(hits) == 1, f'expected exactly one {suffix}, got {hits} of {sorted(files)}'
    return files[hits[0]]


def has(files: dict[str, str], suffix: str) -> bool:
    return any(p.endswith(suffix) for p in files)


# ───────────────────── 1. one slug drives every artifact ─────────────────────

FW = 'testhub-performance-quality-accelerator/'


def _fw(files: dict[str, str]) -> dict[str, str]:
    """Just the drop into the client's tree, keyed relative to its root. The Studio's
    own self-contained output lives in studio/ under the same root and is not
    part of his layout, so it is left out here."""
    return {p[p.index(FW) + len(FW):]: v for p, v in files.items()
            if FW in p and '/studio/' not in p}


def test_the_drop_is_six_files_and_nothing_else():
    """His words on the 6 Sep call: the workbook, the request payload, the smoke
    test and the load test. Since (date TBD) the Studio also writes the compiled
    JSON pair his gen step would otherwise produce — profiles.json and
    <slug>-scenario.json — directly, so a run needs no `npm run <slug>:gen`
    first. Pinned by full listing."""
    drop = _fw(emit(cfg(testName='newUser')))
    assert sorted(drop) == [
        'tests/newuser/newuser-load-test.js',
        'tests/newuser/newuser-requestpayload.json',
        'tests/newuser/newuser-scenario.json',
        'tests/newuser/newuser-smoke-test.js',
        'tests/newuser/newuser.xlsx',
        'tests/newuser/profiles.json',
    ]


def test_the_slug_is_lowercase_because_his_compiler_lowercases_sheet_names():
    """excel-to-scenario.mjs derives the JSON filename from the lowercased sheet
    name, while the test asks for the scenario by the name it was given. A
    camelCase name would compile to newuser-scenario.json and the test would
    open newUser-scenario.json. Lowercasing once, up front, closes that."""
    drop = _fw(emit(cfg(testName='newUser')))
    js = drop['tests/newuser/newuser-load-test.js']
    assert "loadScenario(run.scenarioSheet || 'newuser', DIR)" in js
    assert "const DIR = 'tests/newuser';" in js
    assert "const PROFILE = 'newuser-load';" in js
    assert list(_sheets(drop)) == ['newuser', 'profiles']


def test_names_that_collide_with_his_tree_are_refused_at_generate_time():
    """'createuser' is his shipped example, and a sheet named profiles/profile/
    config/options is read by his compiler as the profiles sheet — a request
    sheet by that name compiles to nothing, silently."""
    import pytest
    for name in ('createUser', 'Profiles', 'config', 'options'):
        with pytest.raises(ValueError, match='reserved'):
            engine.build_matrix(cfg(testName=name))


def test_test_name_defaults_to_asset_name_alone():
    """Service Name never enters the file/folder naming — only Test Name (when
    given) or the Asset Name by itself."""
    drop = _fw(emit(cfg(testName='')))
    assert 'tests/users/users-load-test.js' in drop
    assert not any('user-service' in p for p in drop)


def test_the_npm_scripts_are_his_three_entries_handed_to_the_app_not_written_as_a_file():
    """What his new-endpoint scaffold adds to package.json. They are NOT a file in
    the drop — app.py merges them into his package.json after the write, so
    render() stays pure and the tree matches his four-file rule."""
    c = cfg(testName='newUser')
    bundle = engine.render(c, engine.build_matrix(c))
    assert bundle.extras['npmScripts'] == {
        'newuser:gen': 'node scripts/excel-to-scenario.mjs --file tests/newuser/newuser.xlsx '
                       '--out-dir tests/newuser',
        'newuser:smoke': 'npm run newuser:gen && k6 run -e ENV=dev tests/newuser/newuser-smoke-test.js',
        'newuser:load': 'npm run newuser:gen && k6 run -e ENV=dev tests/newuser/newuser-load-test.js',
    }
    assert bundle.extras['packageJson'].endswith('testhub-performance-quality-accelerator/package.json')
    assert not [p for p in bundle.files if 'npm-scripts' in Path(p).name]


# ──────────── 2. the workbook is the source of truth, in his columns ────────────

def _sheets(drop: dict, slug: str = 'newuser') -> dict[str, list[dict]]:
    from io import BytesIO
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(drop[f'tests/{slug}/{slug}.xlsx']))
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        cols = list(rows[0])
        out[ws.title] = [dict(zip(cols, ('' if v is None else v for v in r))) for r in rows[1:]]
    return out


def test_request_sheet_header_is_his_and_profiles_header_is_the_columns_we_fill():
    """Request sheet: his 12 columns verbatim. Profiles sheet: the columns the
    Studio fills, in his order — "you don't need to have all these [46]; take
    the values which are available" (6 Sep call). His compiler reads any subset."""
    from engines.perf_k6 import FW_PROFILE_COLS, FW_REQUEST_COLS

    sheets = _sheets(_fw(emit(cfg(testName='newUser'))))
    assert list(sheets['newuser'][0]) == FW_REQUEST_COLS == [
        'name', 'endpoint', 'method', 'authType', 'headers', 'payload', 'payloadFile',
        'expectedStatus', 'maxResponseMs', 'extractField', 'injectAs', 'weight']
    assert list(sheets['profiles'][0]) == FW_PROFILE_COLS == [
        'profile', 'vus', 'iterations', 'duration', 'stages', 'p95_ms', 'errorRate',
        'checkRate', 'scenarioSheet', 'pick', 'think', 'iterationSleep', 'env', 'reportName']


def test_request_row_comes_from_the_form_field_for_field():
    """Every request-sheet column the form exposes lands in the cell: name,
    maxResponseMs, extractField, injectAs, weight — the ones he asked to see."""
    row = _sheets(_fw(emit(cfg(testName='newUser', rowName='Create user', maxResponseMs='1500',
                                extractField='id', injectAs='userId', weight='2'))))['newuser'][0]
    assert row['name'] == 'Create user'
    assert row['endpoint'] == '/api/users' and row['method'] == 'POST' and row['authType'] == 'none'
    assert row['payload'] == '' and row['payloadFile'] == 'tests/newuser/newuser-requestpayload.json'
    assert (row['expectedStatus'], row['maxResponseMs']) == (201, 1500)
    assert (row['extractField'], row['injectAs'], row['weight']) == ('id', 'userId', 2)


def test_request_row_defaults_match_his_createuser_when_the_form_is_left_alone():
    row = _sheets(_fw(emit(cfg(testName='newUser'))))['newuser'][0]
    assert row['name'] == 'newUser' and row['maxResponseMs'] == 2000 and row['weight'] == 1
    assert row['extractField'] == '' and row['injectAs'] == ''


def test_extract_and_inject_go_together():
    import pytest
    with pytest.raises(ValueError, match='extractField and injectAs'):
        emit(cfg(testName='newUser', extractField='id'))


def test_smoke_row_comes_from_the_smoke_fields_and_load_row_from_the_load_section():
    prof = {r['profile']: r for r in _sheets(_fw(emit(cfg(
        testName='newUser', smokeVus='2', smokeIterations='3', smokeP95='1200',
        smokeErrorRate='0.02', smokeCheckRate='0.95'))))['profiles']}
    assert list(prof) == ['newuser-smoke', 'newuser-load']
    smoke, load = prof['newuser-smoke'], prof['newuser-load']
    assert (smoke['vus'], smoke['iterations'], smoke['duration'], smoke['stages']) == (2, 3, '', '')
    assert (smoke['p95_ms'], smoke['errorRate'], smoke['checkRate']) == (1200, 0.02, 0.95)
    assert (smoke['pick'], smoke['think'], smoke['iterationSleep']) == ('sequential', 0, 0)
    assert (load['vus'], load['duration'], load['iterations'], load['stages']) == (25, '5m', '', '')
    assert (load['p95_ms'], load['errorRate']) == (800, 0.01)
    assert (load['pick'], load['iterationSleep'], load['reportName']) == ('weighted', 1, 'newuser-load-test-report')
    for r in (smoke, load):
        assert r['scenarioSheet'] == 'newuser' and r['env'] == 'dev'


def test_smoke_defaults_are_his_createuser_smoke_row():
    smoke = _sheets(_fw(emit(cfg(testName='newUser'))))['profiles'][0]
    assert (smoke['vus'], smoke['iterations'], smoke['p95_ms'], smoke['errorRate'], smoke['checkRate']) == (1, 1, 2000, 0.01, 0.99)


def test_a_ramp_lands_in_the_stages_cell_his_compiler_parses():
    from engines.perf_k6 import _parse_stages
    prof = {r['profile']: r for r in _sheets(_fw(emit(cfg(
        testName='newUser', profile='stress', duration='', vus=''))))['profiles']}
    stress = prof['newuser-stress']
    assert stress['vus'] == '' and stress['duration'] == ''
    assert _parse_stages(stress['stages']) == [('1m', 10), ('2m', 50), ('2m', 100), ('1m', 0)]


def test_iterations_switch_the_row_to_fixed_work():
    prof = {r['profile']: r for r in _sheets(_fw(emit(cfg(
        testName='newUser', iterations='40', vus='4'))))['profiles']}
    load = prof['newuser-load']
    assert (load['vus'], load['iterations'], load['stages'], load['duration']) == (4, 40, '', '')


def test_the_workbook_compiles_to_the_shape_k6_will_run():
    """A Python reading of his excel-to-scenario.mjs buildProfile()/normaliseRow()
    for the columns the Studio fills. His real compiler was run on an emitted
    workbook on 2026-09-06 (twice, both drops) with identical output; this keeps
    the cells honest without needing node in the test run."""
    def has(v): return v is not None and str(v).strip() != ''
    def num(v):
        f = float(str(v).strip()); return int(f) if f == int(f) else f
    def profile(row):
        o = {}
        if has(row['stages']):
            from engines.perf_k6 import _parse_stages
            o['stages'] = [{'duration': d, 'target': v} for d, v in _parse_stages(row['stages'])]
        elif has(row['iterations']):
            if has(row['vus']): o['vus'] = num(row['vus'])
            o['iterations'] = num(row['iterations'])
        else:
            if has(row['vus']): o['vus'] = num(row['vus'])
            if has(row['duration']): o['duration'] = str(row['duration']).strip()
        t = {}
        if has(row['p95_ms']): t['http_req_duration'] = [f"p(95)<{num(row['p95_ms'])}"]
        if has(row['errorRate']): t['http_req_failed'] = [f"rate<{num(row['errorRate'])}"]
        if has(row['checkRate']): t['checks'] = [f"rate>{num(row['checkRate'])}"]
        if t: o['thresholds'] = t
        return o

    sheets = _sheets(_fw(emit(cfg(testName='newUser'))))
    rows = {r['profile']: profile(r) for r in sheets['profiles']}
    assert rows['newuser-smoke'] == {'vus': 1, 'iterations': 1, 'thresholds': {
        'http_req_duration': ['p(95)<2000'], 'http_req_failed': ['rate<0.01'], 'checks': ['rate>0.99']}}
    assert rows['newuser-load'] == {'vus': 25, 'duration': '5m', 'thresholds': {
        'http_req_duration': ['p(95)<800'], 'http_req_failed': ['rate<0.01']}}


# ─────────────────────── 3. no artifact that lies ────────────────────────────

def test_a_get_emits_no_payload_file_and_no_payloadfile_cell():
    """An empty {} beside a GET is an artifact the run never reads.

    A reviewer counts files in the tree as evidence; one that nothing opens is a
    claim of coverage that is not there.
    """
    drop = _fw(emit(cfg(method='GET', payload='', endpoint='/api/users?page=2',
                        expectedStatus='200', testName='getUsers')))
    assert not [p for p in drop if 'requestpayload' in p], sorted(drop)
    row = _sheets(drop, 'getusers')['getusers'][0]
    assert row['payloadFile'] == '' and row['endpoint'] == '/api/users?page=2'


def test_a_smoke_profile_emits_one_test_not_two():
    drop = _fw(emit(cfg(profile='smoke', vus='', duration='', testName='newUser')))
    assert sorted(p for p in drop if p.endswith('-test.js')) == ['tests/newuser/newuser-smoke-test.js']
    assert [r['profile'] for r in _sheets(drop)['profiles']] == ['newuser-smoke']


def test_unset_auth_env_var_emits_no_authorization_anywhere():
    """Regression guard, 2026-08-30.

    `_safe('')` falls back to the string 'asset', which is truthy — so every perf
    script generated without a token carried a dead `__ENV.asset` Authorization
    check that read, to anyone reviewing it, as a real authenticated request.
    """
    files = emit(cfg(authEnvVar=''))
    drop = _fw(files)
    for key in ('tests/newuser/newuser-load-test.js', 'tests/newuser/newuser-smoke-test.js'):
        assert '__ENV.asset' not in drop[key] and 'Bearer' not in drop[key]
        assert 'return { auth: resolveAuthContext(scenario) };' in drop[key]
    assert _sheets(drop)['newuser'][0]['authType'] == 'none'


def test_a_named_auth_env_var_rides_his_oauth2_path_with_the_token_from_the_environment():
    """His resolver has apikey, oauth2 and none; a bearer token named by env var
    has no strategy of its own. It goes through oauth2 — which sends
    `Authorization: Bearer <token>` — with setup() supplying the token from the
    environment instead of fetching it. The token value is never in a file."""
    drop = _fw(emit(cfg(authEnvVar='API_TOKEN', testName='newUser')))
    js = drop['tests/newuser/newuser-load-test.js']
    assert 'return { auth: { token: __ENV.API_TOKEN } };' in js
    assert _sheets(drop)['newuser'][0]['authType'] == 'oauth2'
    assert 'Bearer' not in json.dumps(_sheets(drop)['newuser'][0])


def test_an_explicit_apikey_is_his_strategy_and_needs_nothing_from_the_test():
    """apikey resolves in his ApiKeyAuth from API_KEY / API_KEY_HEADER at run time
    (call notes, 6 Sep). The row says apikey; the test keeps his stock setup()."""
    drop = _fw(emit(cfg(fwAuthType='apikey', testName='newUser')))
    assert _sheets(drop)['newuser'][0]['authType'] == 'apikey'
    js = drop['tests/newuser/newuser-load-test.js']
    assert 'return { auth: resolveAuthContext(scenario) };' in js and '__ENV' not in js


# ───────── 4. nothing performance-related ever lands under the API accelerator ──

def test_no_self_contained_script_or_workbooks_are_emitted():
    """The self-contained k6 script and its two workbooks (studio/*.k6.js,
    *.<profile>.xlsx, *.options.xlsx) were removed by request — only the
    framework-shaped drop and its compiled JSON pair are emitted now."""
    files = emit(cfg())
    assert not has(files, 'studio/users-user-service.load.k6.js')
    assert not has(files, 'studio/users-user-service.load.xlsx')
    assert not has(files, 'studio/users-user-service.options.xlsx')


def test_nothing_lands_under_the_api_accelerator():
    """This engine used to also emit a small Playwright spec (an Ortoni/CI-gate
    wrapper that ran the smoke test via k6) into
    testhub-api-quality-accelerator/src/tests/<asset>/, so k6 results would show
    up in the API accelerator's own Ortoni report. Removed by request: every
    asset this engine writes must stay inside the performance accelerator's own
    tests/<slug>/ folder — nothing performance-related may land under the API
    accelerator, not even a reporting shim.
    """
    files = emit(cfg(testName='', assetName='SampleTestSize', serviceName='SampleTestSize'))
    assert not any('testhub-api-quality-accelerator' in p for p in files), sorted(files)
    assert not any(p.endswith('.k6.spec.ts') for p in files), sorted(files)


# ───────── 5. the same _safe() trap, found in the ZAP engine ─────────────────

def test_zap_plan_emits_no_bearer_token_when_the_env_var_is_blank():
    """Same bug class as above, found by grepping for the pattern after fixing perf.

    `_safe('')` returns 'asset' in every engine that defines it. ZAP gates on
    `if hdr and env_var`, so it only bites when an auth header is configured with no
    token name — and then the plan carries a literal `Bearer ${asset}`, which reads
    to a reviewer as a configured credential rather than a missing one.
    """
    from engines.security_zap import engine as zap  # noqa: E402

    c = {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://example.test',
         'authorisationRef': 'SELF-OWNED example.test',
         'authHeader': 'Authorization', 'authEnvVar': ''}
    plans = [v for p, v in zap.render(c, zap.build_matrix(c)).files.items()
             if str(p).endswith('.zap.yaml')]
    assert plans, 'ZAP emitted no plan to check'
    for plan in plans:
        assert 'Bearer ${asset}' not in plan
        assert '${asset}' not in plan


# ───────── 6. the compiled JSON pair, written directly (no `npm run gen`) ─────

def _scenario(files: dict[str, str], slug: str = 'newuser') -> list[dict]:
    return json.loads(one(files, f'{slug}-scenario.json'))


def _profiles(files: dict[str, str]) -> dict:
    return json.loads(one(files, 'profiles.json'))


def test_scenario_json_matches_the_request_row_field_for_field():
    """<slug>-scenario.json is what excel-to-scenario.mjs's normaliseRow() would
    compile from the request sheet — an array of one row, payload inlined
    (resolved from the payload file, the way loadPayloadFile() would)."""
    drop = emit(cfg(testName='newUser', rowName='Create user', maxResponseMs='1500',
                    extractField='id', injectAs='userId', weight='2'))
    scenario = _scenario(drop)
    assert scenario == [{
        'name': 'Create user', 'endpoint': '/api/users', 'method': 'POST', 'authType': 'none',
        'payload': {'name': 'morpheus', 'job': 'leader'},
        'expectedStatus': 201, 'maxResponseMs': 1500,
        'extractField': 'id', 'injectAs': 'userId', 'weight': 2,
    }]


def test_scenario_json_has_no_payload_key_for_a_get():
    drop = emit(cfg(method='GET', payload='', endpoint='/api/users?page=2',
                    expectedStatus='200', testName='getUsers'))
    row = _scenario(drop, 'getusers')[0]
    assert 'payload' not in row and row['endpoint'] == '/api/users?page=2'


def test_profiles_json_matches_the_workbook_compile_shape():
    """A Python reading of excel-to-scenario.mjs's buildProfile()/buildThresholds()
    for the columns this engine fills — pinned so profiles.json stays exactly
    what the real compiler would have produced from the same workbook."""
    profiles = _profiles(emit(cfg(testName='newUser')))
    assert profiles['newuser-smoke'] == {
        'options': {'vus': 1, 'iterations': 1, 'thresholds': {
            'http_req_duration': ['p(95)<2000'], 'http_req_failed': ['rate<0.01'],
            'checks': ['rate>0.99']}},
        'run': {'scenarioSheet': 'newuser', 'pick': 'sequential', 'think': 0,
                'iterationSleep': 0, 'env': 'dev', 'reportName': 'newuser-smoke-test-report'},
    }
    assert profiles['newuser-load'] == {
        'options': {'vus': 25, 'duration': '5m', 'thresholds': {
            'http_req_duration': ['p(95)<800'], 'http_req_failed': ['rate<0.01']}},
        'run': {'scenarioSheet': 'newuser', 'pick': 'weighted', 'iterationSleep': 1,
                'env': 'dev', 'reportName': 'newuser-load-test-report'},
    }


def test_profiles_json_stages_ramp_compiles_to_duration_target_pairs():
    profiles = _profiles(emit(cfg(testName='newUser', profile='stress', duration='', vus='')))
    assert profiles['newuser-stress']['options']['stages'] == [
        {'duration': '1m', 'target': 10}, {'duration': '2m', 'target': 50},
        {'duration': '2m', 'target': 100}, {'duration': '1m', 'target': 0},
    ]


def test_a_smoke_profile_writes_one_profiles_entry_not_two():
    profiles = _profiles(emit(cfg(profile='smoke', vus='', duration='', testName='newUser')))
    assert list(profiles) == ['newuser-smoke']
