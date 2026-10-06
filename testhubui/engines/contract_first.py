"""
TestHub Automation Studio — Contract & Requirements Assurance engine.

Every other engine in this repo turns intent into tests. This one asks whether
the intent is sound enough to test at all, and that inversion is the point.

The failure it exists to prevent: a suite generated from the API design artifact
(RAML/OpenAPI) inherits the designer's mistakes. Every test passes, the report
is green, and the API still does not do what the business asked for — because
the design was the oracle, and the design was wrong. A green suite built on a
bad oracle is worse than no suite, because it is trusted.

So the oracle here is the REQUIREMENT — the Solution Design Document the
implementation partner produces, and the C4E API specification behind it — and
the design artifact is a candidate to be validated against it.
Four things can be true of any field:

    covered     required by the business and correctly declared in the design
    gap         required by the business, absent from the design
    conflict    present in both, but they disagree (optionality, type)
    undeclared  in the design, traceable to no requirement

The last three are not test cases. They are QUERIES — questions someone must
answer before automation is honest work. This engine emits them as a standard
query log, and computes requirement coverage rather than estimating it, so
"the SDD gives us 55% of what we need" becomes a number per API instead of a
recollection.

Deliberately dependency-free: CI installs flask/openpyxl/pytest only, so the
design artifact is read with a tolerant indentation scanner rather than a YAML
parser. It handles the RAML 1.0 and OpenAPI shapes the team actually writes;
anything it cannot read is reported as unreadable rather than silently treated
as an empty contract, which would score every requirement as a gap.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .base import ACCEL, SPEC_DIR_DEFAULT, Assets, Row, field, register, section

# One query log row per non-covered field. Severity drives the order a reviewer
# works through them: a conflict is worse than a gap, because a gap is visible
# and a conflict looks like agreement.
SEVERITY = {'conflict': 1, 'gap': 2, 'misplaced': 3, 'undeclared': 4, 'covered': 9}

_TRUE = {'true', 'yes', 'required', 'mandatory', 'y', '1'}


def _lines(raw) -> list[str]:
    return [ln.strip() for ln in str(raw or '').splitlines() if ln.strip()]


def _js(s) -> str:
    return json.dumps(str(s))


def _safe(s: str) -> str:
    return ''.join(c for c in str(s or '').strip() if c.isalnum() or c in '-_') or 'asset'


def parse_requirements(raw) -> list[dict]:
    """`field | mandatory|optional | type | business rule` -> requirement rows.

    Only the field name is compulsory; the rest degrade sensibly, because a
    half-specified requirement is exactly the input this engine exists to
    handle. A requirement with no stated optionality is itself a query.
    """
    out = []
    for line in _lines(raw):
        parts = [p.strip() for p in line.split('|')]
        name = parts[0]
        if not name or name.startswith('#'):
            continue
        stated = parts[1].lower() if len(parts) > 1 and parts[1] else ''
        out.append({
            'field': name,
            'mandatory': stated in _TRUE if stated else None,   # None = unstated
            'type': (parts[2].strip().lower() if len(parts) > 2 and parts[2] else ''),
            'rule': (parts[3] if len(parts) > 3 else ''),
        })
    return out


_STATUS = re.compile(r"^['\"]?(\d{3})['\"]?\s*:\s*$")


def parse_error_responses(raw) -> tuple[dict[str, str], str]:
    """Extract declared response statuses, and the body type each carries, from
    a RAML trait.

    Which statuses return the error envelope is declared in a `traits:` block and
    applied to methods with `is: [standardErrors]` — so an engine that asks the
    tester to retype them is asking for the one thing already written down, and
    inviting the transcription error the whole exercise exists to catch.

    Reads all three shapes the team will paste:

        traits:                    #%RAML 1.0 Trait      /accounts:
          standardErrors:          responses:              get:
            responses:               400:                    responses:
              400:                     body:                   404:
                body:                    application/json:       body:
                  application/json:        type: Error             application/json:
                    type: Error                                      type: Error

    Returns (status -> body type, note). Success statuses are kept too: a 200
    declared alongside the errors is how you tell a trait from a whole method.
    """
    text = str(raw or '')
    if not text.strip():
        return {}, ''

    found: dict[str, str] = {}
    in_responses = False
    responses_indent = -1
    current: tuple[str, int] | None = None

    for line in text.splitlines():
        if not line.strip() or line.strip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if re.match(r'^responses\s*:\s*$', stripped):
            in_responses, responses_indent, current = True, indent, None
            continue
        if not in_responses:
            continue
        # A sibling or shallower key ends the block — but not the status keys
        # themselves, which sit one level in.
        if indent <= responses_indent:
            in_responses, current = False, None
            continue

        status = _STATUS.match(stripped)
        if status and (current is None or indent <= current[1]):
            found[status.group(1)] = ''
            current = (status.group(1), indent)
            continue
        if current:
            body_type = re.match(r'^type\s*:\s*(.+?)\s*$', stripped)
            if body_type and not found[current[0]]:
                found[current[0]] = body_type.group(1).strip().strip('"\'')

    if not found:
        return {}, ('Trait supplied but no response statuses could be read from it. Expected a '
                    '`responses:` block with status keys. Treating this as unreadable rather than '
                    'as a trait that declares no errors.')
    return found, ''


def parse_design(raw) -> tuple[dict[str, dict], str]:
    """Extract declared fields from a RAML/OpenAPI fragment.

    Returns (fields, note). `note` is non-empty when nothing could be read —
    the caller must surface that rather than proceeding, because an unreadable
    artifact and an empty artifact produce identical gap counts and mean
    completely different things.

    Handles the two shapes in real use:

        properties:              # RAML 1.0 and OpenAPI both
          accountNumber:
            type: string
            required: true       # RAML style

        required:                # OpenAPI style, a sibling list
          - accountNumber
    """
    text = str(raw or '')
    if not text.strip():
        return {}, 'No design artifact supplied.'

    fields: dict[str, dict] = {}
    required_list: set[str] = set()
    in_properties = False
    in_required_list = False
    prop_indent = None
    current = None

    for line in text.splitlines():
        if not line.strip() or line.strip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if re.match(r'^required\s*:\s*$', stripped):
            in_required_list, in_properties = True, False
            continue
        if in_required_list:
            item = re.match(r'^-\s*(.+?)\s*$', stripped)
            if item:
                required_list.add(item.group(1).strip().strip('"\''))
                continue
            in_required_list = False

        if re.match(r'^properties\s*:\s*$', stripped):
            in_properties, prop_indent, current = True, indent, None
            continue

        if in_properties:
            if indent <= prop_indent:
                in_properties = False
            else:
                key = re.match(r'^([A-Za-z_][\w\-]*)\s*:\s*$', stripped)
                if key and (current is None or indent <= current[1]):
                    name = key.group(1)
                    fields[name] = {'field': name, 'declaredRequired': None, 'type': ''}
                    current = (name, indent)
                    continue
                if current:
                    kv = re.match(r'^(type|required)\s*:\s*(.+?)\s*$', stripped)
                    if kv:
                        prop, value = kv.group(1), kv.group(2).strip().strip('"\'')
                        if prop == 'type':
                            fields[current[0]]['type'] = value.lower()
                        else:
                            fields[current[0]]['declaredRequired'] = value.lower() in _TRUE

    for name in required_list:
        if name in fields:
            fields[name]['declaredRequired'] = True

    if not fields:
        return {}, ('Design artifact supplied but no fields could be read from it. Expected a '
                    '`properties:` block (RAML 1.0 or OpenAPI). A C4E root RAML resolves its types '
                    'through `!include` and carries none inline — paste the DataType fragment it '
                    'points at instead. Treating this as unreadable rather than empty: an '
                    'unreadable artifact and a contract with no fields score identically and mean '
                    'completely different things.')
    return fields, ''


class ContractFirstEngine:
    id = 'contract'
    title = 'Contract & Requirements Assurance'
    emits_assets = True
    can_execute = False        # emits a query log + contract suite; the suite runs via the API engine

    def preflight(self) -> tuple[bool, str]:
        return True, ('Compares the design artifact against the stated requirement and emits a '
                      'query log plus a contract suite. Runs offline — no endpoint needed until '
                      'the designers publish a mock.')

    def schema(self):
        return [
            section('Identity', [
                field('assetName', 'Asset Name', required=True, placeholder='accounts'),
                field('serviceName', 'Service Name', required=True, placeholder='retail-banking'),
                field('requirementRef', 'Requirement reference', width='full', required=True,
                      placeholder='SDD §4.1 — Accounts API v2 / C4E Confluence',
                      hint='Where the SOURCE OF TRUTH lives. Not the RAML.'),
            ]),
            section('Mandatory requirements — from the SDD, not the RAML', [
                field('requirements', 'Requirements', 'textarea', width='full', required=True,
                      placeholder=('accountNumber | mandatory | string | 11 digits, matches customer record\n'
                                   'balance | mandatory | number | ZAR, 2 decimal places\n'
                                   'nickname | optional | string |'),
                      hint='One per line:  field | mandatory|optional | type | business rule. '
                           'Leave optionality blank if the SDD does not say — that becomes a query.'),
                field('unspecifiedElsewhere', 'Detail known to live elsewhere', 'textarea', width='full',
                      placeholder='branchCode — field-level rules are in the C4E interface spec, not the SDD',
                      hint='One per line:  field — where the detail actually lives. Marks a gap as '
                           'MISPLACED rather than unspecified.'),
            ], note='This is the oracle. If it is thin, the query log will say so — that is the '
                    'engine working, not failing. But an SDD is a solution-level document: some '
                    'field detail was never meant to be in it, and a gap someone can resolve by '
                    'opening another document is a different question from one nobody has answered.'),
            section('Error contract — the half a C4E governs hardest', [
                field('errorEnvelope', 'Error envelope required by the SDD', 'textarea', width='full',
                      placeholder=('code | mandatory | string | canonical error code\n'
                                   'message | mandatory | string | human-readable, no PII\n'
                                   'correlationId | mandatory | string | echoes the request header'),
                      hint='Same format as the requirements above. In a bank this shape is usually '
                           'fixed across every API by a C4E library, so it is the same on all of them.'),
                field('errorDesignArtifact', 'Error DataType fragment', 'textarea', width='full',
                      placeholder=('properties:\n'
                                   '  code:\n'
                                   '    type: string\n'
                                   '    required: true'),
                      hint='The Error type the RAML !includes. Validated against the envelope above '
                           'exactly as the success body is validated against the requirements.'),
                field('errorStatuses', 'Statuses the SDD requires', default='400,404,500',
                      hint='Comma-separated, from the SDD. Compared against what the trait actually '
                           'declares — a disagreement is a query like any other.'),
                field('errorTrait', 'RAML trait / responses block', 'textarea', width='full',
                      placeholder=('responses:\n'
                                   '  400:\n'
                                   '    body:\n'
                                   '      application/json:\n'
                                   '        type: Error'),
                      hint='Paste the trait that applies the error responses (or the method\'s own '
                           'responses block). The statuses are read from it rather than retyped — '
                           'retyping the one thing already written down invites the transcription '
                           'error this engine exists to catch.'),
                field('errorTrigger', 'Request that provokes an error', width='full',
                      placeholder='/v1/accounts/does-not-exist',
                      hint='Optional path or query that returns a non-2xx. Without it the error '
                           'assertions are emitted as pending rather than silently skipped.'),
            ], note='Success-path contract testing passes while every error response is unverified. '
                    'The error envelope is often the more governed half and the less tested one.'),
            section('Design artifact — the candidate to validate', [
                field('designArtifact', 'RAML / OpenAPI fragment', 'textarea', width='full',
                      placeholder=('properties:\n'
                                   '  accountNumber:\n'
                                   '    type: string\n'
                                   '    required: true\n'
                                   '  balance:\n'
                                   '    type: number'),
                      hint='Paste the response body schema — the RAML DataType fragment (the file a '
                           '!include points at), not the root RAML. A C4E root RAML keeps its types '
                           'in separate files, so pasting it yields nothing to compare and the '
                           'engine will say so rather than scoring every field as a gap.'),
                field('mockEndpoint', 'Mock endpoint (when published)', width='full',
                      placeholder='https://mocksvc.mulesoft.com/.../accounts',
                      hint='Optional. Scripts are written before the mock exists so they run the '
                           'moment it does.'),
            ]),
        ]

    def build_matrix(self, cfg: dict) -> list[Row]:
        # `field — where it actually lives`. An SDD is a solution-level document,
        # so some field detail was never meant to be in it. A gap someone can
        # close by opening the interface spec is a different question from one
        # nobody has answered, and sending both to the same queue wastes a
        # designer's time on questions that already have answers.
        elsewhere = {}
        for line in _lines(cfg.get('unspecifiedElsewhere')):
            name, _, where = line.partition('—')
            if not where:
                name, _, where = line.partition('-')
            if name.strip():
                elsewhere[name.strip()] = where.strip()

        requirements = parse_requirements(cfg.get('requirements'))
        if not requirements:
            raise ValueError('At least one requirement is needed — the specification is the oracle.')
        declared, note = parse_design(cfg.get('designArtifact'))

        rows: list[Row] = []
        seen = set()
        for req in requirements:
            name = req['field']
            seen.add(name)
            design = declared.get(name)
            if design is None:
                if name in elsewhere:
                    kind = 'misplaced'
                    detail = ('Absent from the SDD and from the design artifact, but the detail is '
                              f'held elsewhere: {elsewhere[name]}. Retrieve it before raising a query — '
                              'this one already has an answer.')
                else:
                    kind, detail = 'gap', 'Required by the specification; absent from the design artifact.'
            else:
                mismatches = []
                if req['mandatory'] is True and design['declaredRequired'] is False:
                    mismatches.append('specification says mandatory, design declares it optional')
                if req['mandatory'] is None:
                    mismatches.append('specification does not state whether this is mandatory')
                if req['type'] and design['type'] and req['type'] != design['type']:
                    mismatches.append(f"type differs — specification {req['type']}, design {design['type']}")
                if mismatches:
                    kind, detail = 'conflict', '; '.join(mismatches)
                else:
                    kind, detail = 'covered', 'Design matches the specification.'
            rows.append(Row(name=name, kind=kind, detail=detail, data={**req, 'design': design}))

        # Fields the designer invented. Each is a question: either the spec is
        # incomplete or the design has scope nobody asked for. Both need answering.
        for name, design in sorted(declared.items()):
            if name in seen:
                continue
            rows.append(Row(
                name=name, kind='undeclared',
                detail='Declared in the design artifact; traceable to no stated requirement.',
                data={'field': name, 'mandatory': None, 'type': design['type'],
                      'rule': '', 'design': design}))

        if note:
            rows.append(Row(name='(design artifact)', kind='unreadable', detail=note,
                            data={'field': '(design artifact)', 'design': None}))

        # The error contract, resolved the same four ways as the success body.
        # Same comparison, different scope — reusing it rather than inventing a
        # second vocabulary keeps the query log readable as one list.
        error_reqs = parse_requirements(cfg.get('errorEnvelope'))
        if error_reqs:
            error_declared, error_note = parse_design(cfg.get('errorDesignArtifact'))
            for req in error_reqs:
                name = req['field']
                design = error_declared.get(name)
                if design is None:
                    kind, detail = 'gap', ('Required in the error envelope; absent from the Error '
                                           'type the RAML declares.')
                else:
                    problems = []
                    if req['mandatory'] is True and design['declaredRequired'] is False:
                        problems.append('SDD says mandatory, Error type declares it optional')
                    if req['type'] and design['type'] and req['type'] != design['type']:
                        problems.append(f"type differs — SDD {req['type']}, design {design['type']}")
                    kind, detail = ('conflict', '; '.join(problems)) if problems else \
                        ('covered', 'Error type matches the SDD.')
                rows.append(Row(name=f'error.{name}', kind=kind, detail=detail,
                                data={**req, 'design': design, 'scope': 'error'}))
            # Which statuses carry the envelope: what the SDD requires versus what
            # the trait declares. Same four states as any other comparison.
            declared_statuses, trait_note = parse_error_responses(cfg.get('errorTrait'))
            stated = [s.strip() for s in str(cfg.get('errorStatuses') or '').split(',') if s.strip()]
            if declared_statuses or stated:
                error_types = {s for s, ty in declared_statuses.items()
                               if not ty or 'error' in ty.lower() or int(s) >= 400}
                for status in sorted(set(stated) | error_types):
                    if status in stated and status in error_types:
                        kind, detail = 'covered', 'Declared in the trait as the SDD requires.'
                    elif status in stated:
                        kind = 'gap' if declared_statuses else 'misplaced'
                        detail = ('Required by the SDD; the trait does not declare it.'
                                  if declared_statuses else
                                  'No trait supplied, so this status is asserted on the SDD alone.')
                    else:
                        kind, detail = 'undeclared', ('Declared in the trait; the SDD does not '
                                                      'require it. Either the SDD is thin or the '
                                                      'API returns more than was asked for.')
                    rows.append(Row(name=f'status.{status}', kind=kind, detail=detail,
                                    data={'field': f'status.{status}', 'design': None,
                                          'scope': 'error', 'status': status}))
            if trait_note:
                rows.append(Row(name='(error trait)', kind='unreadable', detail=trait_note,
                                data={'field': '(error trait)', 'design': None, 'scope': 'error'}))

            if error_note and not error_declared:
                rows.append(Row(name='(error artifact)', kind='unreadable', detail=error_note,
                                data={'field': '(error artifact)', 'design': None, 'scope': 'error'}))

        return sorted(rows, key=lambda r: (SEVERITY.get(r.kind, 5), r.name))

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        asset, service = _safe(cfg.get('assetName')), _safe(cfg.get('serviceName'))
        out = Path((cfg.get('paths') or {}).get('contract') or ACCEL['contract'])
        ref = str(cfg.get('requirementRef') or '(not supplied)')

        covered = [r for r in rows if r.kind == 'covered']
        queries = [r for r in rows if r.kind in ('gap', 'conflict', 'misplaced', 'undeclared')]
        testable = [r for r in rows if r.kind in ('covered', 'conflict')
                    and (r.data or {}).get('scope') != 'error']
        total = len(covered) + len([r for r in rows if r.kind in ('gap', 'conflict', 'misplaced')])
        coverage = round(100.0 * len(covered) / total, 1) if total else 0.0

        # ── query log ──────────────────────────────────────────────────────
        Q = [f'# Requirements query log — {asset} ({service})', '',
             '<!-- GENERATED by TestHub Automation Studio. Regenerate rather than hand-edit. -->', '',
             f'**Source of truth:** {ref}  ',
             f'**Requirement coverage:** {coverage}% — {len(covered)} of {total} stated requirements '
             f'are correctly declared in the design artifact.', '',
             'Every row below is a question that must be answered before a test derived from this '
             'contract can be trusted. Automating around them produces a green suite over an '
             'unverified requirement.', '',
             '| # | Field | Query | Detail | Owner | Status |',
             '|---|---|---|---|---|---|']
        for i, r in enumerate(queries, 1):
            detail = r.detail.replace('|', '\\|')
            Q.append(f'| Q{i:03d} | `{r.name}` | {r.kind} | {detail} |  | open |')
        if not queries:
            Q.append('| — | — | — | No open queries: every stated requirement is correctly declared. |  |  |')
        Q += ['', '## How to read this', '',
              '- **gap** — the business asked for it and the design does not have it. The design changes.',
              '- **conflict** — both mention it and disagree. The most dangerous row here, because it '
              'looks like agreement until a test asserts the wrong side.',
              '- **misplaced** — specified, just not in the SDD. Someone fetches it from the named '
              'source; this is a lookup, not a decision, and it should not consume a designer\'s time.',
              '- **undeclared** — the design has it and no requirement asked for it. Either the '
              'specification is incomplete or the design has grown scope. Both are worth knowing.', '',
              '## What was NOT checked', '',
              'This compares stated requirements against a declared contract. It cannot tell you a '
              'requirement is *wrong*, only that the two artifacts disagree. Business-rule '
              'correctness still needs a human who knows the domain.', '']
        assets = Assets(rows=len(rows), sheet=f'{asset}Contract')
        assets.add(out / f'{asset}-{service}.query-log.md', '\n'.join(Q))

        # ── coverage, machine-readable ─────────────────────────────────────
        assets.add(out / f'{asset}-{service}.coverage.json', json.dumps({
            'note': 'GENERATED by TestHub Automation Studio',
            'asset': asset, 'service': service, 'requirementRef': ref,
            'requirementCoveragePercent': coverage,
            'counts': {k: len([r for r in rows if r.kind == k])
                       for k in ('covered', 'gap', 'conflict', 'misplaced', 'undeclared', 'unreadable')},
            'openQueries': [{'id': f'Q{i:03d}', 'field': r.name, 'type': r.kind, 'detail': r.detail}
                            for i, r in enumerate(queries, 1)],
        }, indent=2) + '\n')

        # ── contract suite ─────────────────────────────────────────────────
        endpoint = str(cfg.get('mockEndpoint') or '').strip()
        S = ["import { test, expect } from '@playwright/test';", '',
             '/**', f' * {asset} — contract assurance ({service})', ' *',
             ' * GENERATED by TestHub Automation Studio.', ' *',
             f' * Asserts the response against the SPECIFICATION ({ref}),',
             ' * not against the design artifact. Where the two disagree the specification wins —',
             ' * that is the whole point, and it is why a passing run here means something a',
             ' * schema-validation run does not.', ' *',
             ' * Written before the mock exists so it runs the moment the designers publish one.',
             ' */', '',
             f'const ENDPOINT = process.env.CONTRACT_ENDPOINT ?? {_js(endpoint)};', '',
             "test.describe('" + f'{asset} contract' + "', () => {", '',
             '  test.skip(!ENDPOINT, "Set CONTRACT_ENDPOINT (or supply a mock endpoint) to run.");', '',
             '  test("contract matches the specification", async ({ request }) => {',
             '    const res = await request.get(ENDPOINT);',
             '    expect(res.ok(), `endpoint did not respond OK: ${res.status()}`).toBeTruthy();',
             '    const body = await res.json();',
             '    const record = Array.isArray(body) ? body[0] : (body.data ?? body);', '']
        for r in testable:
            if r.data.get('mandatory') is True:
                S.append(f'    expect(record, {_js(f"{r.name}: mandatory per specification")})'
                         f'.toHaveProperty({_js(r.name)});')
        for r in testable:
            if r.data.get('mandatory') is True and r.data.get('type') in ('string', 'number', 'boolean'):
                S.append(f'    if (record[{_js(r.name)}] !== undefined) '
                         f'expect(typeof record[{_js(r.name)}], {_js(f"{r.name}: type per specification")})'
                         f'.toBe({_js(r.data["type"])});')
        S += ['  });', '']

        # A gap must not simply vanish from the suite. If a specification-mandated
        # field is missing from the design, dropping it leaves a green report that
        # reads as "all requirements met". test.fixme keeps it visible as pending
        # work in the same report the sign-off meeting looks at.
        gaps = [r for r in rows if r.kind == 'gap' and (r.data or {}).get('scope') != 'error']
        if gaps:
            S += ['  // Specification-mandated fields the design artifact does not declare.',
                  '  // Pending, not passing — a missing requirement must be visible in the report,',
                  '  // not absent from it.']
            for r in gaps:
                S.append(f'  test.fixme({_js(f"{r.name}: required by specification, absent from design")},'
                         f' async () => {{}});')
            S.append('')

        conflicts = [r for r in rows if r.kind == 'conflict'
                     and (r.data or {}).get('scope') != 'error']
        if conflicts:
            S += ['  // Fields the specification and the design artifact disagree about. Asserted',
                  '  // against the SPECIFICATION on purpose: if the implementation followed the',
                  '  // design instead, this test is how that surfaces — loudly, before sign-off.']
            for r in conflicts:
                S.append(f'  // Q · {r.name} — {r.detail}')
            S.append('')
        # ── error contract ────────────────────────────────────────────────
        error_rows = [r for r in rows if (r.data or {}).get('scope') == 'error'
                      and r.kind in ('covered', 'conflict')]
        # Assert every status either side names. Dropping the ones only the trait
        # declares would leave the API free to return an undocumented error shape.
        statuses = sorted({str(r.data['status']) for r in rows
                           if (r.data or {}).get('status') and r.kind != 'unreadable'}
                          or {s.strip() for s in str(cfg.get('errorStatuses') or '').split(',') if s.strip()})
        trigger = str(cfg.get('errorTrigger') or '').strip()

        # Gaps are emitted whether or not anything is testable. Nesting them under
        # `if error_rows` meant an envelope where EVERY field is missing — the worst
        # case — produced a spec with no trace of it at all: exactly the silent
        # omission the success path already forbids.
        error_gaps = [r for r in rows if (r.data or {}).get('scope') == 'error' and r.kind == 'gap']

        if error_rows or error_gaps:
            S += ['  // The error contract. Asserted against the SDD envelope, because a suite that',
                  '  // only proves the happy path leaves the half a C4E governs hardest unverified.']

        if error_rows and trigger:
            S.append(f'  const ERROR_URL = process.env.CONTRACT_ERROR_URL ?? {_js(trigger)};')
            S.append('')
            S.append('  test("error responses carry the standard envelope", async ({ request }) => {')
            S.append('    const res = await request.get(ERROR_URL);')
            if statuses:
                S.append(f'    expect({json.dumps([int(s) for s in statuses if s.isdigit()])},')
                S.append('      `expected a declared error status, got ${res.status()}`)'
                         '.toContain(res.status());')
            S.append('    expect(res.status(), "error trigger returned a success").'
                     'toBeGreaterThanOrEqual(400);')
            S.append('    const body = await res.json();')
            for r in error_rows:
                fname = r.name.split('.', 1)[1]
                if r.data.get('mandatory') is True:
                    S.append(f'    expect(body, {_js(f"error.{fname}: mandatory per the SDD envelope")})'
                             f'.toHaveProperty({_js(fname)});')
            S.append('  });')
        elif error_rows:
            S += ['  // No error-provoking request was supplied, so these cannot run. Pending,',
                  '  // not skipped: an unverified error contract must be visible in the report.']
            S.append('  test.fixme("error responses carry the standard envelope '
                     '(set errorTrigger / CONTRACT_ERROR_URL)", async () => {});')

        for r in error_gaps:
            fname = r.name.split('.', 1)[1]      # 'error.x' or 'status.404'
            label = (f'status {fname}: required by the SDD, not declared in the trait'
                     if fname.isdigit() else
                     f'error.{fname}: required by the SDD envelope, absent from the Error type')
            S.append(f'  test.fixme({_js(label)}, async () => {{}});')

        if error_rows or error_gaps:
            S.append('')

        S += ['});', '']
        # The spec goes where Playwright actually looks. Emitted beside the query
        # log it was outside testDir, so `playwright test <file>` found no tests
        # and the Ortoni report never carried a contract entry — a suite that was
        # generated, listed as runnable, and could not run. Same fix the perf,
        # ZAP and garak gates needed (DECISIONS: "the Ortoni gate specs never ran").
        spec_dir = Path((cfg.get('paths') or {}).get('spec') or SPEC_DIR_DEFAULT) / asset
        assets.add(spec_dir / f'{asset}-{service}.contract.spec.ts', '\n'.join(S))
        return assets


engine = register(ContractFirstEngine())
