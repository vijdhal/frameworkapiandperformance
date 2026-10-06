"""
Tests for per-framework report resolution.

Why this file exists
--------------------
The client's requirement: every framework must obviously produce its OWN standard
report, because not all of them belong in Ortoni. The reports were already being
written. Finding them was the gap.

The only resolution used to be a regex over stdout shaped for Ortoni's
"Report generated at <path>.html" line. k6, ZAP, garak and mobilewright never
print that, so the runner ended a run with report=None, the frontend called
/api/report with no path, and the endpoint served the newest HTML found under
ortoni-report/. Measured against a real k6 run on 2026-08-20: 108 lines of
output, zero regex matches, and its own perf-report-*.html written and ignored.

Two failure directions, both asserted below:
  - too loose, and a stale report from an EARLIER run is presented as this run's
    evidence, which is a green report over a gate that never ran;
  - too strict, and a framework that did write a report shows nothing, which
    trains people to go looking in the filesystem instead.

Run:  testhubui/.venv/bin/python -m pytest testhubui/tests -q
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND))

import runner  # noqa: E402


def _write(path: Path, mtime: float, body: str = '<html>report</html>') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    os.utime(path, (mtime, mtime))
    return path


def test_k6_report_is_found_where_k6_actually_writes_it(tmp_path):
    started = time.time()
    _write(tmp_path / 'perf-report-clients-customer-service.html', started + 1)
    found = runner._resolve_report('k6', 'perf/clients.k6.js', str(tmp_path),
                                   str(tmp_path), started)
    assert found == 'perf-report-clients-customer-service.html'


def test_a_report_older_than_the_run_is_never_offered(tmp_path):
    """The regression that mattered: evidence from a previous run reads as this
    run's, and a reviewer signs off a gate that never executed."""
    started = time.time()
    _write(tmp_path / 'perf-report-stale.html', started - 3600)
    assert runner._resolve_report('k6', 'perf/clients.k6.js', str(tmp_path),
                                  str(tmp_path), started) is None


def test_garak_report_is_found_beside_its_own_script(tmp_path):
    started = time.time()
    rel = 'llmsec/support-agent.garak.sh'
    _write(tmp_path / 'llmsec' / 'garak-runs' / 'support-agent.report.html', started + 1)
    found = runner._resolve_report('garak', rel, str(tmp_path), str(tmp_path), started)
    assert found == str(Path('llmsec') / 'garak-runs' / 'support-agent.report.html')


def test_a_report_outside_the_repo_is_copied_in_not_served_from_there(tmp_path, monkeypatch):
    """ZAP resolves a relative reportFile against its own install directory. The
    serving endpoint refuses anything outside the repo, and rightly so, so the
    file is brought in rather than the containment check being relaxed."""
    repo, elsewhere = tmp_path / 'repo', tmp_path / 'zap-home'
    repo.mkdir()
    started = time.time()
    outside = _write(elsewhere / 'zap-report-clients.html', started + 1)
    monkeypatch.setitem(runner.ASSET_KINDS['zap'], 'reports',
                        lambda f, root: [str(outside)])
    found = runner._resolve_report('zap', 'security/clients.zap.yaml',
                                   str(repo), str(repo), started)
    assert found == str(Path('reports') / 'zap-report-clients.html')
    assert (repo / found).read_text(encoding='utf-8') == '<html>report</html>'


def test_agentforce_declares_no_html_rather_than_borrowing_one(tmp_path):
    """`sf agent test run` has no HTML format. Showing another framework's report
    would be worse than showing none."""
    started = time.time()
    _write(tmp_path / 'ortoni-report' / 'index.html', started + 1)
    assert runner._resolve_report('agentforce', 'agentforce/a.agentforce-test.yaml',
                                  str(tmp_path), str(tmp_path), started) is None


def test_every_runnable_kind_names_the_report_it_produces():
    """A framework with no report_label would show the generic word 'Report',
    which is exactly the ambiguity this change exists to remove."""
    for kind, spec in runner.ASSET_KINDS.items():
        assert spec.get('report_label'), f'{kind} does not name its own report'
        assert 'reports' in spec, f'{kind} does not declare where its report lands'


def test_playwright_falls_back_to_the_ortoni_folder_when_stdout_says_nothing():
    """The regex over stdout is the fast path, not the only one. With the
    server-side "newest report lying around" fallback deleted, this glob is what
    stands between a successful run and no evidence at all, so it is asserted
    rather than assumed."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        started = time.time()
        _write(root / 'ortoni-report' / 'suite' / 'dev' / 'run.html', started + 1)
        found = runner._resolve_report('playwright', 'src/tests/a/b.test.ts',
                                       str(root), str(root), started)
        assert found == str(Path('ortoni-report') / 'suite' / 'dev' / 'run.html')
