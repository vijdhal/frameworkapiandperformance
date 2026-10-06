"""
Containment tests for /api/report.

Why this file exists
--------------------
The RAMS audit found an arbitrary file read here: the endpoint took a caller-
supplied `root`, made it the containment base, and `?root=/etc&path=hosts`
served /etc/hosts. That was fixed (f605f47) by dropping `root` and always
resolving against the server's own REPO_ROOT.

On 2026-08-20 the endpoint's other branch was deleted: it used to fall back to
"the newest HTML under ortoni-report/" whenever no path was given, which served
one framework's report as another's evidence. That deletion makes _contained()
the ONLY guard on this path, and the path parameter now comes straight from an
SSE event. The guard had no test. It does now.

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

import app as studio  # noqa: E402


@pytest.fixture()
def client():
    studio.app.config['TESTING'] = True
    return studio.app.test_client()


@pytest.mark.parametrize('path', [
    '../../etc/passwd',
    '/etc/hosts',
    '../../../../../../etc/passwd',
    'src/../../outside.html',
])
def test_a_path_outside_the_repo_is_refused(client, path):
    r = client.get('/api/report', query_string={'path': path})
    assert r.status_code in (403, 404), f'{path} was served with {r.status_code}'


def test_no_path_means_no_report_rather_than_someone_elses(client):
    """The deleted fallback, asserted as deleted. A run that produced no report
    must not be handed the newest report on the machine."""
    r = client.get('/api/report')
    assert r.status_code == 404
    assert 'no report path' in r.get_json()['error']


def test_a_non_html_file_inside_the_repo_is_still_refused(client):
    """Containment is not the only rule: the endpoint serves reports, so a
    contained-but-arbitrary file (a .env, a key, a lockfile) is not fair game."""
    r = client.get('/api/report', query_string={'path': 'package.json'})
    assert r.status_code in (403, 404)
