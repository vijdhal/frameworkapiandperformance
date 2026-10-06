"""
Tests for generator.py — the component that writes every asset the platform
produces, and which had NO tests at all until now.

Why this file exists
--------------------
The 132 TypeScript tests validate the *framework*. They say nothing about the
generator. `scripts/demo.sh` exercises it end to end, which catches "it crashed"
but never "it emitted a subtly wrong assertion" — and a subtly wrong assertion is
exactly what ships to a client and passes review unnoticed.

For a company whose position is "we prove the technology did the right work", an
unverified generator is the gap a client QA or security review finds first.

What is asserted
----------------
1. DETERMINISM — same intent in, identical assets out. Every other guarantee
   rests on this: if output drifts between runs, no reviewer can sign anything
   off, and golden-file review is impossible.
2. STRUCTURE — the matrix produces a happy path, every row carries an expected
   status, and emitted specs contain real Playwright scaffolding.
3. SAFETY INVARIANTS — no secret literals in generated assets, and no invented
   HTTP status codes. Both are promises the design already makes; making them
   tests stops them eroding into conventions.

API shapes below were read from the module, not assumed:
    lenient_json_parse(text) -> (ordered_pairs, name_map) | None
    build_matrix(cfg, fields, create_method) -> (column_names, rows_as_dicts)

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

from generator import (  # noqa: E402
    build_matrix,
    lenient_json_parse,
    render_data_ts,
    render_test_ts,
)


# ───────────────────────── fixtures ─────────────────────────

def base_cfg(**over) -> dict:
    cfg = {
        'assetName': 'clients',
        'serviceName': 'customer-service',
        'method': 'POST',
        'endpoint': '/v1/clients',
        'expectedStatus': '201',
        'bodyFormat': 'JSON',
        'requestPayload': '{ "name": "Morpheus", "job": "leader" }',
        'expectedResponse': '',
        'positive': True,
        'negative': True,
        'env': 'dev',
        'authType': 'apikey',
    }
    cfg.update(over)
    return cfg


def fields_from(cfg) -> list:
    parsed = lenient_json_parse(cfg['requestPayload'])
    assert parsed is not None, 'fixture payload should parse'
    pairs, _names = parsed
    return pairs


def matrix(cfg):
    """-> (column_names, rows) where each row is a dict keyed by column name."""
    return build_matrix(cfg, fields_from(cfg), cfg.get('method', 'POST'))


# ───────────────────────── 1. determinism ─────────────────────────

def test_matrix_is_deterministic():
    cfg = base_cfg()
    f = fields_from(cfg)
    assert build_matrix(cfg, f, 'POST') == build_matrix(cfg, f, 'POST'), \
        'build_matrix is not deterministic — golden review would be impossible'


def test_render_is_deterministic():
    cfg = base_cfg()
    f = fields_from(cfg)
    assert render_data_ts(cfg, f, 'POST') == render_data_ts(cfg, f, 'POST'), \
        'render_data_ts emitted different bytes for identical input'


# ───────────────────────── 2. structure ─────────────────────────

def test_matrix_has_a_happy_path_and_typed_rows():
    cfg = base_cfg()
    header, rows = matrix(cfg)
    assert 'TestName' in header, f'unexpected header: {header}'
    assert rows, 'no scenario rows produced'
    assert any('happy' in str(r.get('TestName', '')).lower() for r in rows), \
        'no happy-path row in the matrix'
    assert all('ExpectedStatus' in r for r in rows), 'a row carries no ExpectedStatus'


def test_no_invented_http_status_codes():
    """Every emitted status must be a real HTTP status, never a made-up number."""
    header, rows = matrix(cfg := base_cfg())
    codes = {str(r['ExpectedStatus']).strip() for r in rows
             if str(r.get('ExpectedStatus', '')).strip()}
    assert codes, 'matrix emitted no expected statuses at all'
    for c in codes:
        assert c.isdigit() and len(c) == 3 and c[0] in '12345', \
            f'implausible HTTP status emitted: {c!r}'


def test_spec_contains_playwright_scaffolding():
    cfg = base_cfg()
    spec = render_test_ts(cfg, 'clients', 'customer-service', 'clients-tests.xlsx',
                          has_body=True, has_params=False)
    assert 'import' in spec
    assert 'test.describe' in spec or 'test(' in spec


def test_spec_runs_parallel_by_default_and_falls_back_to_serial_on_chaining():
    """Parallel is the default; serial is earned by the data, not assumed.

    Requested 30 Aug 2026. The mode must not be a hard-coded literal:
    ContextStore is process-local, so a sheet that chains (extractField feeds a
    later row's injectAs) is wrong under parallel — and wrong QUIETLY, because an
    unresolved ctx: token renders as the literal "{{ctx:key}}" and a permissive
    endpoint still answers 2xx. That is a green report over a gate that never ran.

    So this asserts the shape, not just the word: the ternary reads the loaded
    rows, and no unconditional `mode: 'serial'` survives anywhere in the spec.
    """
    spec = render_test_ts(base_cfg(), 'clients', 'customer-service',
                          'clients-tests.xlsx', has_body=True, has_params=False)

    assert "mode: 'serial' }" not in spec, 'mode must not be hard-coded to serial'
    assert "CHAINS_BETWEEN_TESTS ? 'serial' : 'parallel'" in spec
    assert 'testData.some(row => row.extractField && row.injectAs)' in spec, \
        'the fallback must be derived from the loaded rows, not a flag'

    # The decision has to be made before the describe it configures.
    assert spec.index('CHAINS_BETWEEN_TESTS') < spec.index("test.describe('")


def test_scaffold_ts_also_defaults_to_parallel():
    """The OTHER generator gets the same guard.

    `scripts/scaffold.ts` emits the spec shape the client had on screen, and unlike
    generator.py its workbook DOES declare extractField/injectAs columns — so its
    serial fallback is live, not dead code. pytest cannot execute TypeScript, but
    it is the gate that always runs, and a source assertion is enough to stop the
    literal being re-hard-coded in a path the Python tests otherwise never see.

    Both branches were verified against a real workbook through DataLoader on
    2026-08-30: blank chaining cells -> parallel, extractField+injectAs -> serial.
    """
    src = (Path(__file__).resolve().parents[2] / 'testhub-api-quality-accelerator' / 'scripts' / 'scaffold.ts').read_text()

    assert "mode: 'serial' }" not in src, 'scaffold.ts must not hard-code serial'
    assert "mode: CHAINS_BETWEEN_TESTS ? 'serial' : 'parallel'" in src
    assert 'testData.some(row => row.extractField && row.injectAs)' in src


@pytest.mark.parametrize('payload', [
    '{ "name": "Morpheus" }',
    '{ "id": "demo1", "nested": { "a": 1 } }',
    '{ "name": "Morpheus", "job": "leader", "extra": "x" }',
])
def test_varied_json_payloads_produce_rows(payload):
    header, rows = matrix(base_cfg(requestPayload=payload))
    assert rows, f'no scenario rows for payload {payload!r}'


# ───────────────────────── 3. safety invariants ─────────────────────────

SECRET_MARKERS = ('password=', 'apikey=', 'api_key=', 'bearer ey', 'secret=')


def test_no_secret_literals_in_generated_assets():
    """Generated assets carry env-var REFERENCES, never values.

    This is the invariant the MFT design already promises ("no secret is ever
    written into a generated asset"). Asserting it stops the promise decaying
    into a convention nobody checks.
    """
    out = render_data_ts(base_cfg(authType='apikey'), fields_from(base_cfg()), 'POST').lower()
    for marker in SECRET_MARKERS:
        assert marker not in out, f'possible secret literal in generated asset: {marker!r}'


def test_unsupported_verbs_follow_the_endpoint_shape():
    """PUT/PATCH against a COLLECTION is not a route; against a RESOURCE it is.

    This shipped hard-coded to the resource answer. Against a collection
    endpoint that put two rows in every generated suite which could never
    pass — and the mirror case is worse, because asserting 404 on a route that
    actually works is a test that passes while checking nothing.
    """
    from generator import _unsupported_verb_rows

    collection = dict(_unsupported_verb_rows('/api/users'))
    resource = dict(_unsupported_verb_rows('/api/users/2'))

    assert collection['PUT'] == '404' and collection['PATCH'] == '404'
    assert resource['PUT'] == '200' and resource['PATCH'] == '200'
    # GET/DELETE/OPTIONS/HEAD do not depend on the distinction.
    for verb in ('GET', 'DELETE', 'OPTIONS', 'HEAD'):
        assert collection[verb] == resource[verb]


@pytest.mark.parametrize('endpoint,is_resource', [
    ('/api/users', False),
    ('/api/users/2', True),
    ('/api/users/{id}', True),
    ('/api/users/:id', True),
    ('/v1/orders/3f2504e0-4f89-11d3-9a0c-0305e82c3301', True),
    ('/v1/orders', False),
    ('/', False),
    ('', False),
])
def test_endpoint_shape_detection(endpoint, is_resource):
    from generator import _is_resource_endpoint
    assert _is_resource_endpoint(endpoint) is is_resource


@pytest.mark.parametrize('body_format', ['JSON', 'XML', 'URLENCODED', 'FORM'])
def test_every_body_format_follows_the_endpoint_shape(body_format):
    """The first version of this fix only reached the JSON path.

    Testing the helper in isolation could not catch that — the helper was
    right, three of the five call sites simply never asked it. So assert
    through the actual matrix, per body format, which is the level at which
    "did every path get fixed" is answerable.

    Formats whose rule is genuinely different (MFT is GET-only, the strict
    mock rejects non-POST — both 405 Method Not Allowed) are excluded on
    purpose: 405 is the correct code for an existing path that refuses a verb,
    and is not a collection-vs-resource question.
    """
    def statuses(endpoint):
        cfg = base_cfg(bodyFormat=body_format, endpoint=endpoint,
                       requestPayload='{ "name": "Morpheus", "job": "leader" }')
        _hdr, rows = matrix(cfg)
        return {str(r['TestName']): str(r['ExpectedStatus'])
                for r in rows if 'Unsupported' in str(r.get('TestName', ''))}

    collection = statuses('/api/users')
    resource = statuses('/api/users/2')
    if not collection:
        pytest.skip(f'{body_format} emits no Unsupported rows')

    for verb, expected in (('PUT', '404'), ('PATCH', '404')):
        key = f'Unsupported {verb}'
        if key in collection:
            assert collection[key] == expected, \
                f'{body_format}: collection endpoint should expect {expected} for {verb}'
            assert resource[key] == '200', \
                f'{body_format}: resource endpoint should expect 200 for {verb} ' \
                f'— this path is still hard-coded'


def test_generated_assets_identify_themselves():
    """The banner is what lets generate() recognise its own output. Without it
    the overwrite guard treats every previously-generated file as hand-written
    and refuses to reissue it, which breaks the ordinary regenerate loop."""
    from generator import _banner
    import engines.base as eb
    assert eb.GENERATED_MARKER.lower() in _banner('clients', 'customer').lower()


def test_lenient_json_parse_tolerates_sloppy_input():
    """Testers paste trailing commas and single quotes. That tolerance is
    load-bearing for the Studio's UX and must not regress."""
    pairs, _ = lenient_json_parse('{ "a": 1, }')     # trailing comma
    assert pairs == [('a', 1)]
    pairs, _ = lenient_json_parse("{ 'a': 1 }")      # single quotes
    assert pairs == [('a', 1)]


def test_lenient_json_parse_returns_none_on_garbage():
    """Unparseable input returns None rather than raising — the Studio depends on
    that to show a validation message instead of a 500."""
    assert lenient_json_parse('not json at all') is None
