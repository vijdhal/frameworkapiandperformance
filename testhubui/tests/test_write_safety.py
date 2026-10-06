"""
Tests for the overwrite guard in engines.write().

Why this file exists
--------------------
Found during the pre-handover sweep, by generating twice over a file a human
had edited. The Studio destroyed it, silently, and returned ok:true.

That is not an exotic path — it is the workflow. A QA engineer generates a
spec, hand-edits it to add the assertions only a human knows to add, then
regenerates to pick up a new scenario. Before this guard, the second generate
threw the edits away with no warning, no backup and no error.

The distinction the guard rests on: a file carrying the generated-by marker was
written by this tool and is safe to reissue; anything else is presumed precious.
Getting that backwards in either direction is a bug —
  - too strict, and the normal regenerate loop starts prompting, which trains
    people to click through warnings;
  - too loose, and someone loses a day's work.
Both directions are asserted below.

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

from engines.base import (Assets, GENERATED_MARKER, WouldClobber,  # noqa: E402
                          write)


def _bundle(path: Path, body: str = 'new content') -> Assets:
    a = Assets(rows=1, sheet='X')
    a.add(path, body)
    return a


def test_hand_written_file_is_never_silently_destroyed(tmp_path):
    victim = tmp_path / 'mine.ui.test.ts'
    victim.write_text('PRECIOUS HAND-WRITTEN TEST', encoding='utf-8')

    with pytest.raises(WouldClobber) as exc:
        write(_bundle(victim))

    assert str(victim) in exc.value.paths
    assert victim.read_text(encoding='utf-8') == 'PRECIOUS HAND-WRITTEN TEST'


def test_regenerating_our_own_file_is_silent(tmp_path):
    """The normal loop. Prompting here would be noise, and noise gets clicked
    through — which is how the guard would stop protecting anything."""
    ours = tmp_path / 'gen.ui.test.ts'
    ours.write_text(f'/** {GENERATED_MARKER} Automation Studio. */\nold', encoding='utf-8')

    written = write(_bundle(ours, 'regenerated'))

    assert written == [str(ours)]
    assert ours.read_text(encoding='utf-8') == 'regenerated'


def test_explicit_overwrite_is_honoured(tmp_path):
    """A human who has seen the refusal can still say yes."""
    victim = tmp_path / 'mine.ts'
    victim.write_text('hand written', encoding='utf-8')

    write(_bundle(victim, 'forced'), overwrite=True)

    assert victim.read_text(encoding='utf-8') == 'forced'


def test_new_files_are_unaffected(tmp_path):
    target = tmp_path / 'nested' / 'brand-new.ts'
    assert write(_bundle(target)) == [str(target)]
    assert target.read_text(encoding='utf-8') == 'new content'


def test_a_rejected_bundle_writes_nothing_at_all(tmp_path):
    """Checked up front, so a refusal cannot leave a half-written tree — the
    state that is hardest to reason about when something has gone wrong."""
    safe = tmp_path / 'safe.ts'
    victim = tmp_path / 'victim.ts'
    victim.write_text('hand written', encoding='utf-8')

    bundle = Assets(rows=1, sheet='X')
    bundle.add(safe, 'should not appear')
    bundle.add(victim, 'should not appear')

    with pytest.raises(WouldClobber):
        write(bundle)

    assert not safe.exists(), 'a rejected bundle partially wrote to disk'
    assert victim.read_text(encoding='utf-8') == 'hand written'


def test_unreadable_file_is_treated_as_precious(tmp_path):
    """Binary or undecodable content cannot be shown to carry the marker, so
    it must fall on the safe side rather than being assumed ours."""
    blob = tmp_path / 'thing.xlsx'
    blob.write_bytes(b'\x89PNG\x00\x00\xff\xfe binary junk')

    with pytest.raises(WouldClobber):
        write(_bundle(blob))


def test_every_engine_marks_what_it_writes(tmp_path):
    """The guard is only as good as the marker's coverage: an engine that emits
    an unmarked text asset would block its OWN next regenerate."""
    import engines

    PATHS = {k: str(tmp_path) for k in
             ('spec', 'mobile', 'perf', 'security', 'agentforce', 'aiData',
              'llmsec', 'sfSpec', 'sfData', 'data', 'ui', 'contract')}
    CFG = {
        'contract': {'assetName': 'a', 'serviceName': 's', 'requirementRef': 'SDD-1',
                     'requirements': 'accountNumber | mandatory | string | 11 digits',
                     'designArtifact': 'properties:\n  accountNumber:\n    type: string\n'
                                       '    required: true'},
        'af': {'assetName': 'a', 'agentApiName': 'A', 'utterances': 'hi => Topic'},
        'ai': {'assetName': 'a', 'endpointEnvVar': 'AGENT_ENDPOINT', 'cases': 'hi => hello'},
        'llmsec': {'assetName': 'a', 'serviceName': 's', 'modelName': 'llama3.2:3b'},
        'mob': {'assetName': 'a', 'serviceName': 's', 'platform': 'android',
                'bundleId': 'x.y', 'deviceName': 'Pixel', 'expectText': '1',
                'steps': [{'action': 'waitFor', 'locator': '1'}]},
        'perf': {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://e.com',
                 'endpoint': '/v1', 'p95': '500'},
        'sec': {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://e.com',
                'authorisationRef': 'SELF-OWNED test fixture'},
        'sf': {'assetName': 'a', 'serviceName': 's', 'sfObject': 'Account',
               'fields': {'Name': 'Acme'}},
        'ui': {'assetName': 'a', 'serviceName': 's', 'journeyName': 's',
               'baseUrl': 'file:///x', 'successLocator': '#a',
               'steps': [{'action': 'click', 'locator': '#a'}]},
        # afc edits agentforce.config.ts in the framework repo through
        # /api/agentforce/config; it emits no assets of its own, which the
        # emits_assets assertion below pins so that stays true.
        'afc': {'frameworkRoot': '/tmp/agentforce-testing-framework',
                'suites': [{'key': 'orderManagement',
                            'sfSuiteName': 'Order Management Tests'}]},
    }

    for meta in engines.catalog():
        eid = meta['id']
        eng = engines.get(eid)
        cfg = dict(CFG[eid])
        cfg.update({'positive': True, 'negative': True, 'paths': dict(PATHS)})
        bundle = eng.render(cfg, eng.build_matrix(cfg))
        # An engine that says it emits nothing must emit nothing. If that ever
        # changes, the marker assertion below has to start covering it — so fail
        # here rather than let unmarked files slip past an unticked flag.
        if not eng.emits_assets:
            assert not bundle.files, \
                f'{eid} declares emits_assets=False but wrote {sorted(f.name for f in bundle.files)}'
            continue
        # Pure-data JSON that something else parses at runtime (a request
        # payload, or the perf engine's compiled profiles.json / <slug>-scenario.json
        # — normally excel-to-scenario.mjs's own output) cannot carry a comment
        # marker without breaking JSON.parse(). These rely on write()'s _same()
        # byte-identical check instead — see test_rewriting_a_file_with_identical_bytes_is_not_a_clobber.
        UNMARKABLE_JSON = ('-requestpayload.json', '-scenario.json', 'profiles.json')
        for path, content in bundle.files.items():
            if isinstance(content, bytes):
                continue                     # binary assets carry no header
            if path.name.endswith(UNMARKABLE_JSON):
                continue
            assert GENERATED_MARKER.lower() in content.lower(), \
                f'{eid} emits {path.name} with no generated-by marker — it would ' \
                f'block its own regenerate'


def test_generated_workbook_does_not_block_its_own_regenerate(tmp_path):
    """An .xlsx stores its properties deflated, so the marker cannot be found by
    scanning bytes — the guard has to read the archive. Without that, the perf
    engine emits a workbook and is then refused permission to replace it, which
    is the exact failure the marker exists to prevent, reappearing as soon as an
    asset is binary."""
    import engines
    from engines.base import _is_ours

    eng = engines.get('perf')
    cfg = {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://e.com',
           'endpoint': '/v1', 'p95': '500', 'profile': 'smoke',
           # 'spec' too: the perf engine emits its gate spec there, and without it
           # the test writes into the repo's real src/tests. Everything else (the
           # workbook included) now lands under perfFramework/tests/<slug>/.
           'paths': {'spec': str(tmp_path), 'perfFramework': str(tmp_path / 'framework')}}
    bundle = eng.render(cfg, eng.build_matrix(cfg))
    write(bundle)

    books = list((tmp_path / 'framework').glob('tests/*/*.xlsx'))
    assert books, 'perf engine emitted no workbook'
    assert _is_ours(books[0]), 'the guard does not recognise a workbook the Studio wrote'

    write(eng.render(cfg, eng.build_matrix(cfg)))          # must not raise


def test_a_workbook_we_did_not_write_is_still_protected(tmp_path):
    """The archive check must not degrade into "any .xlsx is ours"."""
    from openpyxl import Workbook
    from engines.base import _is_ours

    hand_made = tmp_path / 'hand-made.xlsx'
    Workbook().save(hand_made)
    assert not _is_ours(hand_made)
    with pytest.raises(WouldClobber):
        write(_bundle(hand_made))


def test_rewriting_a_file_with_identical_bytes_is_not_a_clobber(tmp_path):
    """The perf engine's payload JSON must be exactly the body, so it cannot carry
    a marker. A plain regenerate used to refuse over the Studio's own output;
    identical bytes are not a clobber, marker or not. Different bytes still are."""
    from engines.base import Assets, WouldClobber, write

    target = tmp_path / 'x-requestpayload.json'
    write(_bundle_at(target, '{"name": "morpheus"}\n'))
    write(_bundle_at(target, '{"name": "morpheus"}\n'))            # must not raise
    with pytest.raises(WouldClobber):
        write(_bundle_at(target, '{"name": "neo"}\n'))


def _bundle_at(path, content):
    from engines.base import Assets
    b = Assets(); b.add(path, content); return b
