"""
TestHub Automation Studio — backend asset generator.

Given the form data captured by the frontend, writes four assets into the
user-configured paths (never duplicating files or folders — existing files
are overwritten in place, existing folders are reused):

  1. <requestPayload>/<Asset>/<Service>.data.ts   — dynamic payload builder
  2. <tests>/<Asset>/<Service>.test.ts            — Playwright excel-driven spec
  3. <excel>/<Asset>.xlsx  (sheet = <Service>)    — governed scenario matrix
  4. <json>/<Asset>/<Service>.json                — expected response body

Generic by design: any payload fields, any service/asset name, GET with a
body OR with query params, duplicated field names renamed Field, Field_1 ...
consistently across the excel sheet and the .data.ts.
"""

import json
import os
import re
import shutil
import subprocess
import time as _perf
from pathlib import Path

# One definition of "did we write this?", shared with the engine registry.
# Two copies of that rule would drift, and the failure mode when they drift is
# silent data loss on one path and spurious refusals on the other.
import engines.base as engines_base

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

# ─────────────────────────────── helpers ───────────────────────────────

def _pascal(s: str) -> str:
    parts = re.split(r'[^A-Za-z0-9]+', s or '')
    return ''.join(p[:1].upper() + p[1:] for p in parts if p) or 'Service'

def _camel(s: str) -> str:
    p = _pascal(s)
    return p[:1].lower() + p[1:]

def _safe_name(s: str) -> str:
    """Filesystem-safe folder / file stem."""
    return re.sub(r'[^A-Za-z0-9._ -]+', '-', (s or '').strip()).strip('-') or 'asset'

# ── safe embedding of user-supplied field names into generated TS/XML ──────
#
# `fields` come straight from a pasted request-payload JSON / XML / form body
# — arbitrary text a caller of the Studio controls. A field name is a string
# key, not a trusted identifier, so it must never be spliced into generated
# source with an f-string: a name like `x', require('child_process')...` or
# a bare `` ` `` breaks out of the quotes/backticks it lands in and turns
# into executable code in the emitted .data.ts. Every place a field name
# reaches generated source goes through one of these instead.

_JS_IDENT_RE = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')
_XML_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]*$')

def _js_str(s: str) -> str:
    """A field name (or any string) as a safely-escaped TS string literal."""
    return json.dumps(s)

def _js_get(k: str, base: str = 'data') -> str:
    """`data.k` for a valid identifier, else the equivalent safe `data['k']`."""
    return f'{base}.{k}' if _JS_IDENT_RE.match(k or '') else f'{base}[{_js_str(k)}]'

def _js_key(k: str) -> str:
    """Object-literal key for `k`: bare when it's a valid identifier, else computed."""
    return f'{k}:' if _JS_IDENT_RE.match(k or '') else f'[{_js_str(k)}]:'

def _xml_tag(k: str) -> str:
    """Validates `k` as a safe XML element name; raises rather than emit unsafe XML/JS."""
    if not _XML_NAME_RE.match(k or ''):
        raise ValueError(
            f'field name {k!r} cannot be used as an XML element — use letters, '
            f'digits, "_", "-" or "." and start with a letter or "_"')
    return k

def lenient_json_parse(text: str):
    """
    Accepts strict JSON *and* JS-style objects like { name: 'morpheus' }.
    Preserves duplicate keys by renaming: Field, Field_1, Field_2 ...
    Returns (ordered list of (unique_key, value), original_key_map) or None.
    original_key_map maps unique_key -> the key as typed by the user.
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    # normalise JS-ish syntax → JSON
    t = re.sub(r"'([^'\\]*)'", r'"\1"', t)                       # single → double quotes
    t = re.sub(r'([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)\s*:', r'\1"\2":', t)  # bare keys
    t = re.sub(r',\s*([}\]])', r'\1', t)                          # trailing commas

    pairs_out, orig_map = [], {}

    def hook(pairs):
        # only apply dedup at the top level; nested objects come through as dicts
        return dict(pairs) if pairs_out else _dedup(pairs)

    def _dedup(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                seen[k] += 1
                uk = f"{k}_{seen[k]}"
            else:
                seen[k] = 0
                uk = k
            pairs_out.append((uk, v))
            orig_map[uk] = k
        return dict(pairs_out)

    try:
        parsed = json.loads(t, object_pairs_hook=hook)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not pairs_out:  # top level was empty object
        return [], {}
    return pairs_out, orig_map


def xml_field_parse(text: str):
    """
    Parse an XML request payload — fields are the root's child elements.
    Duplicate element names renamed Field, Field_1 ... exactly like JSON mode.
    Returns (ordered list of (unique_key, text_value), root_tag) or None.
    """
    if not text or '<' not in text:
        return None
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return None
    pairs, seen = [], {}
    for child in root:
        k = child.tag
        if k in seen:
            seen[k] += 1
            uk = f"{k}_{seen[k]}"
        else:
            seen[k] = 0
            uk = k
        pairs.append((uk, (child.text or '').strip()))
    return pairs, root.tag


def form_field_parse(text: str):
    """
    Parse a FORM/URLENCODED payload entered as JSON. Unlike lenient_json_parse
    (which assumes a flat object and dedups the innermost object first), this
    preserves the *top-level* structure — so a nested file spec like
    { document: { file: '…', type: '…' } } survives intact for form_split.
    Duplicate top-level names are renamed Field, Field_1 … Returns ordered
    list of (unique_key, value) or None.
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    t = re.sub(r"'([^'\\]*)'", r'"\1"', t)                                  # single → double quotes
    t = re.sub(r'([{,]\s*)([A-Za-z_$][A-Za-z0-9_$]*)\s*:', r'\1"\2":', t)   # bare keys
    t = re.sub(r',\s*([}\]])', r'\1', t)                                    # trailing commas

    captured = {}

    def hook(pairs):
        # object_pairs_hook fires innermost-first; the LAST call is the top object.
        captured['top'] = pairs
        return dict(pairs)

    try:
        parsed = json.loads(t, object_pairs_hook=hook)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    out, seen = [], {}
    for k, v in captured.get('top', []):
        if k in seen:
            seen[k] += 1
            uk = f"{k}_{seen[k]}"
        else:
            seen[k] = 0
            uk = k
        out.append((uk, v))
    return out


def _is_file_spec(v):
    """A payload field whose value is an object with a file/path key is a file part."""
    return isinstance(v, dict) and ('file' in v or 'path' in v)


def form_split(fields):
    """
    Split (key, value) pairs into scalar form fields and multipart file specs.
    A value like { file: 'test-data/files/x.pdf', type: 'application/pdf' } becomes
    a file part { field, path, contentType }; everything else stays a scalar field.
    Returns (scalar_pairs, file_specs).
    """
    scalars, files = [], []
    for k, v in fields:
        if _is_file_spec(v):
            files.append({
                'field': k,
                'path': v.get('file') or v.get('path'),
                'contentType': v.get('type') or v.get('contentType') or 'application/octet-stream',
            })
        else:
            scalars.append((k, v))
    return scalars, files


def normalize_form_payload(payload: dict):
    """
    Robustly resolve the FORM/URLENCODED payload into (scalar_pairs, file_specs),
    accepting EVERY shape the frontend or a hand-editor might send:

      1. Structured object (current frontend):
         payload['formFields'] = { 'fields': {name:'x'}, 'files': [{field,path,contentType}] }
      2. requestPayload as a JSON string of that same {fields, files} object.
      3. Legacy nested form: { name:'x', document:{file:'...', type:'...'} }
      4. Flat object: { name:'x', job:'y' }  (no files)

    Returns (scalar_pairs, file_specs). Never raises — bad input yields ([], []).
    """
    def coerce_files(files):
        out = []
        for f in files or []:
            if not isinstance(f, dict):
                continue
            path = f.get('path') or f.get('file')
            if not path:
                continue
            out.append({
                'field': f.get('field') or f.get('name') or 'file',
                'path': path,
                'contentType': f.get('contentType') or f.get('type') or 'application/octet-stream',
            })
        return out

    def from_structured(obj):
        """obj is a {fields, files} dict."""
        scalars, seen = [], {}
        for k, v in (obj.get('fields') or {}).items():
            if k in seen:
                seen[k] += 1; k2 = f"{k}_{seen[k]}"
            else:
                seen[k] = 0; k2 = k
            scalars.append((k2, v))
        return scalars, coerce_files(obj.get('files'))

    # 1 — structured object sent directly
    ff = payload.get('formFields')
    if isinstance(ff, dict) and ('fields' in ff or 'files' in ff):
        return from_structured(ff)

    # 2/3/4 — parse requestPayload string
    raw = payload.get('requestPayload') or ''
    pairs = form_field_parse(raw)
    if not pairs:
        return [], []
    as_dict = {k: v for k, v in pairs}
    # structured {fields, files} that arrived as a JSON string
    if set(as_dict.keys()) <= {'fields', 'files'} and ('fields' in as_dict or 'files' in as_dict):
        return from_structured(as_dict)
    # legacy nested / flat
    return form_split(pairs)


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v

# ───────────────────────── RAML DataType ─────────────────────────
#
# A RAML 1.0 DataType describes the request body: which properties exist, their
# type, and whether each is required. When the user supplies one, it drives the
# negative-matrix expected status codes so the sheet matches what a
# contract-compliant API actually returns:
#
#   missing a required property   -> 400   (the property is absent, see
#                                          missingField() in the emitted .data.ts)
#   missing an optional property  -> happy (omitting it is allowed)
#   invalid value, type string    -> happy ('defect' is a valid string)
#   invalid value, non-string     -> 400   ('defect' violates number/boolean/…)
#
# Only `type` and `required` are evaluated. Constraints such as enum, pattern,
# minLength and format are NOT checked here, so a `string` with an `enum` gets
# the happy code in the sheet even though a real API may return 400 — state that
# limit rather than let it surprise someone.

# 'defect' (the invalid-field probe value) is a valid instance of these types,
# so an invalid-value row for such a field expects the happy code, not 400.
_RAML_STRINGLY_TYPES = {'string', 'any', 'file', 'nil'}


def parse_raml_datatype(text: str) -> dict:
    """Parse a RAML 1.0 DataType into {property: {'type': str, 'required': bool}}.

    The `#%RAML 1.0 DataType` first line is a YAML comment, so safe_load ignores
    it — no stripping needed. Raises ValueError on anything that is not a usable
    DataType so the caller can surface it rather than emit a sheet from a spec it
    could not read.
    """
    import yaml
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f'RAML is not valid YAML: {exc}')
    if not isinstance(doc, dict):
        raise ValueError('RAML DataType must be a YAML mapping with a `properties` block')

    props = doc.get('properties')
    # A bare `type: object` with no properties carries no field contract.
    if not isinstance(props, dict):
        raise ValueError('RAML DataType has no `properties` map')

    out = {}
    for raw_name, spec in props.items():
        name = str(raw_name)
        # RAML shorthand: a trailing '?' on the property name means optional.
        required = True                     # RAML 1.0 default: properties are required
        if name.endswith('?'):
            name = name[:-1]
            required = False

        if spec is None:
            ptype = 'string'                # `name:` alone -> string
        elif isinstance(spec, str):
            ptype = spec                    # `name: string` shorthand
        elif isinstance(spec, dict):
            ptype = str(spec.get('type', 'string'))
            if 'required' in spec:          # explicit wins over the '?' suffix
                required = bool(spec['required'])
        else:
            raise ValueError(f'property "{name}" has an unreadable definition')

        # Normalise: 'string[]' / union 'string | nil' -> base token for our
        # coarse type check. We only need "is this stringly?".
        base = ptype.replace('[]', '').split('|')[0].strip().lower()
        out[name] = {'type': base, 'required': required}

    if not out:
        raise ValueError('RAML DataType `properties` map is empty')
    return out


def raml_conformance_errors(spec: dict, payload) -> list:
    """Compare the sample request payload against the RAML spec.

    Returns a list of human-readable problems: a required property missing from
    the payload, a value whose JSON type contradicts the declared type, or a
    payload key the RAML does not declare. Empty list means they agree.
    """
    errors = []
    if not isinstance(payload, dict):
        return ['the request payload is not a JSON object, so it cannot be '
                'checked against the RAML']

    for name, p in spec.items():
        if p['required'] and name not in payload:
            errors.append(f'required property "{name}" is missing from the '
                          f'request payload')
        if name in payload and not _value_matches_raml_type(payload[name], p['type']):
            errors.append(f'property "{name}" is {p["type"]} in the RAML but '
                          f'the payload value {payload[name]!r} is not')

    declared = set(spec)
    for key in payload:
        if key not in declared:
            errors.append(f'payload key "{key}" is not declared in the RAML')
    return errors


def _value_matches_raml_type(value, raml_type: str) -> bool:
    """Coarse JSON-value/RAML-type agreement, enough to catch a real mismatch."""
    t = raml_type.lower()
    if t in _RAML_STRINGLY_TYPES:
        return True                         # string/any accept anything sane
    if t in ('number', 'integer'):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == 'boolean':
        return isinstance(value, bool)
    if t in ('object',):
        return isinstance(value, dict)
    if t in ('array',):
        return isinstance(value, list)
    return True                             # unknown type -> don't block


def raml_missing_status(spec: dict, field: str, default) -> str:
    """Expected code for a 'Missing <field>' row: 400 if required, else happy."""
    if not spec or field not in spec:
        return default
    return '400' if spec[field]['required'] else default


def raml_invalid_status(spec: dict, field: str, default) -> str:
    """Expected code for an 'Invalid <field>' row.

    The probe value is the string 'defect'. It satisfies a stringly type (happy
    code) and violates number/boolean/object/array (400).
    """
    if not spec or field not in spec:
        return default
    return default if spec[field]['type'] in _RAML_STRINGLY_TYPES else '400'


# ───────────────────────── scenario matrix ─────────────────────────

INVALID_ACCEPTS = [
    ('Invalid Header XML',  'application/xml'),
    ('Invalid Header HTML', 'text/html'),
    ('Invalid Header TEXT', 'text/plain'),
    ('Invalid Header PNG',  'image/png'),
    ('Invalid Header PDF',  'application/pdf'),
]

UNSUPPORTED = [('GET', '200'), ('PUT', '200'), ('PATCH', '200'),
               ('DELETE', '204'), ('OPTIONS', '204'), ('HEAD', '200')]


def build_matrix(cfg, fields, create_method):
    """
    Returns (columns, rows) for the JSON / XML / urlencoded scenario matrix.

    FIDELITY MANDATE (reference spec): each generated suite reproduces its GIVEN
    reference sheet verbatim — same rows, same expected codes — NO INVENTION.
    These three formats run against the PERMISSIVE reqres contract mock
    (reqresContractServer), so their negative rows carry that mock's real codes:

      json  → complex.xlsx / users1  (21 rows)   endpoint /api/users/2 (resource)
      xml   → complex.xlsx / usersXml (19 rows)  endpoint /api/users/2 (resource)
      urlenc→ urlencodedExample.xlsx / urlencoded (31 rows) endpoint /api/urlencoded (collection)

    Resource endpoints (/…/<id>) make Unsupported PUT/PATCH → 200; a collection
    endpoint makes them → 404 — this is why the driver pins those endpoints.
    """
    method     = (cfg.get('method') or 'POST').upper()
    endpoint   = cfg.get('endpoint') or '/'
    status     = str(cfg.get('expectedStatus') or '201')
    auth       = cfg.get('authType') or 'apikey'
    ct         = cfg.get('contentType') or 'application/json'
    accept     = cfg.get('accept') or 'application/json'
    svc        = cfg.get('serviceName') or 'service'
    expected_file = cfg.get('expectedFileRel') or ''
    contract      = cfg.get('contractRel') or ''
    fmt = (cfg.get('bodyFormat') or 'json').lower()

    field_cols = [k for k, _ in fields]
    cols = ['TestName', 'Method', 'Endpoint', 'PayloadMethod'] + field_cols + \
           ['ExpectedStatus', 'ExpectedFile', 'Contract', 'authType', 'ContentType', 'Accept']
    base_vals = {k: _cell(v) for k, v in fields}

    def row(test, m=method, ep=endpoint, pm=create_method, vals=None,
            st=status, ef='', ctr='', c_type=ct, acc=accept, at=auth):
        r = {'TestName': test, 'Method': m, 'Endpoint': ep, 'PayloadMethod': pm,
             'ExpectedStatus': st, 'ExpectedFile': ef, 'Contract': ctr,
             'authType': at, 'ContentType': c_type, 'Accept': acc}
        for k in field_cols:
            r[k] = (vals or base_vals).get(k, '')
        return r

    rows = [row(f'{_pascal(svc)} Happy Path', ef=expected_file, ctr=contract)]
    if not cfg.get('negative'):
        return cols, rows

    f0 = field_cols[0] if field_cols else 'field'
    f1 = field_cols[1] if len(field_cols) > 1 else f0

    if fmt == 'urlencoded':
        # ── urlencodedExample.xlsx / urlencoded — 31 rows (permissive) ──────────
        rows.append(row('Empty Payload', pm='emptyPayload'))                       # 201
        rows.append(row('Missing Name', pm='missingField', vals={**base_vals, f0: ''}))
        rows.append(row('Missing Job',  pm='missingField', vals={**base_vals, f1: ''}))
        rows.append(row('Invalid Name', pm='invalidField', vals={**base_vals, f0: 'defect'}))
        rows.append(row('Invalid Job',  pm='invalidField', vals={**base_vals, f1: 'defect'}))
        rows.append(row('Long Values',  pm=create_method,
                        vals={**base_vals, f0: 'A' * 300, f1: 'B' * 300}))
        rows.append(row('Invalid UrlEncoded', pm='invalidJson'))                   # verbatim junk body → 201
        rows.append(row('Invalid Endpoint', ep='/invalid' + endpoint, st='404'))
        # Derived from the endpoint shape — see _is_resource_endpoint. Hard-coding
        # the collection answer here matched the pinned demo endpoint and asserted
        # 404 against a resource route that works, which passes while checking
        # nothing.
        for m, st in _unsupported_verb_rows(endpoint):
            rows.append(row(f'Unsupported {m}', m=m, st=st))
        for name, acc in INVALID_ACCEPTS:
            rows.append(row(name, acc=acc))                                        # Accept ignored → 201
        rows.append(row('Invalid Content Type', c_type='application/json'))        # object body still JSON-parses → 201
        # Auth negatives — genuinely exercised (the reference sheet's 201s were an
        # artifact of a mis-cased AuthType read + unrecognised authType values that
        # never dropped the key). Missing/invalid credentials are 401 Unauthorized.
        rows.append(row('Missing API Key', at='none', st='401'))                   # no key → 401
        rows.append(row('Invalid API Key', at='invalidApiKey', st='401'))          # wrong key → 401
        rows.append(row('Missing Authorization', at='none', st='401'))             # no credentials → 401
        rows.append(row('Empty Name', vals={**base_vals, f0: ''}))
        rows.append(row('Empty Job',  vals={**base_vals, f1: ''}))
        rows.append(row('SQL Injection',
                        vals={**base_vals, f0: '1 UNION SELECT password FROM users'}, st='403'))
        rows.append(row('XSS Payload',
                        vals={**base_vals, f0: '<script>alert(1)</script>'}, st='403'))
        rows.append(row('Unicode Characters', vals={**base_vals, f0: 'Zoë Müller', f1: 'Développeur'}))
        rows.append(row('Emoji Characters',   vals={**base_vals, f0: 'John 😀', f1: 'QA 🚀'}))
        rows.append(row('Duplicate Request', pm=create_method))
        return cols, rows

    # ── json / xml — permissive shared shape ──────────────────────────────────
    # A RAML DataType, when supplied, sets the expected code for the per-field
    # missing/invalid rows. Absent (raml_spec is None), `st` stays the happy
    # status and the rows are byte-identical to before.
    raml_spec = cfg.get('ramlSpec')
    rows.append(row('Mandatory Only', pm='mandatoryOnly'))                         # 201
    rows.append(row('Empty Payload', pm='emptyPayload'))                           # 201
    rows.append(row('Missing Name', pm='missingField', vals={**base_vals, f0: ''},
                    st=raml_missing_status(raml_spec, f0, status)))
    rows.append(row('Missing Job',  pm='missingField', vals={**base_vals, f1: ''},
                    st=raml_missing_status(raml_spec, f1, status)))
    rows.append(row('Invalid Name', pm='invalidField', vals={**base_vals, f0: 'defect'},
                    st=raml_invalid_status(raml_spec, f0, status)))
    rows.append(row('Invalid Job',  pm='invalidField', vals={**base_vals, f1: 'defect'},
                    st=raml_invalid_status(raml_spec, f1, status)))
    if fmt == 'xml':
        rows.append(row('Invalid XML', pm='invalidJson'))                          # malformed XML → 201 (sheet)
    else:
        rows.append(row('Invalid JSON', pm='invalidJson', st='400'))               # malformed JSON → 400 (sheet)
    rows.append(row('Invalid Endpoint', ep='/invalid' + endpoint, st='404'))
    # Derived from the endpoint shape, not assumed — see _is_resource_endpoint.
    for m, st in _unsupported_verb_rows(endpoint):
        rows.append(row(f'Unsupported {m}', m=m, st=st))
    if fmt == 'xml':
        # usersXml: 3 Invalid Accept rows + Invalid Content Type (text/plain).
        rows.append(row('Invalid Accept HTML', acc='text/html'))
        rows.append(row('Invalid Accept JSON', acc='application/json'))
        rows.append(row('Invalid Accept PNG',  acc='image/png'))
        rows.append(row('Invalid Content Type', c_type='text/plain'))
    else:
        # users1: 5 Invalid Header rows + Invalid Content Type ('defect').
        for name, acc in INVALID_ACCEPTS:
            rows.append(row(name, acc=acc))                                        # Accept ignored → 201
        rows.append(row('Invalid Content Type', c_type='defect'))                  # 201
    return cols, rows

# ───────────────────────── file writers ─────────────────────────

def _obfuscate_spec(path: Path) -> None:
    """Minify a generated .test.ts in place, when THUB_OBFUSCATE_SPEC=1.

    Uses esbuild (the client's own, or npx) to strip comments and collapse the
    spec while keeping test names intact so the Ortoni report stays readable.
    esbuild emits JS, which is valid inside a .test.ts and still runs under
    Playwright. Never fails generation: if esbuild is not available or errors,
    the spec is left readable rather than half-written.
    """
    esbuild = shutil.which('esbuild')
    cmd = [esbuild] if esbuild else ['npx', '--yes', 'esbuild']
    cmd += ['--loader=ts', '--minify', '--keep-names', '--legal-comments=none']
    try:
        src = path.read_text(encoding='utf-8')
        out = subprocess.run(cmd, input=src, capture_output=True, text=True,
                             timeout=60, cwd=str(path.parent))
        code = (out.stdout or '').strip()
        # Only accept a plausible result: non-empty and still importing the
        # framework. Anything else means esbuild did not do what we expect, so
        # keep the readable spec.
        if out.returncode == 0 and len(code) > 40 and 'import' in code:
            # Minified JS-in-.ts loses the type annotations, so a project-wide
            # `tsc` would report implicit-any on it. Playwright runs the spec
            # through its own transpiler and never typechecks, so // @ts-nocheck
            # keeps `tsc` green on the obfuscated file without changing what
            # runs.
            path.write_text('// @ts-nocheck\n' + code + '\n', encoding='utf-8')
    except Exception:
        pass  # leave the spec readable; obfuscation is best-effort


def write_excel(path: Path, sheet: str, cols, rows):
    """
    Meeting 21 Jul rule: if a workbook with this asset name exists, open it and
    add a sheet for the new service; if that service sheet exists, update it in
    place — other sheets are never touched or removed.
    """
    from openpyxl import load_workbook
    sheet = (sheet or 'Sheet1')[:31]
    if path.exists():
        wb = load_workbook(path)
        if sheet in wb.sheetnames:
            idx = wb.sheetnames.index(sheet)
            del wb[sheet]                       # update: rebuild this sheet only
            ws = wb.create_sheet(sheet, idx)
        else:
            ws = wb.create_sheet(sheet)         # append: new service sheet
        # openpyxl needs at least one sheet; drop a leftover blank default
        if 'Sheet' in wb.sheetnames and wb['Sheet'].max_row == 1 \
           and wb['Sheet'].max_column == 1 and wb['Sheet']['A1'].value is None \
           and len(wb.sheetnames) > 1:
            del wb['Sheet']
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet
    ws.append(cols)
    hdr = Font(bold=True, color='FFFFFF')
    fill = PatternFill('solid', fgColor='FF6A1A')
    for c in ws[1]:
        c.font, c.fill = hdr, fill
    for r in rows:
        ws.append([r.get(c, '') for c in cols])
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(14, min(38, len(c) + 6))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def render_data_ts(cfg, fields, create_method) -> str:
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    has_body = bool(fields)
    lines_payload = '\n'.join(f"            {_js_key(k)} {_js_get(k)}," for k, _ in fields).rstrip(',')
    keys_arr = ', '.join(_js_str(k) for k, _ in fields)
    mandatory = cfg.get('mandatoryFields') or [k for k, _ in fields]
    lines_mand = '\n'.join(f"            {_js_key(k)} {_js_get(k)}," for k in mandatory if any(k == fk for fk, _ in fields)).rstrip(',')
    raw_invalid = json.dumps({(fields[0][0] if fields else 'field'): 'value'})[:-1]  # broken JSON on purpose

    params_method = ''
    if cfg.get('params'):
        params_method = f'''
    /** Query params for {(cfg.get('method') or 'GET').upper()} services that use params instead of a body. */
    async params(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return data.Params ? JSON.parse(data.Params) : {{}};
    }}
'''

    if not has_body:
        return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

/**
 * {cls} — generated by TestHub Automation Studio.
 * This service carries no request body ({(cfg.get('method') or 'GET').upper()});
 * params (if any) are read from the excel Params column.
 */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}
{params_method}
    async build(_excelName: string, _sheetName: string, _testName: string, _payloadMethod: string): Promise<any> {{
        return undefined; // no request payload for this service
    }}
}}
'''

    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

const FIELDS = [{keys_arr}];

export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    async {create_method}(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{
{lines_payload}
        }};
    }}

    async mandatoryOnly(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{
{lines_mand}
        }};
    }}

    async emptyPayload(): Promise<Record<string, any>> {{
        return {{}};
    }}

    async missingField(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        const payload: Record<string, any> = {{}};
        for (const f of FIELDS) {{
            // a blank excel cell means the field is intentionally missing for this row
            if (data[f] !== undefined && data[f] !== null && data[f] !== '') payload[f] = data[f];
        }}
        if (data.MissingField) delete payload[data.MissingField];
        return payload;
    }}

    async invalidField(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        const payload: Record<string, any> = {{}};
        for (const f of FIELDS) payload[f] = data[f];
        if (data.InvalidField) payload[data.InvalidField] = data.InvalidValue ?? 'defect';
        return payload;
    }}

    async invalidJson(): Promise<string> {{
        return `{raw_invalid}
        `;
    }}
{params_method}
    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string): Promise<any> {{
        switch (payloadMethod) {{
            case '{create_method}':
                return await this.{create_method}(excelName, sheetName, testName);
            case 'mandatoryOnly':
                return await this.mandatoryOnly(excelName, sheetName, testName);
            case 'emptyPayload':
                return await this.emptyPayload();
            case 'missingField':
                return await this.missingField(excelName, sheetName, testName);
            case 'invalidField':
                return await this.invalidField(excelName, sheetName, testName);
            case 'invalidJson':
                return await this.invalidJson();
            default:
                throw new Error(`Unknown Payload Method : ${{payloadMethod}}`);
        }}
    }}
}}
'''


def render_test_ts(cfg, asset_dir: str, service: str, excel_name: str, has_body: bool, has_params: bool) -> str:
    cls = _pascal(service)
    inst = _camel(service)
    tag = _pascal(cfg.get('assetName') or 'Suite')
    params_block = ''
    if has_params:
        params_block = '''
                //--------------------------------------------
                // Query Params (GET-style services)
                //--------------------------------------------
                const queryParams = row.Params ? JSON.parse(row.Params) : undefined;
'''
    params_arg = '\n                        params: queryParams,' if has_params else ''

    # Format-aware mock wiring, matched to each format's GIVEN reference sheet so
    # the generated suite reproduces those scenarios' exact expected codes — no
    # invention. Form-data's sheet (formData1) is standards-correct, so it runs
    # against the strict multipart mock (uploadContractServer). The json / xml /
    # urlencoded / binary / mft sheets are permissive (Unsupported→200/204,
    # Invalid Header→201, Missing field→201, SQLi/XSS→403, Invalid JSON→400), so
    # they run against reqresContractServer, which returns exactly those codes —
    # the same mock the hand-written example suites already pass against. Each
    # mock binds an ephemeral port so parallel suites never clash.
    fmt_mock = cfg.get('bodyFormat')
    if fmt_mock == 'form':
        mock_import = "import { startUploadMock, UploadMock } from '../../../mocks/uploadContractServer';"
        mock_type   = 'UploadMock'
        mock_start  = 'startUploadMock(0)'
    else:
        mock_import = "import { startReqresMock, ReqresMock } from '../../../mocks/reqresContractServer';"
        mock_type   = 'ReqresMock'
        mock_start  = 'startReqresMock(0)'

    return f'''import {{ test, expect }} from '@playwright/test';
import path from 'path';
import fs from 'fs';

import {cls} from '../../requestPayload/{asset_dir}/{service}.data';
import {{ Config }} from '../../../config/config';
import {{ APIClient }} from '../../client/apiClient';
import {{ loadExcel }} from '../../utils/excelUtils';
import {{ RequestBuilder }} from '../../utils/requestBuilder';
import {{ SmartComparator }} from '../../utils/smartComparator';
import {{ ContractValidator }} from '../../validators/contractValidator';
import {{ ResponseValidator }} from '../../validators/responseValidator';
import {{ ReportHelper }} from '../../utils/reportHelper';
import {{ ContextStore }} from '../../utils/contextStore';
import {{ AuthStrategyResolver }} from '../../auth/AuthStrategyResolver';
import {{ HealMode }} from '../../utils/healMode';
{mock_import}

const excelName = '{excel_name}';
const sheetName = '{service}';
const {inst} = new {cls}();
const testData = loadExcel(excelName, sheetName);
// Parallel by default. Serial ONLY when this sheet actually chains: a row that
// extracts a value into ContextStore for a later row to consume needs a single
// worker, because ContextStore is process-local and a parallel describe is spread
// across worker processes. Chaining is declared in the data (extractField +
// injectAs), so the mode is read from the data instead of assumed.
// A missing ctx: token resolves to the literal "{{{{ctx:key}}}}" rather than throwing,
// so getting this wrong reads as a pass. That is why it is not hard-coded.
// For unconditional parallel, replace the ternary with 'parallel'.
const CHAINS_BETWEEN_TESTS = testData.some(row => row.extractField && row.injectAs);

test.describe.configure({{ mode: CHAINS_BETWEEN_TESTS ? 'serial' : 'parallel' }});

// Set MOCK=1 to run this suite against the bundled deterministic contract mock
// (offline, no rate limits) — ideal for demos and CI. Without MOCK it runs
// against the configured target (config/env.yaml or BASE_URL).
let __mock: {mock_type} | undefined;
let __prevBase: string | undefined;
test.beforeAll(async () => {{
    if (process.env.MOCK) {{
        __mock = await {mock_start};
        __prevBase = process.env.BASE_URL;
        process.env.BASE_URL = __mock.url;
    }}
}});
test.afterAll(async () => {{
    if (__mock) {{
        if (__prevBase === undefined) delete process.env.BASE_URL; else process.env.BASE_URL = __prevBase;
        await __mock.stop();
    }}
}});

test.describe('{tag} Excel Driven API Tests', () => {{
    for (const [index, row] of testData.entries()) {{
        test(`'@{tag}_API @regression' [${{index + 1}}] ${{row.Method}} ${{row.Endpoint}} — ${{row.TestName}}`, async ({{}}, testInfo) => {{
                const client = new APIClient();
                await client.init();
                //--------------------------------------------
                // Base URL
                //--------------------------------------------
                const baseUrl = Config.getServiceUrl(row.Service ?? row.service);
                //--------------------------------------------
                // Authentication
                //--------------------------------------------
                const auth = AuthStrategyResolver.resolve(row.authType);
                //--------------------------------------------
                // Build Payload (undefined for no-body services)
                //--------------------------------------------
                const requestBody = await {inst}.build(excelName, sheetName, row.TestName, row.PayloadMethod);
{params_block}
                const request = await RequestBuilder.build(
                    {{
                        method: row.Method,
                        endpoint: row.Endpoint,
                        expectedStatus: row.ExpectedStatus,
                        headers: {{
                            "Content-Type": row.ContentType,
                            "Accept": row.Accept
                        }},
                        requestBody,{params_arg}
                        authType: row.authType
                    }},
                    baseUrl,
                    auth
                );
                ReportHelper.attachRequest(testInfo, request);
                //--------------------------------------------
                // Execute Request
                //--------------------------------------------
                const response = await client.send(request);
                const status = response.status();
                const body = status === 204 ? null : await response.json();

                ReportHelper.attachResponse(testInfo, status, body);
                //--------------------------------------------
                // Validate Status
                //--------------------------------------------
                const expectedStatus = Number(row.expected?.status ?? row.ExpectedStatus);
                // Smart Run capture pass: record what the service ACTUALLY returned
                // instead of asserting. The accept/defect decision belongs to
                // testhubui/heal.py (proxy URL: any status; non-proxy: below 500;
                // 5xx on a non-proxy URL becomes a defect and never reaches the
                // excel), not to this spec. Outside a capture pass nothing changes.
                const healCapture = HealMode.capturing();
                if (healCapture) {{
                    HealMode.record({{
                        suite:          '{asset_dir}/{service}',
                        excelName,
                        sheetName,
                        rowIndex:       index,
                        rowName:        row.TestName,
                        method:         row.Method,
                        endpoint:       row.Endpoint,
                        resolvedUrl:    request.url,
                        proxy:          HealMode.isProxyUrl(request.url),
                        expectedStatus,
                        actualStatus:   status,
                        elapsedMs:      response.elapsedMs,
                        requestHeaders: HealMode.redactHeaders(request.headers),
                        requestBody:    request.body,
                        responseBody:   body,
                        environment:    HealMode.environment(),
                        capturedAt:     new Date().toISOString()
                    }});
                    testInfo.annotations.push({{
                        type: 'Heal',
                        description: `captured: expected ${{expectedStatus}}, actual ${{status}}`
                            + (HealMode.isProxyUrl(request.url) ? ' (proxy endpoint)' : '')
                    }});
                }} else {{
                    expect(status, `Expected ${{expectedStatus}} but got ${{status}}`).toBe(expectedStatus);
                }}
                //--------------------------------------------
                // Validate Response Time
                //--------------------------------------------
                if (!healCapture && row.expected?.maxResponseMs !== undefined) {{
                    expect(response.elapsedMs).toBeLessThanOrEqual(row.expected.maxResponseMs);
                }}
                //--------------------------------------------
                // Response Validator — status + content-type-driven parsing.
                // File comparison is delegated to SmartComparator below, which
                // understands the __DEFINED__/__REGEX__ sentinels (ResponseValidator's
                // literal toMatchObject cannot, and resolvable relative paths would
                // otherwise fail on those sentinels).
                //--------------------------------------------
                if (!healCapture) {{
                    await ResponseValidator.validate(response, {{
                        status: Number(row.ExpectedStatus)
                    }});
                }}
                //--------------------------------------------
                // Smart Comparator
                //--------------------------------------------
                if (!healCapture && body && row.ExpectedFile) {{
                    const expectedFile = path.join(process.cwd(), row.ExpectedFile);
                    if (fs.existsSync(expectedFile)) {{
                        const expected = JSON.parse(fs.readFileSync(expectedFile, 'utf8'));
                        SmartComparator.compare(body, expected);
                    }}
                }}
                //--------------------------------------------
                // Contract Validation
                //--------------------------------------------
                if (!healCapture && body && row.ContractFile) {{
                    try {{
                        await ContractValidator.validate(row.ContractFile, row.Endpoint, row.Method, status, body);
                    }} catch (err: any) {{
                        if (err.message?.startsWith('No schema found')) {{
                            testInfo.annotations.push({{
                                type: 'Schema',
                                description: `No schema found for ${{row.Method}} ${{row.Endpoint}}`
                            }});
                        }} else {{
                            throw err;
                        }}
                    }}
                }}
                //--------------------------------------------
                // Extract Context
                //--------------------------------------------
                if (body && row.extractField && row.injectAs) {{
                    const value = ContextStore.extract(body, row.extractField);
                    if (value !== undefined && value !== null) ContextStore.set(row.injectAs, value);
                }}
                //--------------------------------------------
                // Cleanup
                //--------------------------------------------
                if (row.cleanupEndpoint) {{
                    const cleanupRequest = await RequestBuilder.build(
                        {{
                            endpoint: row.cleanupEndpoint,
                            method: row.cleanupMethod ?? 'DELETE',
                            headers: row.headers,
                            requestBody: undefined
                        }},
                        baseUrl,
                        auth
                    );
                    await client.send(cleanupRequest);
                }}
                //--------------------------------------------
                // Governed negative-matrix assertions
                //--------------------------------------------
                if (!healCapture && ['invalidJson', 'emptyPayload', 'missingMandatory', 'missingField', 'invalidField'].includes(row.PayloadMethod)) {{
                    expect(status).toBe(Number(row.ExpectedStatus));
                }}

                const acceptHeader = row.headers?.Accept ?? row.headers?.accept ?? row.Accept;
                const invalidAcceptHeaders = ['application/xml', 'text/html', 'text/plain', 'image/png', 'application/pdf'];
                if (!healCapture && acceptHeader && invalidAcceptHeaders.includes(acceptHeader)) {{
                    expect(status).toBe(Number(row.ExpectedStatus));
                }}

                if (!healCapture && ['OPTIONS', 'HEAD', 'TRACE'].includes(row.Method.toUpperCase())) {{
                    expect(status).toBe(Number(row.ExpectedStatus));
                }}

                if (!healCapture && (row.Endpoint.includes('invalid') || row.Endpoint.includes('notfound') || row.Endpoint.includes('404'))) {{
                    expect(status).toBe(404);
                }}
            }});
    }}
}});
'''

# ───────────────────────── main entry ─────────────────────────

def render_data_ts_xml(cfg, fields, create_method, root_tag='root') -> str:
    """XML twin of render_data_ts — builds XML string payloads from excel data."""
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    keys_arr = ', '.join(_js_str(k) for k, _ in fields)
    mandatory = cfg.get('mandatoryFields') or [k for k, _ in fields]
    lines_payload = '\n'.join(
        f"            `  <{_xml_tag(k)}>${{{_js_get(k)}}}</{_xml_tag(k)}>`," for k, _ in fields)
    lines_mand = '\n'.join(
        f"            `  <{_xml_tag(k)}>${{{_js_get(k)}}}</{_xml_tag(k)}>`," for k in mandatory
        if any(k == fk for fk, _ in fields))

    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

const FIELDS = [{keys_arr}];
const XML_HEADER = '<?xml version="1.0" encoding="UTF-8" ?>';

/** {cls} — XML payload builder generated by TestHub Automation Studio. */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    private wrap(lines: string[]): string {{
        return [XML_HEADER, '<{root_tag}>', ...lines, '</{root_tag}>'].join('\\n');
    }}

    async {create_method}(excelName: string, sheetName: string, testName: string): Promise<string> {{
        const data = await this.getData(excelName, sheetName, testName);
        return this.wrap([
{lines_payload}
        ]);
    }}

    async mandatoryOnly(excelName: string, sheetName: string, testName: string): Promise<string> {{
        const data = await this.getData(excelName, sheetName, testName);
        return this.wrap([
{lines_mand}
        ]);
    }}

    async emptyPayload(): Promise<string> {{
        return this.wrap([]);
    }}

    async missingField(excelName: string, sheetName: string, testName: string): Promise<string> {{
        const data = await this.getData(excelName, sheetName, testName);
        const lines: string[] = [];
        for (const f of FIELDS) {{
            // a blank excel cell means the element is intentionally omitted for this row
            if (data[f] !== undefined && data[f] !== null && data[f] !== '') {{
                lines.push(`  <${{f}}>${{data[f]}}</${{f}}>`);
            }}
        }}
        return this.wrap(lines);
    }}

    async invalidField(excelName: string, sheetName: string, testName: string): Promise<string> {{
        const data = await this.getData(excelName, sheetName, testName);
        return this.wrap(FIELDS.map(f => `  <${{f}}>${{data[f]}}</${{f}}>`));
    }}

    async invalidJson(): Promise<string> {{
        // malformed XML on purpose — unclosed root element
        return XML_HEADER + '\\n<{root_tag}><broken>';
    }}

    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string): Promise<any> {{
        switch (payloadMethod) {{
            case '{create_method}':
                return await this.{create_method}(excelName, sheetName, testName);
            case 'mandatoryOnly':
                return await this.mandatoryOnly(excelName, sheetName, testName);
            case 'emptyPayload':
                return await this.emptyPayload();
            case 'missingField':
                return await this.missingField(excelName, sheetName, testName);
            case 'invalidField':
                return await this.invalidField(excelName, sheetName, testName);
            case 'invalidJson':
                return await this.invalidJson();
            default:
                throw new Error(`Unknown Payload Method : ${{payloadMethod}}`);
        }}
    }}
}}
'''


def render_data_ts_mft(cfg, create_method) -> str:
    """
    MFT Zone builder — the ETL on-ramp / landing-zone transfer.
    Reads Website URL, Username, File Path from Excel; resolves the password
    from an ENV VAR reference at runtime (process.env[...]) so no secret is
    ever written into the generated asset. GET-only.
    """
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

/**
 * {cls} — MFT Zone transfer builder (ETL on-ramp / landing-zone step).
 * The test authenticates to the portal and drops a file into the landing
 * zone a downstream pipeline picks up from. GET-only.
 *
 * SECURITY: the password is NOT stored here. The Excel `PasswordRef` column
 * holds an environment-variable NAME (e.g. MFT_PASSWORD); the real secret is
 * read from process.env at run time and never committed.
 */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    async {create_method}(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        const passwordRef = data.PasswordRef;
        const password = passwordRef ? process.env[passwordRef] : undefined;
        if (passwordRef && !password) {{
            throw new Error(`MFT password env var '${{passwordRef}}' is not set in .env`);
        }}
        return {{
            websiteUrl: data.WebsiteUrl,
            username:   data.Username,
            password,                       // resolved from .env — never from the sheet
            filePath:   data.FilePath
        }};
    }}

    async missingCredentials(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ websiteUrl: data.WebsiteUrl, username: '', password: '', filePath: data.FilePath }};
    }}

    async missingFile(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        const password = data.PasswordRef ? process.env[data.PasswordRef] : undefined;
        return {{ websiteUrl: data.WebsiteUrl, username: data.Username, password, filePath: '' }};
    }}

    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string): Promise<any> {{
        switch (payloadMethod) {{
            case '{create_method}':      return await this.{create_method}(excelName, sheetName, testName);
            case 'missingCredentials':   return await this.missingCredentials(excelName, sheetName, testName);
            case 'missingFile':          return await this.missingFile(excelName, sheetName, testName);
            default: throw new Error(`Unknown Payload Method : ${{payloadMethod}}`);
        }}
    }}
}}
'''


def build_matrix_mft(cfg, create_method):
    """MFT Zone scenario matrix — transfer happy path + auth/file negatives. GET-only."""
    endpoint = cfg.get('endpoint') or '/'
    status   = str(cfg.get('expectedStatus') or '200')
    auth     = cfg.get('authType') or 'apikey'
    svc      = cfg.get('serviceName') or 'service'
    mft      = cfg.get('mft') or {}
    cols = ['TestName', 'Method', 'Endpoint', 'PayloadMethod',
            'WebsiteUrl', 'Username', 'PasswordRef', 'FilePath',
            'ExpectedStatus', 'authType', 'ContentType', 'Accept']

    def row(name, pm, st=status, url=None, user=None, pref=None, fp=None, m='GET', ep=None):
        return {'TestName': name, 'Method': m, 'Endpoint': endpoint if ep is None else ep, 'PayloadMethod': pm,
                'WebsiteUrl': mft.get('websiteUrl', '') if url is None else url,
                'Username': mft.get('username', '') if user is None else user,
                'PasswordRef': mft.get('passwordRef', '') if pref is None else pref,
                'FilePath': mft.get('filePath', '') if fp is None else fp,
                'ExpectedStatus': st, 'authType': auth,
                'ContentType': 'text/plain', 'Accept': 'application/json'}

    rows = [row(f'{_pascal(svc)} Happy Path', create_method)]
    if cfg.get('negative', True):
        rows.append(row('Invalid Credentials', 'missingCredentials', st='401', user='', pref=''))
        rows.append(row('Missing File', 'missingFile', st='400', fp=''))
        rows.append(row('Unreachable Website URL', create_method, st='404', url='https://invalid.invalid/nope'))
        rows.append(row('Invalid Endpoint', create_method, st='404', ep='/invalid' + endpoint))
        # MFT is GET-only: every non-GET method is unsupported (405)
        for m in ('PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'):
            rows.append(row(f'Unsupported {m}', create_method, m=m, st='405'))
    return cols, rows


def render_data_ts_form(cfg, fields, files, create_method, multipart=True) -> str:
    """
    Form twin of render_data_ts — emits the { fields, files } shape consumed by
    PayloadEncoder. The row's ContentType column selects multipart/form-data vs
    application/x-www-form-urlencoded serialisation; the same builder serves both.
    Files (multipart only) are streamed from disk at request time by the framework.
    """
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    keys_arr = ', '.join(_js_str(k) for k, _ in fields)
    mandatory = cfg.get('mandatoryFields') or [k for k, _ in fields]
    mand_arr = ', '.join(_js_str(k) for k in mandatory if any(k == fk for fk, _ in fields))

    files_ts = ',\n'.join(
        f"    {{ field: {_js_str(f['field'])}, path: {_js_str(f['path'])}, contentType: {_js_str(f['contentType'])} }}"
        for f in files)
    file_type = "{ field: string; path: string; contentType: string }[]"
    files_literal = f"[\n{files_ts}\n]" if files else "[]"

    kind = 'multipart/form-data' if multipart else 'application/x-www-form-urlencoded'
    invalid_body = ("'------malformed-multipart-no-boundary'" if multipart
                    else "'defect&missing=&=badpair'")

    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

const FIELDS = [{keys_arr}];
const MANDATORY = [{mand_arr}];
const FILES: {file_type} = {files_literal};

/**
 * {cls} — {kind} payload builder generated by TestHub Automation Studio.
 * Returns the {{ fields, files }} shape consumed by PayloadEncoder; the row's
 * ContentType column drives multipart vs urlencoded serialisation.
 */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    private pick(keys: string[], data: ExcelTestData): Record<string, any> {{
        const out: Record<string, any> = {{}};
        for (const k of keys) if (data[k] !== undefined) out[k] = data[k];
        return out;
    }}

    async {create_method}(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ fields: this.pick(FIELDS, data), files: FILES }};
    }}

    async mandatoryOnly(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ fields: this.pick(MANDATORY, data), files: FILES }};
    }}

    async emptyPayload(): Promise<Record<string, any>> {{
        return {{ fields: {{}}, files: [] }};
    }}

    async missingField(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        // a blank excel cell means the field is intentionally omitted for this row
        const keys = FIELDS.filter(f => data[f] !== undefined && data[f] !== null && data[f] !== '');
        return {{ fields: this.pick(keys, data), files: FILES }};
    }}

    async invalidField(excelName: string, sheetName: string, testName: string): Promise<Record<string, any>> {{
        const data = await this.getData(excelName, sheetName, testName);
        const payload = this.pick(FIELDS, data);
        if (data.InvalidField) payload[data.InvalidField] = data.InvalidValue ?? 'defect';
        return {{ fields: payload, files: FILES }};
    }}

    async invalidJson(): Promise<string> {{
        // malformed {kind} body on purpose — exercises the negative "invalid body" row
        return {invalid_body};
    }}

    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string): Promise<any> {{
        switch (payloadMethod) {{
            case '{create_method}':
                return await this.{create_method}(excelName, sheetName, testName);
            case 'mandatoryOnly':
                return await this.mandatoryOnly(excelName, sheetName, testName);
            case 'emptyPayload':
                return await this.emptyPayload();
            case 'missingField':
                return await this.missingField(excelName, sheetName, testName);
            case 'invalidField':
                return await this.invalidField(excelName, sheetName, testName);
            case 'invalidJson':
                return await this.invalidJson();
            default:
                throw new Error(`Unknown Payload Method : ${{payloadMethod}}`);
        }}
    }}
}}
'''


def render_data_ts_formdata(cfg, form_entries, create_method) -> str:
    """
    Multipart FORMDATA twin of render_data_ts_form — mirrors the corrected
    hand-written FormDataPayload contract (src/requestPayload/formExample/formData.data.ts):

      * each scenario method returns
            { payloadType: "FORMDATA", fields: [{ key, type, value, description }] }
      * build() splits that into { payloadType, body, files } for RequestBuilder /
        PayloadEncoder (text parts -> body, File parts -> files streamed from disk).

    Works for ANY field count: file_idx / text_idx are derived from the ordered
    `form_entries` (files-first, then scalars) and the methods iterate the numbered
    Key{i}/DropdownKey{i}/Value{i}/Description{i} excel columns 1..n.
    """
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    n = len(form_entries)
    all_idx  = list(range(1, n + 1))
    file_idx = [i for i, e in enumerate(form_entries, 1) if e.get('type') == 'File']
    text_idx = [i for i, e in enumerate(form_entries, 1) if e.get('type') != 'File']

    def arr(xs):
        return '[' + ', '.join(str(x) for x in xs) + ']'

    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

// Ordered field indices for the numbered excel columns (files-first, then text).
const ALL_IDX  = {arr(all_idx)};
const FILE_IDX = {arr(file_idx)};
const TEXT_IDX = {arr(text_idx)};

/**
 * {cls} — multipart/form-data (FORMDATA) payload builder generated by TestHub Automation Studio.
 * Each scenario returns {{ payloadType: "FORMDATA", fields: [{{ key, type, value, description }}] }};
 * build() splits that into {{ payloadType, body, files }} (text parts -> body, File parts -> files).
 */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    /** Build one field object from the numbered excel columns, with optional overrides. */
    private field(data: ExcelTestData, i: number, override: {{ type?: string; value?: string }} = {{}}) {{
        return {{
            key: data[`Key${{i}}`],
            type: override.type ?? data[`DropdownKey${{i}}`],
            value: override.value ?? data[`Value${{i}}`],
            description: data[`Description${{i}}`] || ""
        }};
    }}

    // Happy path — every configured part (files + text).
    async uploadFile(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ payloadType: "FORMDATA", fields: ALL_IDX.map(i => this.field(data, i)) }};
    }}

    // Text parts only.
    async textOnly(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ payloadType: "FORMDATA", fields: TEXT_IDX.map(i => this.field(data, i, {{ type: "Text" }})) }};
    }}

    // File parts only.
    async fileOnly(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ payloadType: "FORMDATA", fields: FILE_IDX.map(i => this.field(data, i, {{ type: "File" }})) }};
    }}

    // Empty multipart body.
    async emptyForm() {{
        return {{ payloadType: "FORMDATA", fields: [] as any[] }};
    }}

    // Drop the file part(s) — send the text part(s) only.
    async missingFile(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ payloadType: "FORMDATA", fields: TEXT_IDX.map(i => this.field(data, i, {{ type: "Text" }})) }};
    }}

    // Drop the text part(s) — send the file part(s) only.
    async missingText(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        return {{ payloadType: "FORMDATA", fields: FILE_IDX.map(i => this.field(data, i, {{ type: "File" }})) }};
    }}

    // File part(s) point at a non-existent path.
    async invalidFilePath(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        const fields = ALL_IDX.map(i =>
            FILE_IDX.includes(i)
                ? this.field(data, i, {{ type: "File", value: "test-data/files/does-not-exist.pdf" }})
                : this.field(data, i));
        return {{ payloadType: "FORMDATA", fields }};
    }}

    // File part(s) use a disallowed extension.
    async invalidExtension(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        const fields = ALL_IDX.map(i =>
            FILE_IDX.includes(i)
                ? this.field(data, i, {{ type: "File", value: "test-data/files/virus.exe" }})
                : this.field(data, i));
        return {{ payloadType: "FORMDATA", fields }};
    }}

    // Same shape as the happy path — the "large" fixture lives in the excel Value column.
    async largeFile(excelName: string, sheetName: string, testName: string) {{
        return await this.uploadFile(excelName, sheetName, testName);
    }}

    // File part(s) point at a zero-byte fixture.
    async emptyFile(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        const fields = ALL_IDX.map(i =>
            FILE_IDX.includes(i)
                ? this.field(data, i, {{ type: "File", value: "test-data/files/empty.txt" }})
                : this.field(data, i));
        return {{ payloadType: "FORMDATA", fields }};
    }}

    // "Duplicate" is a stateful server condition a single stateless request can't
    // express, so the contract mock honours a `simulateDuplicate` marker field.
    async duplicateUpload(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        const fields = [
            ...FILE_IDX.map(i => this.field(data, i, {{ type: "File" }})),
            {{ key: "simulateDuplicate", type: "Text", value: "true", description: "" }}
        ];
        return {{ payloadType: "FORMDATA", fields }};
    }}

    // Send every part, but override the `Email` text field with an invalid value
    // so the contract mock's email validation rejects the upload (400).
    async invalidEmail(excelName: string, sheetName: string, testName: string) {{
        const data = await this.getData(excelName, sheetName, testName);
        const fields = ALL_IDX.map(i => {{
            const key = data[`Key${{i}}`];
            return (typeof key === "string" && key.toLowerCase() === "email")
                ? this.field(data, i, {{ type: "Text", value: "not-an-email" }})
                : this.field(data, i);
        }});
        return {{ payloadType: "FORMDATA", fields }};
    }}

    // Convert framework payload to RequestBuilder / PayloadEncoder format.
    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string) {{
        let payload: any;
        switch (payloadMethod) {{
            // Scenario names that share the standard upload shape — intent lives in
            // the row's headers / auth / expected-status, not a new payload shape.
            case "{create_method}":
            case "uploadFile":
            case "uploadTxt":
            case "uploadPng":
            case "uploadZip":
            case "multipleFiles":
            case "invalidApiKey":
            case "uploadSpaces":
            case "uploadUnicode":
                payload = await this.uploadFile(excelName, sheetName, testName); break;
            case "invalidEmail":
                payload = await this.invalidEmail(excelName, sheetName, testName); break;
            case "emptyForm":
            case "emptyFormData":
                payload = await this.emptyForm(); break;
            case "textOnly":
                payload = await this.textOnly(excelName, sheetName, testName); break;
            case "fileOnly":
                payload = await this.fileOnly(excelName, sheetName, testName); break;
            case "missingFile":
                payload = await this.missingFile(excelName, sheetName, testName); break;
            case "missingText":
                payload = await this.missingText(excelName, sheetName, testName); break;
            case "invalidFilePath":
                payload = await this.invalidFilePath(excelName, sheetName, testName); break;
            case "invalidExtension":
                payload = await this.invalidExtension(excelName, sheetName, testName); break;
            case "largeFile":
                payload = await this.largeFile(excelName, sheetName, testName); break;
            case "emptyFile":
                payload = await this.emptyFile(excelName, sheetName, testName); break;
            case "duplicateUpload":
                payload = await this.duplicateUpload(excelName, sheetName, testName); break;
            default:
                throw new Error(`Unknown Payload Method: ${{payloadMethod}}`);
        }}

        const body: Record<string, any> = {{}};
        const files: any[] = [];

        for (const f of payload.fields ?? []) {{
            if (f.type === "File") {{
                files.push({{
                    field: f.key,
                    path: f.value,
                    filename: String(f.value).split(/[\\\\/]/).pop()
                }});
            }} else {{
                body[f.key] = f.value;
            }}
        }}

        return {{ payloadType: "FORMDATA", body, files }};
    }}
}}
'''


def build_matrix_form(cfg, form_entries, create_method):
    """
    FORMDATA (multipart) scenario matrix — numbered Key{{i}}/DropdownKey{{i}}/Value{{i}}/
    Description{{i}} columns + upload-shaped payload methods, for ANY field count.

    Expected statuses are STANDARDS-CORRECT: this suite runs against the strict
    multipart contract mock (uploadContractServer), which returns real rejection
    codes — 405 (non-POST), 401 (missing/invalid x-api-key), 406 (non-JSON
    Accept), 415 (non-multipart Content-Type), 413 (body > 1 MB), 409 (duplicate),
    400 (empty file part), else 201. This matches the rigour of the hand-written
    formExample suite (a bank-grade "catches real bugs" story), unlike the
    permissive reqres convention the JSON/XML/urlencoded/binary suites use.

    Payload-shape variants that are still legitimate uploads (textOnly/fileOnly/
    missingFile/missingText/invalidFilePath/invalidExtension) the mock accepts →
    201; only the genuine protocol violations reject with their real codes.
    """
    method   = (cfg.get('method') or 'POST').upper()
    endpoint = cfg.get('endpoint') or '/'
    status   = str(cfg.get('expectedStatus') or '201')
    auth     = cfg.get('authType') or 'apikey'
    ct       = cfg.get('contentType') or 'multipart/form-data'
    accept   = cfg.get('accept') or 'application/json'
    svc      = cfg.get('serviceName') or 'service'
    expected_file = cfg.get('expectedFileRel') or ''
    contract      = cfg.get('contractRel') or ''

    n = len(form_entries)
    file_idx = [i for i, e in enumerate(form_entries, 1) if e.get('type') == 'File']
    text_idx = [i for i, e in enumerate(form_entries, 1) if e.get('type') != 'File']

    num_cols = []
    for i in range(1, n + 1):
        num_cols += [f'Key{i}', f'DropdownKey{i}', f'Value{i}', f'Description{i}']
    cols = ['TestName', 'Method', 'Endpoint', 'PayloadMethod'] + num_cols + \
           ['ExpectedStatus', 'ExpectedFile', 'Contract', 'authType', 'ContentType', 'Accept']

    base = {}
    for i, e in enumerate(form_entries, 1):
        base[f'Key{i}']         = _cell(e.get('key'))
        base[f'DropdownKey{i}'] = e.get('type') or 'Text'
        base[f'Value{i}']       = _cell(e.get('value'))
        base[f'Description{i}']  = _cell(e.get('description'))

    def row(test, pm='uploadFile', m=method, ep=endpoint, st=status,
            ef='', ctr='', c_type=ct, acc=accept, auth_t=auth, overrides=None):
        r = {'TestName': test, 'Method': m, 'Endpoint': ep, 'PayloadMethod': pm,
             'ExpectedStatus': st, 'ExpectedFile': ef, 'Contract': ctr,
             'authType': auth_t, 'ContentType': c_type, 'Accept': acc}
        r.update(base)
        if overrides:
            r.update(overrides)           # per-row cell tweaks (e.g. Large File path)
        return r

    # Happy path row uses the reference's exact TestName so the whole sheet is
    # reproduced row-for-row (formData1's first row is "Upload PDF Happy Path").
    rows = [row('Upload PDF Happy Path', ef=expected_file, ctr=contract)]

    if not cfg.get('negative'):
        return cols, rows

    # ── formExample.xlsx / formData1 — 30 rows, verbatim (strict upload mock) ──
    # Rows 2-9: still-legitimate uploads the mock accepts → 201.
    rows.append(row('Upload Missing File', pm='missingFile'))                   # text parts only → 201
    rows.append(row('Upload Missing Email', pm='missingText'))                  # file part only → 201
    rows.append(row('Empty FormData', pm='emptyFormData'))                      # empty body → 201
    rows.append(row('Invalid File Path', pm='invalidFilePath'))                 # missing file part skipped → 201
    rows.append(row('Upload TXT File', pm='uploadTxt'))                         # 201
    rows.append(row('Upload PNG File', pm='uploadPng'))                         # 201
    rows.append(row('Upload ZIP File', pm='uploadZip'))                         # 201
    rows.append(row('Multiple Files', pm='multipleFiles'))                      # 201
    # Routing / protocol negatives — the strict mock returns real rejection codes.
    rows.append(row('Invalid Endpoint', ep='/invalid' + endpoint, st='404'))   # unknown path → 404
    for m in ('GET', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'):
        rows.append(row(f'Unsupported {m}', m=m, st='405'))                     # non-POST → 405
    for name, acc in INVALID_ACCEPTS:
        rows.append(row(name, acc=acc, st='406'))                              # non-JSON Accept → 406
    # Invalid Content Type: a non-multipart type survives to the wire → 415.
    rows.append(row('Invalid Content Type', c_type='application/json', st='415'))
    # Auth negatives — the strict mock enforces x-api-key.
    rows.append(row('Missing API Key', pm='uploadFile', auth_t='none',          st='401'))  # no key → 401
    rows.append(row('Invalid API Key', pm='invalidApiKey', auth_t='apikeyinvalid', st='401'))  # wrong key → 401
    # Body-content negatives.
    rows.append(row('Large File Upload', pm='largeFile', st='413',             # ~2 MB body → 413
                    overrides={f'Value{i}': 'test-data/files/largefile.zip' for i in file_idx}))
    rows.append(row('Empty File', pm='emptyFile', st='400'))                    # zero-byte file part → 400
    rows.append(row('Duplicate Upload', pm='duplicateUpload', st='409'))        # simulateDuplicate marker → 409
    rows.append(row('Invalid Email Format', pm='invalidEmail', st='400'))       # invalid Email field → 400
    rows.append(row('Upload Filename With Spaces', pm='uploadSpaces'))          # 201
    rows.append(row('Upload Unicode Filename', pm='uploadUnicode'))             # 201
    return cols, rows


def render_data_ts_binary(cfg, create_method, content_type='application/octet-stream') -> str:
    """
    Binary payload builder — the request body is a file streamed to a Buffer by
    PayloadEncoder (application/octet-stream, application/pdf, application/zip,
    image/*). The happy path returns the fixture path from the excel File column;
    negatives return an empty / corrupt / non-binary body.
    """
    cls = _pascal(cfg.get('serviceName') or cfg.get('assetName'))
    return f'''import {{ readTestDataFromExcel }} from '../../utils/excelUtils';

type ExcelTestData = Record<string, any>;

/**
 * {cls} — binary ({content_type}) payload builder generated by TestHub Automation Studio.
 * The happy path returns a filesystem path (read into a Buffer by PayloadEncoder);
 * negative rows return an empty, corrupt, or non-binary body.
 */
export default class {cls} {{
    private async getData(excelName: string, sheetName: string, testName: string): Promise<ExcelTestData> {{
        return await readTestDataFromExcel(excelName, sheetName, testName);
    }}

    async {create_method}(excelName: string, sheetName: string, testName: string): Promise<any> {{
        const data = await this.getData(excelName, sheetName, testName);
        return data.File; // path to the binary fixture — encoder reads it into a Buffer
    }}

    async emptyPayload(): Promise<any> {{
        return Buffer.alloc(0); // zero-length body
    }}

    async corruptBody(): Promise<any> {{
        return Buffer.alloc(0); // corrupt / unreadable payload — server rejects (400)
    }}

    async invalidJson(): Promise<any> {{
        return Buffer.alloc(0); // unreadable / non-binary payload — server rejects (400)
    }}

    async build(excelName: string, sheetName: string, testName: string, payloadMethod: string): Promise<any> {{
        switch (payloadMethod) {{
            case '{create_method}':
                return await this.{create_method}(excelName, sheetName, testName);
            case 'emptyPayload':
                return await this.emptyPayload();
            case 'corruptBody':
                return await this.corruptBody();
            case 'invalidJson':
                return await this.invalidJson();
            default:
                throw new Error(`Unknown Payload Method : ${{payloadMethod}}`);
        }}
    }}
}}
'''


def build_matrix_binary(cfg, create_method, binary_path):
    """
    Binary scenario matrix — reproduces binaryExample.xlsx / binary (31 rows)
    verbatim. Runs against the PERMISSIVE reqres mock (reqresContractServer) on a
    collection endpoint (/api/upload): every row is a real file upload (pm=create,
    a non-empty body), so the only non-201 codes are routing/method/auth:
    Invalid Endpoint → 404; GET → 200, PUT/PATCH → 404, DELETE/OPTIONS → 204,
    HEAD → 200; Missing API Key (authType none) → 403; everything else → 201.
    """
    endpoint = cfg.get('endpoint') or '/'
    auth     = cfg.get('authType') or 'apikey'
    accept   = cfg.get('accept') or 'application/json'
    expected_file = cfg.get('expectedFileRel') or ''
    contract      = cfg.get('contractRel') or ''

    cols = ['TestName', 'Method', 'Endpoint', 'PayloadMethod', 'File',
            'ExpectedStatus', 'ExpectedFile', 'Contract', 'authType', 'ContentType', 'Accept']

    def row(test, m='POST', ep=endpoint, pm=create_method, f=binary_path,
            st='201', ef='', ctr='', c_type='application/pdf', acc=accept, at=auth):
        return {'TestName': test, 'Method': m, 'Endpoint': ep, 'PayloadMethod': pm, 'File': f,
                'ExpectedStatus': st, 'ExpectedFile': ef, 'Contract': ctr,
                'authType': at, 'ContentType': c_type, 'Accept': acc}

    # 1-7: happy uploads (varied content types) — all 201.
    rows = [row('Upload PDF Happy Path', c_type='application/pdf', ef=expected_file, ctr=contract)]
    if not cfg.get('negative'):
        return cols, rows
    rows.append(row('Upload PNG Happy Path', c_type='image/png'))
    rows.append(row('Upload TXT Happy Path', c_type='text/plain'))
    rows.append(row('Upload ZIP Happy Path', c_type='application/zip'))
    rows.append(row('Upload Large File', c_type='application/pdf'))
    rows.append(row('Upload Empty File', c_type='application/pdf'))
    rows.append(row('Invalid File Path', f='test-data/files/does-not-exist.pdf', c_type='application/pdf'))
    # Routing / method negatives — codes follow the endpoint shape, not a
    # hard-coded guess. See _is_resource_endpoint.
    rows.append(row('Invalid Endpoint', ep='/invalid' + endpoint, st='404'))
    for m, st in _unsupported_verb_rows(endpoint):
        rows.append(row(f'Unsupported {m}', m=m, st=st))
    # Invalid Accept ("Invalid Header …") — the mock ignores Accept → 201.
    for name, acc in INVALID_ACCEPTS:
        rows.append(row(name, acc=acc))
    rows.append(row('Invalid Content Type', c_type='defect'))                   # non-json/binary CT → 201
    # Auth negatives — genuinely exercised. Missing/invalid credentials are 401
    # Unauthorized (the reference sheet's 403/201 were bugs: 403 is the wrong code
    # for missing auth, and the 201s came from unrecognised authType values that
    # never dropped the key).
    rows.append(row('Missing API Key', at='none', st='401'))                    # no key → 401
    rows.append(row('Invalid API Key', at='invalidApiKey', st='401'))           # wrong key → 401
    rows.append(row('Missing Authorization', at='none', st='401'))              # no credentials → 401
    # Remaining happy variants — all accepted (201).
    rows.append(row('Unsupported File Extension', c_type='application/octet-stream'))
    rows.append(row('Corrupted File', c_type='application/pdf'))
    rows.append(row('Upload Unicode Filename', c_type='application/pdf'))
    rows.append(row('Upload Special Characters Filename', c_type='application/pdf'))
    rows.append(row('Upload ReadOnly File', c_type='application/pdf'))
    rows.append(row('Upload Very Large File', c_type='application/zip'))
    rows.append(row('Upload Duplicate File', c_type='application/pdf'))
    rows.append(row('Upload Zero Byte File', c_type='application/octet-stream'))
    return cols, rows


def _is_resource_endpoint(endpoint: str) -> bool:
    """True for /users/2 or /users/{id} (a single resource), False for /users.

    This distinction decides what the "Unsupported <VERB>" rows must expect, and
    it is REST's own convention, not a quirk of the bundled mock:

        PUT/PATCH /users/2   -> updates that resource        -> 2xx
        PUT/PATCH /users     -> no such route on a collection -> 404/405

    It used to be hard-coded to the resource answer, with a comment saying so.
    That is correct for the pinned demo endpoints and wrong for roughly half of
    real ones: pointing the Studio at a collection endpoint shipped two rows
    that could never pass, and — worse, because nobody investigates a green
    run — pointing it at a resource endpoint while assuming a collection would
    have asserted 404 against a route that works, and called that a pass.

    Heuristic, deliberately conservative: the last segment identifies a
    resource when it is numeric, a {placeholder}/:param, or a UUID. Anything
    else reads as a collection, which is the commoner shape and the safer
    default — a false 404 expectation fails loudly, where a false 200
    expectation passes quietly.
    """
    tail = [s for s in str(endpoint or '').split('/') if s]
    if not tail:
        return False
    last = tail[-1]
    if last.isdigit():
        return True
    if (last.startswith('{') and last.endswith('}')) or last.startswith(':'):
        return True
    if re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}'
                    r'-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', last):
        return True
    return False


def _unsupported_verb_rows(endpoint: str) -> list[tuple[str, str]]:
    """(verb, expected status) for the Unsupported rows, per endpoint shape."""
    if _is_resource_endpoint(endpoint):
        return [('GET', '200'), ('PUT', '200'), ('PATCH', '200'),
                ('DELETE', '204'), ('OPTIONS', '204'), ('HEAD', '200')]
    return [('GET', '200'), ('PUT', '404'), ('PATCH', '404'),
            ('DELETE', '204'), ('OPTIONS', '204'), ('HEAD', '200')]


def _banner(asset: str, service: str) -> str:
    """Header prepended to every generated .ts asset.

    Serves two purposes, and the second is load-bearing:

    1. It tells a human reading the file that edits here are not durable.
    2. It is how generate() recognises its OWN previous output. The overwrite
       guard refuses to clobber anything lacking this marker, so without the
       banner every regenerate would be blocked as if a human had written the
       file. The API path had no header at all until the guard went in.

    Kept deliberately short — it sits above the imports in a file testers read.
    """
    return (f'/** {engines_base.GENERATED_MARKER} Automation Studio — '
            f'{asset} · {service}.\n'
            f' *  Regenerating replaces this file. Put durable edits elsewhere. */\n')


def generate(payload: dict) -> dict:
    """
    payload: everything the frontend sends — form fields + paths.
    Writes assets to disk. Returns manifest of written files.
    """
    asset   = _safe_name(payload.get('assetName'))
    service = _safe_name(payload.get('serviceName'))
    method  = (payload.get('method') or 'GET').upper()

    paths = payload.get('paths') or {}
    p_req  = Path(paths.get('request')  or 'src/requestPayload')
    p_test = Path(paths.get('spec')     or 'src/tests')
    p_xls  = Path(paths.get('excel')    or 'test-data/excel')
    p_resp = Path(paths.get('response') or 'test-data/json')
    p_raml = Path(paths.get('raml')     or 'test-data/raml')

    # payload fields — lenient parse, duplicate keys renamed Field, Field_1 …
    fmt = (payload.get('bodyFormat') or 'JSON').lower()
    # normalise form aliases to two canonical formats
    if fmt in ('multipart', 'multipart/form-data', 'form-data'):
        fmt = 'form'
    elif fmt in ('x-www-form-urlencoded', 'application/x-www-form-urlencoded'):
        fmt = 'urlencoded'
    elif fmt in ('binary', 'octet-stream', 'application/octet-stream'):
        fmt = 'binary'
    elif fmt in ('mft', 'mft zone', 'mftzone'):
        fmt = 'mft'
    form_formats = {'form', 'urlencoded'}
    multipart = fmt == 'form'
    form_files = []
    form_entries = []                           # ordered multipart parts: files-first, then scalars
    binary_path, binary_ct = 'test-data/files/sample.pdf', 'application/octet-stream'
    fields, params, xml_root = [], None, 'root'
    mft_cfg = {}
    body_methods = {'POST', 'PUT', 'PATCH', 'DELETE'}
    raw_payload = payload.get('requestPayload') or ''
    if fmt not in form_formats and fmt not in ('xml', 'binary') and raw_payload.lstrip().startswith('<'):
        fmt = 'xml'                             # tolerate a missed toggle
    if fmt == 'binary':
        # Frontend sends binary as a bare file-path string; also tolerate a
        # JSON spec { file, type } for hand-editors.
        rp = (raw_payload or '').strip()
        if rp.startswith('{') or rp.startswith('['):
            pairs = form_field_parse(rp)
            if pairs:
                _sc, bfiles = form_split(pairs)
                if bfiles:
                    binary_path = bfiles[0]['path']
                    binary_ct = bfiles[0]['contentType']
        elif rp:
            binary_path = rp                    # bare path from the Studio field
        # infer a sensible content-type from the extension if header didn't set one
        ext = binary_path.rsplit('.', 1)[-1].lower() if '.' in binary_path else ''
        binary_ct = {'pdf': 'application/pdf', 'zip': 'application/zip',
                     'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'
                     }.get(ext, binary_ct)
    elif fmt in form_formats:
        # Robust: accepts {fields,files} object, its JSON string, legacy nested,
        # or a flat object — never trips on the frontend's table structure.
        scalars, form_files = normalize_form_payload(payload)
        if not multipart:
            form_files = []                    # urlencoded carries no files
        if multipart:
            # Ordered multipart parts consumed by the FORMDATA renderer + matrix.
            for f in form_files:
                form_entries.append({'key': f['field'], 'type': 'File',
                                     'value': f['path'], 'description': ''})
            for k, v in scalars:
                form_entries.append({'key': k, 'type': 'Text',
                                     'value': _cell(v), 'description': ''})
        if method in body_methods or payload.get('getBody'):
            fields = scalars
        else:
            params = dict(scalars)
    elif fmt == 'xml':
        parsed = xml_field_parse(raw_payload)
        if parsed:
            pairs, xml_root = parsed
            if method in body_methods or payload.get('getBody'):
                fields = pairs
            else:
                params = dict(pairs)
    elif fmt == 'mft':
        # MFT Zone: 4 fields, GET-only. Password is stored as an ENV VAR REFERENCE
        # (a name like MFT_PASSWORD), never the literal secret.
        method = 'GET'                          # force GET regardless of input
        mft = payload.get('mftFields')
        if not isinstance(mft, dict):
            raw = payload.get('requestPayload') or ''
            try:
                mft = json.loads(raw) if raw.strip().startswith('{') else {}
            except (json.JSONDecodeError, AttributeError):
                mft = {}
        mft_cfg = {
            'websiteUrl':  (mft.get('websiteUrl') or '').strip(),
            'username':    (mft.get('username') or '').strip(),
            'passwordRef': (mft.get('passwordRef') or mft.get('password') or '').strip(),
            'filePath':    (mft.get('filePath') or '').strip(),
        }
    else:
        parsed = lenient_json_parse(raw_payload)
        if parsed:
            pairs, _orig = parsed
            if method in body_methods or payload.get('getBody'):
                fields = pairs                  # GET-with-body supported
            else:
                params = dict(pairs)            # GET without body → params

    # explicit params field (if the frontend sends one) wins for GET
    if payload.get('queryParams'):
        qp = lenient_json_parse(payload['queryParams'])
        if qp:
            params = dict(qp[0])

    create_method = 'create' + _pascal(service)

    expected_raw = (payload.get('expectedResponse') or '').strip()
    expected_out = None                     # text to write to the expected file
    if expected_raw:
        if fmt == 'xml' or expected_raw.startswith('<'):
            if xml_field_parse(expected_raw):           # validate well-formed
                expected_out = expected_raw
        else:
            ep = lenient_json_parse(expected_raw)
            if ep is not None:
                expected_out = json.dumps(dict(ep[0]), indent=4)

    resp_ext  = 'xml' if (fmt == 'xml' or expected_raw.startswith('<')) else 'json'
    resp_dir  = p_resp / asset
    resp_file = resp_dir / f'{service}.{resp_ext}'
    expected_rel = str(resp_file).replace('\\', '/') if expected_out is not None else ''

    # Content-Type is the request wire format; Accept is the *response* format.
    # Form/urlencoded requests still receive JSON responses, so Accept stays JSON.
    default_ct = {
        'xml': 'application/xml',
        'form': 'multipart/form-data',
        'urlencoded': 'application/x-www-form-urlencoded',
        'binary': binary_ct,
    }.get(fmt, 'application/json')
    # Accept is the *response* format. Every strict/upload/reqres mock replies in
    # JSON, so Accept stays application/json for all wire formats (including XML,
    # whose request body is XML but whose response is JSON) — a non-JSON Accept is
    # then a genuine 406 negative in the matrix.
    default_accept = 'application/json'
    # ── RAML DataType (optional) ─────────────────────────────────────────
    # Drives the negative-matrix expected codes and is saved as evidence.
    # Absent, nothing here changes and generation is byte-identical.
    raml_text = (payload.get('raml') or '').strip()
    raml_spec = None
    raml_out = None
    if raml_text:
        try:
            raml_spec = parse_raml_datatype(raml_text)
        except ValueError as exc:
            return {'ok': False, 'error': f'RAML: {exc}'}
        # Compare the RAML against the sample request payload (JSON bodies).
        # A payload that contradicts its own contract is blocked here rather
        # than silently turned into a sheet.
        if fmt not in ('xml',) and raw_payload.strip():
            try:
                _payload_obj = json.loads(raw_payload)
            except Exception:
                _payload_obj = None
            if isinstance(_payload_obj, dict):
                _errs = raml_conformance_errors(raml_spec, _payload_obj)
                if _errs:
                    return {'ok': False,
                            'error': 'RAML does not match the request payload: '
                                     + '; '.join(_errs)}
        raml_out = raml_text if raml_text.endswith('\n') else raml_text + '\n'

    raml_dir = p_raml / asset
    raml_file = raml_dir / f'{service}.raml'
    raml_rel = str(raml_file).replace('\\', '/') if raml_out is not None else ''

    cfg = {
        'assetName': asset,
        'serviceName': service,
        'ramlSpec': raml_spec,          # None unless a RAML DataType was supplied
        'ramlFileRel': raml_rel,
        'method': method,
        'bodyFormat': fmt,
        # internal / external endpoint group -> the row's Service column
        'endpointType': (payload.get('endpointType') or '').strip().lower(),
        'endpoint': payload.get('endpoint') or '/',
        'expectedStatus': payload.get('expectedStatus') or '200',
        'authType': payload.get('authType') or 'apikey',
        'contentType': (payload.get('headers') or {}).get('Content-Type')
                       or (payload.get('headers') or {}).get('ContentType')
                       or default_ct,
        'accept': (payload.get('headers') or {}).get('Accept') or default_accept,
        'negative': payload.get('negative', True),
        'params': params,
        'expectedFileRel': expected_rel,
        'contractRel': payload.get('contract') or '',
        'mandatoryFields': payload.get('mandatoryFields'),
        # Request-contract required fields — every body field is required unless
        # the caller narrows it via mandatoryFields. Drives the strict mock's
        # missing-required-field (400) validation for json/xml/urlencoded.
        # RAML, when present, defines which fields are required; otherwise the
        # prior default (all fields required unless narrowed by mandatoryFields)
        # is preserved unchanged.
        'requiredFields': ([n for n, p in raml_spec.items() if p['required']]
                           if raml_spec
                           else payload.get('mandatoryFields') or [k for k, _ in fields]),
        'mft': mft_cfg,
        'overwrite': payload.get('overwrite'),      # explicit human override
    }

    written = []
    timings = {}                                        # per-asset generation time (seconds)

    # ── overwrite guard ───────────────────────────────────────────────────
    # The API path deliberately stayed byte-for-byte identical while the
    # accelerator was in pilot. This is a considered exception: without it,
    # regenerating destroyed hand-edited specs silently and still reported
    # success, and the API engine is the MOST used, so it is where the loss
    # actually happens. Checked before anything is written, so a refusal
    # leaves the tree untouched.
    #
    # The .ts assets are the ones humans edit. The .xlsx matrix is data the
    # Studio owns outright and is intentionally not guarded — treating it as
    # precious would block every ordinary regenerate.
    WouldClobber, _is_ours = engines_base.WouldClobber, engines_base._is_ours

    _data_file = (p_req / asset) / f'{service}.data.ts'
    _test_file = (p_test / asset) / f'{service}.test.ts'
    if not cfg.get('overwrite'):
        _clobber = [str(f) for f in (_data_file, _test_file)
                    if f.exists() and f.is_file() and not _is_ours(f)]
        if _clobber:
            raise WouldClobber(sorted(_clobber))

    # 1 — request payload builder  <request>/<asset>/<service>.data.ts
    _t = _perf.perf_counter()
    data_dir = p_req / asset
    data_dir.mkdir(parents=True, exist_ok=True)         # reuse, never duplicate
    data_file = data_dir / f'{service}.data.ts'
    if fmt == 'binary':
        _body = render_data_ts_binary(cfg, create_method, binary_ct)
    elif fmt == 'mft':
        _body = render_data_ts_mft(cfg, create_method)
    elif fmt == 'xml' and fields:
        _body = render_data_ts_xml(cfg, fields, create_method, xml_root)
    elif fmt == 'form' and form_entries:
        _body = render_data_ts_formdata(cfg, form_entries, create_method)
    elif fmt in form_formats and fields:
        _body = render_data_ts_form(cfg, fields, form_files, create_method, multipart)
    else:
        _body = render_data_ts(cfg, fields, create_method)
    data_file.write_text(_banner(asset, service) + _body, encoding='utf-8')
    written.append(str(data_file))
    timings[str(data_file)] = round(_perf.perf_counter() - _t, 3)

    # 2 — test spec  <spec>/<asset>/<service>.test.ts
    _t = _perf.perf_counter()
    test_dir = p_test / asset
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / f'{service}.test.ts'
    test_file.write_text(
        _banner(asset, service)
        + render_test_ts(cfg, asset, service, f'{asset}.xlsx', bool(fields) or bool(form_entries) or fmt in ('binary', 'mft'), bool(params)),
        encoding='utf-8')
    # Opt-in spec obfuscation. OFF by default so the generated spec stays a
    # readable, editable asset (the deployment brief requires QA to read what
    # the Studio produces). A client that wants the integration spec hidden
    # sets THUB_OBFUSCATE_SPEC=1 deployment-wide; the Excel test data, payload
    # data and reports stay readable regardless. Like all of this, it raises
    # the cost of reading, it is not secrecy.
    if os.environ.get('THUB_OBFUSCATE_SPEC') == '1':
        _obfuscate_spec(test_file)
    written.append(str(test_file))
    timings[str(test_file)] = round(_perf.perf_counter() - _t, 3)

    # 3 — excel matrix  <excel>/<asset>.xlsx, sheet <service>
    _t = _perf.perf_counter()
    if fmt == 'binary':
        cols, rows = build_matrix_binary(cfg, create_method, binary_path)
    elif fmt == 'mft':
        cols, rows = build_matrix_mft(cfg, create_method)
    elif fmt == 'form' and form_entries:
        cols, rows = build_matrix_form(cfg, form_entries, create_method)
    else:
        cols, rows = build_matrix(cfg, fields, create_method)
    # Endpoint type (internal / external) becomes a `Service` column every row
    # in this sheet shares. The emitted spec resolves it with
    # Config.getServiceUrl(row.Service), which maps it to the internal/external
    # base URL for the selected environment. Left blank, getServiceUrl falls
    # back to baseUrl — the offline example behaviour.
    endpoint_type = (cfg.get('endpointType') or '').strip().lower()
    if not any(c.lower() == 'service' for c in cols):
        cols = cols + ['Service']
    for _r in rows:
        _r['Service'] = endpoint_type
    xls_file = p_xls / f'{asset}.xlsx'
    write_excel(xls_file, service, cols, rows)
    written.append(str(xls_file))
    timings[str(xls_file)] = round(_perf.perf_counter() - _t, 3)

    # 4 — expected response  <response>/<asset>/<service>.(json|xml)
    if expected_out is not None:
        _t = _perf.perf_counter()
        resp_dir.mkdir(parents=True, exist_ok=True)
        resp_file.write_text(expected_out, encoding='utf-8')
        written.append(str(resp_file))
        timings[str(resp_file)] = round(_perf.perf_counter() - _t, 3)

    # 5 — RAML evidence  <raml>/<asset>/<service>.raml (only when supplied),
    # saved the same way as the expected response, in RAML format.
    if raml_out is not None:
        _t = _perf.perf_counter()
        raml_dir.mkdir(parents=True, exist_ok=True)
        raml_file.write_text(raml_out, encoding='utf-8')
        written.append(str(raml_file))
        timings[str(raml_file)] = round(_perf.perf_counter() - _t, 3)

    total_time = round(sum(timings.values()), 3)
    return {'ok': True, 'files': written, 'rows': len(rows), 'sheet': service,
            'bodyFormat': fmt, 'timings': timings, 'totalTime': total_time}
