"""
The frameworks/ layout — one folder per standalone framework — is reachable, not just declared.

Why this file exists
--------------------
Engine defaults are strings. A default that points at a folder nobody created, or a
drop that lands beside a framework rather than inside it, is a layout that exists in
CLAUDE.md and nowhere else. These assert that every engine's default output lands
under frameworks/, and that the k6 drop lands inside a copy of the client's framework that
actually carries the loaders the emitted tests import.
"""

from __future__ import annotations

import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
REPO = FRONTEND.parent
sys.path.insert(0, str(FRONTEND))

import engines  # noqa: E402

CFG = {
    'ui': {'assetName': 'portal', 'serviceName': 'login', 'journeyName': 'login', 'baseUrl': 'https://x.test',
           'steps': [{'action': 'fill', 'locator': '#u', 'value': 'x'}], 'successLocator': 'text=ok'},
    'ai': {'assetName': 'bot', 'endpointEnvVar': 'AGENT_ENDPOINT', 'cases': 'hi => hello'},
    'sf': {'assetName': 'accounts', 'serviceName': 's', 'sfObject': 'Account', 'fields': {'Name': 'Acme'}},
    'contract': {'assetName': 'a', 'serviceName': 's', 'requirementRef': 'SDD-1',
                 'requirements': 'accountNumber | mandatory | string | 11 digits',
                 'designArtifact': 'properties:\n  accountNumber:\n    type: string\n    required: true'},
    'af': {'assetName': 'a', 'agentApiName': 'A', 'utterances': 'hi => Topic'},
    'llmsec': {'assetName': 'a', 'serviceName': 's', 'modelName': 'llama3.2:3b'},
    'mob': {'assetName': 'a', 'serviceName': 's', 'platform': 'android', 'bundleId': 'x.y',
            'deviceName': 'Pixel', 'expectText': '1', 'steps': [{'action': 'waitFor', 'locator': '1'}]},
    'perf': {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://e.com', 'endpoint': '/v1'},
    'sec': {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://e.com',
            'authorisationRef': 'SELF-OWNED test fixture'},
}
EXPECTED_ROOT = {
    'ui': 'testhub-ui-quality-accelerator', 'ai': 'testhub-ai-agentic-quality-accelerator',
    'sf': 'testhub-salesforce-quality-accelerator',
    'contract': 'testhub-contract-quality-accelerator', 'af': 'testhub-agentforce-quality-accelerator',
    'llmsec': 'testhub-llm-security-quality-accelerator', 'mob': 'testhub-mobile-quality-accelerator',
    'perf': 'testhub-performance-quality-accelerator', 'sec': 'testhub-security-quality-accelerator',
}
# Playwright projects: a .spec.ts/.test.ts must sit in one of these testDirs or it never runs.
TESTDIRS = ('testhub-api-quality-accelerator/src/tests/', 'testhub-ui-quality-accelerator/tests/',
            'testhub-ai-agentic-quality-accelerator/tests/', 'testhub-salesforce-quality-accelerator/tests/')


def _default_paths(engine_id: str) -> list[str]:
    eng = engines.get(engine_id)
    cfg = CFG[engine_id]
    return [Path(p).as_posix() for p in eng.render(cfg, eng.build_matrix(cfg)).files]


def test_every_standalone_engine_writes_under_its_own_frameworks_folder():
    for engine_id, root in EXPECTED_ROOT.items():
        paths = _default_paths(engine_id)
        outside = [p for p in paths if not p.startswith(root + '/') and not p.startswith('testhub-api-quality-accelerator/src/tests/')]
        assert not outside, f'{engine_id} writes outside {root}/ (and src/tests/ gates): {outside}'
        assert any(p.startswith(root + '/') for p in paths), f'{engine_id} wrote nothing under {root}/'


def test_the_k6_drop_lands_inside_the_vendored_framework_beside_its_loaders():
    """The emitted tests import ../../src/utils/*.js. Those files must exist in the
    vendored tree, or the drop is a tree of files that cannot run."""
    fw = REPO / 'testhub-performance-quality-accelerator'
    for rel in ('scripts/excel-to-scenario.mjs', 'src/utils/dataLoader.js',
                'src/utils/optionsLoader.js', 'src/utils/authSetup.js',
                'src/utils/scenarioRunner.js', 'src/utils/htmlReport.js',
                'config/environments.json', 'VENDORED.md', 'package.json'):
        assert (fw / rel).is_file(), f'vendored framework is missing {rel}'
    paths = _default_paths('perf')
    assert 'testhub-performance-quality-accelerator/tests/a-s/a-s-smoke-test.js' in paths
    assert 'testhub-performance-quality-accelerator/tests/a-s/a-s.xlsx' in paths
    assert 'testhub-performance-quality-accelerator/studio/a-s.load.k6.js' in paths


def test_studio_names_do_not_collide_with_his_files_and_his_example_is_guarded(tmp_path):
    """His files are the ones a newer drop replaces; the Studio's must not collide.

    One name DOES collide by construction: his own example is `createuser`, and a
    tester typing "createUser" would land on exactly those paths. The overwrite
    guard has to refuse that — his files carry no GENERATED marker — and it has
    to refuse before touching anything. Proved on a copy of the vendored tree.
    """
    import shutil
    import pytest
    from engines.base import WouldClobber, write

    fw = REPO / 'testhub-performance-quality-accelerator'
    his = {p.relative_to(fw).as_posix() for p in fw.rglob('*')
           if p.is_file() and 'node_modules' not in p.parts}
    eng = engines.get('perf')

    def mine(name):
        cfg = {**CFG['perf'], 'testName': name}
        return {Path(p).as_posix().split('testhub-performance-quality-accelerator/', 1)[1]
                for p in eng.render(cfg, eng.build_matrix(cfg)).files
                if 'testhub-performance-quality-accelerator/' in Path(p).as_posix()}

    for name in ('smoke', 'load', 'stress', 'users-user-service', 'getUsers', 'new-user'):
        assert not (mine(name) & his), f'testName={name!r} would overwrite his files'

    # Names that WOULD land on his files are refused before anything is rendered.
    import pytest
    for name in ('createuser', 'profiles'):
        with pytest.raises(ValueError, match='reserved'):
            eng.build_matrix({**CFG['perf'], 'testName': name})

    # Defence in depth: if render() is ever reached with such a name, the guard
    # still refuses, and refuses before writing anything. On a throwaway copy.
    copy = tmp_path / 'fw'
    shutil.copytree(fw, copy, ignore=shutil.ignore_patterns('node_modules'))
    before = {p: p.read_bytes() for p in copy.rglob('*') if p.is_file()}
    base = {**CFG['perf'], 'paths': {'perfFramework': str(copy), 'perf': str(tmp_path / 'studio'),
                                     'spec': str(tmp_path / 'spec')}}
    rows = eng.build_matrix({**base, 'testName': 'harmless'})
    with pytest.raises(WouldClobber):
        write(eng.render({**base, 'testName': 'createUser'}, rows))
    after = {p: p.read_bytes() for p in copy.rglob('*') if p.is_file()}
    assert after == before, 'the guard must refuse before writing anything'


def test_every_playwright_spec_lands_under_the_spec_dir_so_it_is_collected():
    """Playwright only collects files under testDir (src/tests). A .spec.ts or
    .test.ts anywhere else is generated, shows as runnable in the Studio, and
    finds no tests when run. The contract engine had exactly this until
    2026-09-06; this stops it coming back for any engine."""
    for engine_id, cfg in CFG.items():
        eng = engines.get(engine_id)
        for path in eng.render(cfg, eng.build_matrix(cfg)).files:
            rel = Path(path).as_posix()
            if rel.endswith(('.spec.ts', '.test.ts')) and 'testhub-mobile-quality-accelerator/' not in rel:
                assert rel.startswith(TESTDIRS), f'{engine_id} emits a Playwright spec outside every Playwright testDir: {rel}'


def test_the_standalone_accelerators_are_real_playwright_projects():
    """A folder that only holds specs is a folder Playwright never runs. UI and AI
    agentic are standalone here — their own package.json, config and testDir."""
    for name in ('testhub-ui-quality-accelerator', 'testhub-ai-agentic-quality-accelerator'):
        d = REPO / name
        for rel in ('package.json', 'playwright.config.ts', 'tsconfig.json', 'tests', 'README.md'):
            assert (d / rel).exists(), f'{name} is missing {rel}'
        assert "testDir: './tests'" in (d / 'playwright.config.ts').read_text()


def test_the_ui_keyword_layer_is_a_byte_identical_copy_not_a_fork():
    """browserActions.ts is vendored from the accelerator and must never be edited. The UI
    accelerator carries a copy so it can run standalone; the copy has to match
    the API accelerator's, or the two silently diverge."""
    import filecmp
    a = REPO / 'testhub-api-quality-accelerator' / 'src' / 'ui'
    b = REPO / 'testhub-ui-quality-accelerator' / 'src' / 'ui'
    for f in a.rglob('*'):
        if f.is_file():
            other = b / f.relative_to(a)
            assert other.is_file() and filecmp.cmp(f, other, shallow=False), f'src/ui drift: {f.relative_to(a)}'


def test_the_ui_spec_imports_resolve_from_where_it_lands():
    """From tests/<asset>/ in the UI accelerator the keyword layer is ../../src/ui;
    from src/tests/<asset>/ in the API accelerator it is ../../ui. The import
    must follow the folder, or the spec fails at collection."""
    eng = engines.get('ui')
    cfg = CFG['ui']
    ui = next(v for p, v in eng.render(cfg, eng.build_matrix(cfg)).files.items())
    assert "from '../../src/ui/browserActions'" in ui and "'../../ui/" not in ui
    api = next(v for p, v in eng.render({**cfg, 'paths': {'ui': 'testhub-api-quality-accelerator/src/tests'}},
                                        eng.build_matrix(cfg)).files.items())
    assert "from '../../ui/browserActions'" in api
    spec = REPO / 'testhub-ui-quality-accelerator' / 'tests' / 'portal' / 'login.ui.test.ts'
    for line in ui.splitlines():
        if line.startswith('import') and "from '../../src/ui/" in line:
            mod = line.split("from '")[1].rstrip("';")
            assert (spec.parent / (mod + '.ts')).resolve().is_file(), f'unresolvable import {mod}'
