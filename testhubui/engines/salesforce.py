"""
TestHub Automation Studio — Salesforce Test Automation engine.

The roadmap puts Salesforce as the next MVP with immediate market demand,
against ACCELQ / Provar / Copado. This engine therefore does NOT invent a
TestHub-flavoured Salesforce framework. It emits assets in the exact shape of
the team's internal Salesforce automation accelerator so a generated test is
indistinguishable from one written by hand and drops straight into that repo.

Conventions taken verbatim from that repo (and its claude.md):

  · Spec imports `test` from src/fixtures/sfFixtures — page objects and the
    ComparisonHelper arrive as fixtures; `_autoLogin` handles login by persona.
  · Test data lives in YAML keyed by the EXACT Playwright test title
    (`yamlReader.get<T>(testInfo.title, file)`).
  · Tags come from the central `Tags` vocabulary, via Playwright's native
    `{ tag: [...] }` option — never hand-typed strings.
  · Secrets never appear in an asset; credentials resolve from env/credentials.yaml.
  · Layout is tests/salesforce/*.spec.ts and src/testdata/yaml/*.yaml.

Object support mirrors what their page objects can actually DO today — verified
by reading the classes, not assumed:

    Contact  · ContactPage.createContact() exists  -> create + verify flow
    Account  · AccountPage has navigate/read only  -> verify-existing-record flow

There is deliberately no Account create flow, because their framework has none.
Inventing one would emit a test that cannot compile.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache

from pathlib import Path

from .base import ACCEL, Assets, Row, register

# Field sets copied from the accelerator's own page objects so a generated spec
# can never reference a field the framework will not fill.
# ContactPage.CONTACT_TEXT_FIELDS:
CONTACT_FIELDS = [
    'FirstName', 'LastName', 'Email', 'Phone', 'MobilePhone',
    'Title', 'Department',
    'MailingStreet', 'MailingCity', 'MailingState', 'MailingPostalCode', 'MailingCountry',
]
# AccountPage.getAccountSnapshot() reads these:
ACCOUNT_FIELDS = [
    'Name', 'Phone', 'Website', 'Industry', 'Type',
    'BillingStreet', 'BillingCity', 'BillingState', 'BillingPostalCode', 'BillingCountry',
]

REQUIRED = {'Contact': 'LastName', 'Account': 'Name'}

OBJECTS = {
    'Contact': {
        'fixture': 'contactPage',
        'type': 'SfContact',
        'tag': 'Tags.CONTACT',
        'fields': CONTACT_FIELDS,
        'flow': 'create',
    },
    'Account': {
        'fixture': 'accountPage',
        'type': 'SfAccount',
        'tag': 'Tags.ACCOUNT',
        'fields': ACCOUNT_FIELDS,
        'flow': 'verify',
    },
}


def _safe(s: str) -> str:
    return ''.join(c for c in str(s or '').strip() if c.isalnum() or c in '-_') or 'asset'


def _yaml_scalar(v) -> str:
    """Quote anything YAML would otherwise coerce (phone numbers, postcodes, bools)."""
    s = str(v)
    if s == '':
        return "''"
    if (s[0].isdigit() or s[0] in '+-'
            or s.lower() in ('true', 'false', 'null', 'yes', 'no', 'on', 'off')
            or ':' in s or '#' in s):
        return '"' + s.replace('"', '\\"') + '"'
    return s



@lru_cache(maxsize=1)
def _sf_orgs() -> dict:
    """Authenticated Salesforce orgs, via the sf CLI. Cached — preflight runs on
    every catalogue read and shelling out is not free."""
    exe = shutil.which('sf')
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, 'org', 'list', '--json'],
                             capture_output=True, text=True, timeout=25).stdout
        res = json.loads(out).get('result', {})
    except Exception:
        return {}
    orgs = {}
    for key in ('devHubs', 'nonScratchOrgs', 'scratchOrgs', 'sandboxes'):
        for o in (res.get(key) or []):
            alias = o.get('alias') or o.get('username')
            if alias:
                orgs[alias] = {'username': o.get('username'), 'kind': key,
                               'isDevHub': bool(o.get('isDevHub'))}
    return orgs


def _scratch_orgs() -> dict:
    return {a: v for a, v in _sf_orgs().items() if v['kind'] == 'scratchOrgs'}


class SalesforceEngine:
    id = 'sf'
    title = 'Salesforce Test Automation'
    emits_assets = True

    @property
    def can_execute(self) -> bool:
        return bool(_scratch_orgs())

    def preflight(self) -> tuple[bool, str]:
        scratch = _scratch_orgs()
        if scratch:
            names = ', '.join(sorted(scratch))
            return True, (f'Scratch org authenticated ({names}) — assets can be generated and '
                          'deployed. Running them still needs the accelerator repo checked out.')
        if _sf_orgs():
            return True, ('A Salesforce org is authenticated but no scratch org exists. Create one: '
                          'sf org create scratch --definition-file config/afdx-scratch-def.json')
        return True, ('Emits assets for the Salesforce accelerator. Execution needs an '
                      'authenticated org — sf org login web.')

    # ───────────────────────── matrix ─────────────────────────

    def build_matrix(self, cfg: dict) -> list[Row]:
        obj = cfg.get('sfObject') or 'Contact'
        if obj not in OBJECTS:
            raise ValueError(f'unsupported Salesforce object: {obj}')
        spec = OBJECTS[obj]
        fields = {k: v for k, v in (cfg.get('fields') or {}).items()
                  if k in spec['fields'] and str(v).strip() != ''}
        if not fields:
            raise ValueError(f'no {obj} fields captured — supply at least '
                             f'{REQUIRED[obj]}')

        prefix = _safe(cfg.get('casePrefix') or f'TC_SF_{obj}')
        want_pos = cfg.get('positive', True) is not False
        want_neg = cfg.get('negative', True) is not False
        rows: list[Row] = []
        n = 0

        if want_pos:
            n += 1
            verb = 'Create' if spec['flow'] == 'create' else 'Verify'
            rows.append(Row(
                name=f'{prefix}_{n:03d} - {verb} {obj} with multiple fields',
                kind='positive',
                detail=f'{verb} a {obj} from YAML and compare every field against the UI.',
                data={'fields': fields, 'flow': spec['flow']},
            ))

        # Only a create flow can be negatively tested by omitting a required
        # field. A read-only verify flow has no such negative — do not invent one.
        if want_neg and spec['flow'] == 'create':
            req = REQUIRED[obj]
            if req in fields:
                without = {k: v for k, v in fields.items() if k != req}
                if without:
                    n += 1
                    rows.append(Row(
                        name=f'{prefix}_{n:03d} - Create {obj} without {req} is rejected',
                        kind='negative',
                        detail=f'{req} is required by Salesforce; the modal must stay open and the record must not save.',
                        data={'fields': without, 'flow': 'create-negative', 'required': req},
                    ))

        return rows

    # ───────────────────────── render ─────────────────────────

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        obj = cfg.get('sfObject') or 'Contact'
        spec = OBJECTS[obj]
        slug = _safe(cfg.get('assetName') or obj).lower()

        paths = cfg.get('paths') or {}
        spec_dir = Path(paths.get('sfSpec') or ACCEL['sf'] + '/tests/salesforce')
        data_dir = Path(paths.get('sfData') or ACCEL['sf'] + '/src/testdata/yaml')

        # Where we WRITE may be absolute (the Paths dialog resolves against the
        # target repo). What we EMIT into the spec must stay repo-relative —
        # their convention is path.resolve('src/testdata/yaml/…') and a baked-in
        # absolute path would break portability the moment the repo moves.
        data_rel = f"{(cfg.get('sfDataRel') or 'src/testdata/yaml').strip('/')}/sf-{slug}.yaml"

        assets = Assets(rows=len(rows), sheet=f'SF{obj}')
        assets.add(spec_dir / f'{slug}.spec.ts', self._spec(cfg, obj, spec, slug, data_rel, rows))
        assets.add(data_dir / f'sf-{slug}.yaml', self._yaml(obj, rows))
        return assets

    def _yaml(self, obj: str, rows: list[Row]) -> str:
        key = obj.lower()
        out = [
            f'# {obj} test data — keyed by exact Playwright test title (testInfo.title).',
            '# GENERATED by TestHub Automation Studio. Values are test data only;',
            '# credentials and secrets never appear here — they resolve from env.',
            '',
        ]
        for r in rows:
            out.append(f'{r.name}:')
            out.append(f'  {key}:')
            for k, v in r.data['fields'].items():
                out.append(f'    {k}: {_yaml_scalar(v)}')
            out.append('')
        return '\n'.join(out)

    def _spec(self, cfg, obj, spec, slug, data_rel, rows) -> str:
        fixture, sf_type, tag = spec['fixture'], spec['type'], spec['tag']
        key = obj.lower()
        persona = (cfg.get('persona') or '').strip()
        describe = cfg.get('suiteName') or f'Salesforce {obj}'

        o: list[str] = []
        o.append("import { test, expect } from '../../src/fixtures/sfFixtures';")
        o.append("import { yamlReader } from '../../src/testdata/loaders/YamlReader';")
        o.append("import { Tags } from '../../src/tags/tags';")
        o.append(f"import {{ {sf_type} }} from '../../src/interfaces/salesforce.types';")
        o.append("import * as path from 'path';")
        o.append('')
        o.append('/**')
        o.append(f' * {describe}')
        o.append(' *')
        o.append(' * GENERATED by TestHub Automation Studio for the Salesforce accelerator.')
        o.append(" * Data is keyed by test title in the YAML beside it — renaming a test")
        o.append(' * without renaming its YAML key will fail the lookup, by design.')
        o.append(' */')
        o.append('')
        o.append(f"const DATA_FILE = path.resolve('{data_rel}');")
        o.append('')
        o.append(f'interface {obj}TestData {{')
        o.append(f'  {key}: Partial<{sf_type}>;')
        o.append('}')
        o.append('')
        o.append(f'function getTestData(testTitle: string): {obj}TestData {{')
        o.append(f'  return yamlReader.get<{obj}TestData>(testTitle, DATA_FILE);')
        o.append('}')
        o.append('')
        o.append(f"test.describe('{describe}', {{ tag: [Tags.REGRESSION, {tag}] }}, () => {{")
        o.append('')
        if persona:
            o.append(f"  // Run this suite as a non-default persona (role from credentials.yaml).")
            o.append(f"  test.use({{ sfPersona: '{persona}' }});")
            o.append('')

        for r in rows:
            flow = r.data['flow']
            o.append(f'  /** {r.detail} */')
            if flow == 'create':
                o.append(f"  test('{r.name}', async ({{ {fixture}, comparator }}, testInfo) => {{")
                o.append(f'    const {{ {key} }} = getTestData(testInfo.title);')
                o.append('')
                o.append(f'    await {fixture}.create{obj}({key});')
                o.append(f'    await {fixture}.verifySaveToast();')
                o.append('')
                o.append(f'    const uiSnapshot = await {fixture}.getFieldValues(Object.keys({key}));')
                o.append(f'    for (const [field, expectedValue] of Object.entries({key})) {{')
                o.append("      comparator.compare(field, uiSnapshot[field] ?? '', String(expectedValue));")
                o.append('    }')
                o.append('    comparator.logSummary();')
                o.append('  });')
            elif flow == 'create-negative':
                req = r.data['required']
                o.append(f"  test('{r.name}', async ({{ {fixture} }}, testInfo) => {{")
                o.append(f'    const {{ {key} }} = getTestData(testInfo.title);')
                o.append('')
                o.append(f'    await {fixture}.openNew{obj}Form();')
                o.append(f'    await {fixture}.fill{obj}Form({key});')
                o.append('')
                o.append(f'    // {req} is omitted, so Salesforce must block the save and the')
                o.append('    // modal must stay open — saveNewContact() waits for it to close.')
                o.append(f'    await expect({fixture}.saveNew{obj}()).rejects.toThrow();')
                o.append('  });')
            else:   # verify an existing record
                o.append(f"  test('{r.name}', async ({{ {fixture}, comparator }}, testInfo) => {{")
                o.append(f'    const {{ {key} }} = getTestData(testInfo.title);')
                o.append('')
                o.append(f"    const recordId = process.env['SF_{obj.upper()}_ID'];")
                o.append(f"    if (!recordId) test.skip(true, 'Set SF_{obj.upper()}_ID to the record under test.');")
                o.append(f'    await {fixture}.navigateById(recordId as string);')
                o.append('')
                o.append(f'    const uiSnapshot = await {fixture}.getFieldValues(Object.keys({key}));')
                o.append(f'    for (const [field, expectedValue] of Object.entries({key})) {{')
                o.append("      comparator.compare(field, uiSnapshot[field] ?? '', String(expectedValue));")
                o.append('    }')
                o.append('    comparator.logSummary();')
                o.append('  });')
            o.append('')

        o.append('});')
        return '\n'.join(o) + '\n'


engine = register(SalesforceEngine())
