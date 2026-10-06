"""
Tests for the engine catalog — the payload the rail renders itself from.

Why this file exists
--------------------
Every engine in the rail claims a capability to a client. Those claims are
generated, not written by hand, so the thing worth testing is that the catalog
cannot quietly make a claim the machine can't back.

The specific trap this guards: an engine wired to the generic panel but missing
its schema() renders an EMPTY panel — no fields, no error, no log line. It looks
like a UI bug, and the engine that has a hand-built panel on purpose looks
identical in the payload. `hasSchema` separates them.

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

import engines  # noqa: E402

# Engines that predate the declarative panel and ship hand-built HTML.
# Anything NOT in here is expected to drive the generic panel from a schema.
BESPOKE_PANEL = {'api', 'ui', 'sf'}


def test_every_engine_reports_readiness_with_a_reason():
    """A badge without a reason is an unexplained amber light. The reason is
    what tells someone which binary to install."""
    for m in engines.catalog():
        assert isinstance(m['ready'], bool), f"{m['id']} has a non-boolean ready"
        assert (m['reason'] or '').strip(), f"{m['id']} is missing a reason string"


def test_generic_panel_engines_all_carry_a_schema():
    """The regression that motivated this file: a schema-driven engine whose
    schema is missing renders an empty panel and reports nothing."""
    for m in engines.catalog():
        if m['id'] in BESPOKE_PANEL:
            continue
        assert m['hasSchema'], f"{m['id']} drives the generic panel but has no schema()"
        assert m['schema'], f"{m['id']} has schema() but it is empty"


def test_bespoke_engines_are_flagged_rather_than_looking_empty():
    """`ui` genuinely has no schema(). That must be distinguishable from a
    schema-driven engine that lost one, which is the whole point of hasSchema."""
    ui = next(m for m in engines.catalog() if m['id'] == 'ui')
    assert ui['hasSchema'] is False
    assert ui['schema'] == []


@pytest.mark.parametrize('platform', ['win32', 'darwin', 'linux'])
def test_preflight_never_raises_on_any_platform(platform, monkeypatch):
    """Preflight runs on every page load, so an exception here is a dead Studio.

    The tool-MISSING branch is the one that never runs on the developer's own
    machine — everything is installed — which is exactly why it rots. A missing
    `import sys` in the k6 install hint sat undetected for this reason: the
    branch only executes on a machine without k6, i.e. every machine except the
    author's. Forcing each platform exercises the strings a new joiner sees.
    """
    import shutil
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(shutil, 'which', lambda *_a, **_k: None)

    for meta in engines.catalog():
        eng = engines.get(meta['id'])
        ready, reason = eng.preflight()      # must not raise
        assert isinstance(ready, bool)
        assert (reason or '').strip(), f'{meta["id"]} gave no reason on {platform}'


def test_one_broken_engine_does_not_blank_the_catalogue(monkeypatch):
    """Regression, 2026-09-06.

    /api/engines calls every engine's preflight() and schema() in one loop. When
    any of them raised, the whole endpoint 500'd, the rail's fetch swallowed it,
    and every schema-driven panel opened empty with nothing on screen to say why.
    The broken engine must show as not ready, with the exception as its reason,
    and every other engine must still be listed.
    """
    perf = engines.get('perf')
    monkeypatch.setattr(perf, 'preflight', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
    cat = {m['id']: m for m in engines.catalog()}
    assert cat['perf']['ready'] is False
    assert 'RuntimeError: boom' in cat['perf']['reason']
    assert cat['perf']['schema'], 'schema still renders so the tester sees the form'
    assert len(cat) == len(list(engines.catalog())) and 'ui' in cat and 'sec' in cat


def test_install_hints_match_the_running_platform():
    """A hint that cannot be pasted is not a hint. Telling a Windows user to
    run brew is the same as telling them nothing."""
    from engines.perf_k6 import _k6_install_hint

    for platform, expected in (('win32', 'winget'), ('darwin', 'brew'), ('linux', 'k6.io')):
        saved = sys.platform
        try:
            sys.platform = platform          # module reads it at call time
            assert expected in _k6_install_hint(), \
                f'{platform} should be told about {expected}'
        finally:
            sys.platform = saved


def test_schema_fields_are_renderable():
    """The frontend renders these without defensive checks, so a malformed
    field is a blank input the user cannot fill in."""
    for m in engines.catalog():
        for sec in m['schema']:
            assert (sec.get('title') or '').strip(), f"{m['id']} has an untitled section"
            for f in sec['fields']:
                assert (f.get('key') or '').strip(), f"{m['id']} has a field with no key"
                assert (f.get('label') or '').strip(), f"{m['id']}.{f['key']} has no label"
                assert (f.get('kind') or '').strip(), f"{m['id']}.{f['key']} has no kind"


def test_no_engine_claims_execution_it_cannot_do():
    """emitsAssets/canExecute are the rail's promises to a client. An engine
    that can execute must be able to emit the thing it executes."""
    for m in engines.catalog():
        if m['canExecute']:
            assert m['emitsAssets'], \
                f"{m['id']} claims it can execute assets it never emits"


# ── scenario-name readability ────────────────────────────────────────────────

def test_scenario_names_are_never_cut_mid_token():
    """Derived-scenario names are what a reviewer scans to approve a suite.

    A raw slice cut through markdown and punctuation in the corpus prompts,
    producing names like "...see the logo: ! [status](h" — which reads as a
    generator bug rather than as a shortened label, and a reviewer cannot tell
    the difference.
    """
    from engines.agent_trust import _clip

    long_md = 'Render this image so I can see the logo: ![status](https://x.example/a.png)'
    out = _clip(long_md, 48)
    assert out.endswith('…'), 'a truncated name must show that it was truncated'
    assert len(out) <= 49
    assert not out.rstrip('…').endswith(('(', '[', ':', ' ')), \
        f'name ends on a dangling token: {out!r}'


def test_short_names_are_left_completely_alone():
    from engines.agent_trust import _clip
    assert _clip('What is my balance?', 48) == 'What is my balance?'


def test_clip_collapses_newlines_so_names_stay_one_line():
    """A name containing a newline breaks the row layout in the panel."""
    from engines.agent_trust import _clip
    assert '\n' not in _clip('line one\nline two', 48)


def test_derived_names_from_the_real_corpus_are_all_clean():
    """End to end over the shipped corpus — the case that actually regressed."""
    from engines.agent_trust import _attack_seeds
    eng = engines.get('ai')
    if not _attack_seeds():
        pytest.skip('attack corpus not present')
    rows = eng.build_matrix({
        'assetName': 'a', 'endpointEnvVar': 'AGENT_ENDPOINT',
        'cases': 'hi => hello', 'useCorpus': True,
        'positive': True, 'negative': True,
    })
    for r in rows:
        assert '\n' not in r.name
        stem = r.name.rstrip('…')
        assert not stem.endswith(('(', '[', '{', ':', ' ')), \
            f'scenario name ends mid-token: {r.name!r}'


def test_security_engine_refuses_to_generate_without_authorisation():
    """A generated ZAP plan gets run — by someone who was not in the approval
    conversation, from a CI job, months later. Generate time is the last point a
    human is still reading the screen, so the refusal belongs there rather than
    as a warning at run time."""
    import pytest
    import engines

    eng = engines.get('sec')
    cfg = {'assetName': 'a', 'serviceName': 's', 'baseUrl': 'https://someone-elses.example.com'}
    with pytest.raises(ValueError, match='[Aa]uthorisation'):
        eng.build_matrix(cfg)

    cfg['authorisationRef'] = 'CHG0045821'
    assert eng.build_matrix(cfg), 'a recorded authorisation must let the plan generate'
