"""
Tests for the Agentforce Configuration engine — MoM points 1-5, 30 Aug 2026.

Why this file carries the weight
--------------------------------
This engine EDITS a hand-written file in someone else's repo. That repo is not on
this machine, so the fixture beside these tests is a RECONSTRUCTION of
agentforce.config.ts from the screenshots shared on the call — the comment block,
the `: AgentforceConfig` annotation and the `process.env ?? "myorg"` lines are
copied verbatim from what was on screen. These tests are therefore the only thing
standing between the merge and a destroyed config, and they are written to fail
loudly rather than to pass.

The invariant under test is narrow and absolute: everything outside the
`suites: [ ... ]` array survives byte for byte, and inside it, an entry nobody
asked to change keeps its own source — including its comments.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

from engines.agentforce_config import (  # noqa: E402
    ConfigError, command_for, engine, merge_suites, parse_suites,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'agentforce.config.ts'


@pytest.fixture
def src() -> str:
    return FIXTURE.read_text()


# ───────────────────────── reading what is there ─────────────────────────

def test_parses_the_suites_already_declared(src):
    assert parse_suites(src) == [
        {'key': 'orderManagement', 'sfSuiteName': 'Order Management Tests'},
        {'key': 'accountManagement', 'sfSuiteName': 'Account Management Tests'},
    ]


def test_reads_a_hand_added_entry_written_with_a_capital_key():
    """The screenshot of the real file shows someone typing `Key:` not `key:`.

    Reading that as a different field would treat the suite as absent and append a
    duplicate on the next merge — two entries, one key, and a CLI that picks one.
    """
    src = 'export const c = { suites: [ { Key: "Testname", sfSuiteName: "testapiname" } ] };'
    assert parse_suites(src) == [{'key': 'Testname', 'sfSuiteName': 'testapiname'}]


# ─────────────── the invariant: everything else survives ─────────────────

def test_merge_preserves_every_byte_outside_the_suites_array(src):
    out, _ = merge_suites(src, [{'key': 'brandNew', 'sfSuiteName': 'Brand New Tests'}])

    head_end = src.index('suites:')
    assert out[:head_end] == src[:head_end], 'the header, imports and comments moved'
    for must_survive in (
        'import { AgentforceConfig } from "./src/types";',
        '// key         : short identifier used in CLI (--test <key>) and result filenames',
        'export const agentforceConfig: AgentforceConfig = {',
        'org: process.env.SF_ORG_ALIAS ?? "myorg",',
        'waitMinutes: Number(process.env.SF_WAIT_MINUTES ?? "10"),',
    ):
        assert must_survive in out, must_survive

    tail = src[src.rindex(']') + 1:]
    assert out.endswith(tail), 'the closing of the config object was rewritten'


def test_updating_one_suite_keeps_its_inline_comment(src):
    """A comment on an entry is the reason someone will not rename it.

    Rebuilding the array from parsed values would drop it silently, and the next
    reader would have no idea the billing squad owns that suite.
    """
    out, report = merge_suites(
        src, [{'key': 'accountManagement', 'sfSuiteName': 'Account Management Tests v2'}])
    assert '// owned by the billing squad — do not rename without telling them' in out
    assert 'sfSuiteName: "Account Management Tests v2"' in out
    assert 'sfSuiteName: "Account Management Tests"' not in out
    assert report == {'updated': ['accountManagement'], 'added': [],
                      'unchanged': ['orderManagement']}


def test_a_suite_nobody_mentioned_is_left_alone(src):
    out, report = merge_suites(src, [{'key': 'brandNew', 'sfSuiteName': 'Brand New Tests'}])
    assert 'key: "orderManagement"' in out and 'sfSuiteName: "Order Management Tests"' in out
    assert report['added'] == ['brandNew']
    assert set(report['unchanged']) == {'orderManagement', 'accountManagement'}


def test_nothing_is_ever_removed(src):
    """Absence from a form submission is not a delete instruction.

    Treating it as one would let a half-filled UI silently drop suites out of the
    release, and the run would still go green — over tests that no longer exist.
    """
    out, _ = merge_suites(src, [])
    assert parse_suites(out) == parse_suites(src)


def test_appending_is_idempotent(src):
    """Clicking Update twice must not produce two entries with the same key."""
    once, _ = merge_suites(src, [{'key': 'testname', 'sfSuiteName': 'testapiname'}])
    twice, report = merge_suites(once, [{'key': 'testname', 'sfSuiteName': 'testapiname'}])
    assert twice == once
    assert report['added'] == [] and report['updated'] == []
    assert [s['key'] for s in parse_suites(twice)].count('testname') == 1


def test_new_entries_match_the_indentation_already_in_the_file(src):
    out, _ = merge_suites(src, [{'key': 'brandNew', 'sfSuiteName': 'Brand New Tests'}])
    assert '        {\n            key: "brandNew",\n' \
           '            sfSuiteName: "Brand New Tests"\n        }' in out


def test_a_bracket_inside_a_suite_name_is_data_not_structure():
    src = 'const c = { suites: [ { key: "a", sfSuiteName: "Tests [EU] ]" } ] };'
    out, report = merge_suites(src, [{'key': 'b', 'sfSuiteName': 'B'}])
    assert report['added'] == ['b']
    assert [s['key'] for s in parse_suites(out)] == ['a', 'b']


def test_a_file_with_no_suites_array_is_refused_not_repaired():
    """Inventing the array would produce a config the framework never declared,
    and a run against it reports success having tested nothing."""
    with pytest.raises(ConfigError, match='No `suites'):
        merge_suites('export const agentforceConfig = { org: "myorg" };', [{'key': 'a', 'sfSuiteName': 'A'}])


# ───────────────────────── validation and running ─────────────────────────

def test_a_key_that_could_be_read_as_a_flag_or_a_path_is_refused():
    for bad in ('--force', '../../etc/passwd', 'a b', 'a;rm -rf /'):
        with pytest.raises(ValueError):
            engine.build_matrix({'suites': [{'key': bad, 'sfSuiteName': 'X'}]})


def test_a_suite_without_its_agentforce_name_is_refused():
    with pytest.raises(ValueError, match='suite name'):
        engine.build_matrix({'suites': [{'key': 'ok', 'sfSuiteName': '  '}]})


def test_build_matrix_previews_the_cli_key_for_each_suite():
    rows = engine.build_matrix({'suites': [{'key': 'orderManagement',
                                            'sfSuiteName': 'Order Management Tests'}]})
    assert rows[0].name == 'orderManagement → Order Management Tests'
    assert '--test orderManagement' in rows[0].detail


def test_the_qa_and_uat_commands_are_declared_empty_not_guessed():
    """MoM point 5, verbatim: "the client has to provide the command."

    The only clue in the repo is `--test <key>`, which does not say whether QA/UAT
    is an org alias, a flag or a separate npm script. A wrong guess runs against a
    live Salesforce org, so this asserts the absence is deliberate and that the
    engine reports itself unrunnable while it stands.
    """
    assert command_for('QA', ['orderManagement']) == []
    assert command_for('UAT', ['orderManagement']) == []
    assert engine.can_execute is False
    ok, reason = engine.preflight()
    assert ok and 'no QA/UAT command has been supplied' in reason


def test_keys_reach_the_command_as_argv_never_as_a_shell_string(monkeypatch):
    """Wiring proof for when the command does arrive."""
    import engines.agentforce_config as afc
    monkeypatch.setitem(afc.COMMANDS, 'QA', ['npm', 'run', 'af:qa', '--', '{keys}'])
    assert afc.command_for('QA', ['a', 'b']) == ['npm', 'run', 'af:qa', '--', '--test', 'a,b']


# ─────────────── the endpoints, against a real file on disk ───────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """A Flask test client with a throwaway framework repo beside it."""
    repo = tmp_path / 'agentforce-testing-framework'
    repo.mkdir()
    (repo / 'agentforce.config.ts').write_text(FIXTURE.read_text(), encoding='utf-8')
    sys.path.insert(0, str(FRONTEND))
    import app as studio
    studio.app.config['TESTING'] = True
    return studio.app.test_client(), repo


def test_read_endpoint_lists_the_keys_actually_in_the_file(client):
    c, repo = client
    r = c.get('/api/agentforce/config', query_string={'root': str(repo)})
    body = r.get_json()
    assert r.status_code == 200 and body['ok']
    assert [s['key'] for s in body['suites']] == ['orderManagement', 'accountManagement']


def test_update_endpoint_appends_and_backs_up_first(client):
    c, repo = client
    cfg = repo / 'agentforce.config.ts'
    before = cfg.read_text()

    r = c.post('/api/agentforce/config', json={
        'frameworkRoot': str(repo),
        'suites': [{'key': 'testname', 'sfSuiteName': 'testapiname'}]})
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] and body['changed']
    assert body['report']['added'] == ['testname']

    # The file is hand-maintained in someone else's repo, and editing it IS the
    # operation — so the overwrite guard cannot protect it. A backup can.
    assert Path(body['backup']).read_text() == before
    assert 'sfSuiteName: "testapiname"' in cfg.read_text()
    assert 'org: process.env.SF_ORG_ALIAS ?? "myorg",' in cfg.read_text()


def test_update_is_a_no_op_when_nothing_changed(client):
    c, repo = client
    payload = {'frameworkRoot': str(repo),
               'suites': [{'key': 'orderManagement', 'sfSuiteName': 'Order Management Tests'}]}
    r = c.post('/api/agentforce/config', json=payload)
    assert r.get_json()['changed'] is False


def test_a_missing_config_is_reported_not_created(client, tmp_path):
    """Creating it would invent a config the framework never declared."""
    c, _ = client
    empty = tmp_path / 'not-a-framework'
    empty.mkdir()
    r = c.post('/api/agentforce/config', json={
        'frameworkRoot': str(empty), 'suites': [{'key': 'a', 'sfSuiteName': 'A'}]})
    assert r.status_code == 404
    assert not (empty / 'agentforce.config.ts').exists()


def test_a_relative_framework_path_is_refused(client):
    """A relative root would resolve against the Studio's own cwd and drop a
    phantom agentforce.config.ts inside THIS repo, where nothing reads it."""
    c, _ = client
    r = c.post('/api/agentforce/config', json={
        'frameworkRoot': 'agentforce-testing-framework',
        'suites': [{'key': 'a', 'sfSuiteName': 'A'}]})
    assert r.status_code == 400 and 'absolute' in r.get_json()['error']


def test_run_refuses_with_the_reason_and_names_what_it_would_have_run(client):
    """Point 5 is wired but inert. The refusal has to be actionable, not a shrug."""
    c, repo = client
    r = c.post('/api/agentforce/run', json={
        'frameworkRoot': str(repo), 'environment': 'QA', 'keys': ['orderManagement']})
    body = r.get_json()
    assert r.status_code == 409 and body['pending'] is True
    assert 'No QA command is configured yet' in body['error']
    assert body['wouldRun'] == {'environment': 'QA', 'keys': ['orderManagement']}


def test_run_rejects_an_unknown_environment_and_a_hostile_key(client):
    c, repo = client
    r = c.post('/api/agentforce/run', json={
        'frameworkRoot': str(repo), 'environment': 'PROD', 'keys': ['a']})
    assert r.status_code == 400

    r = c.post('/api/agentforce/run', json={
        'frameworkRoot': str(repo), 'environment': 'QA', 'keys': ['--force']})
    assert r.status_code == 400
