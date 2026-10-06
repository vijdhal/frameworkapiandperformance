"""
TestHub Automation Studio — Python backend.

Run:  pip install flask openpyxl
      python app.py
Then open http://localhost:5000

Endpoints
  GET  /                 serves the Studio frontend (static/index.html)
  POST /api/draft        saves the current form as a draft on disk
  GET  /api/draft        returns the last saved draft
  POST /api/generate     writes the four assets into the configured paths
"""

from __future__ import annotations   # keep signatures un-evaluated.
# Without this, `X | None` in a signature is evaluated at def time and the
# module simply will not import below Python 3.10 — the Studio would fail to
# start, not degrade. Costs nothing and removes a version constraint nobody
# chose. Note the docs still say 3.10+: that is the version actually tested,
# and this import alone is not evidence 3.9 works end to end.

import sys
sys.dont_write_bytecode = True          # never emit __pycache__ / .pyc

import os
import json
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

from generator import generate
import runner
import engines
from flask import Response

# Works both as plain python and inside a PyInstaller --onefile exe
if getattr(sys, 'frozen', False):
    STATIC_DIR = Path(sys._MEIPASS) / 'static'          # bundled frontend
    APP_DIR = Path(sys.executable).parent                # next to the .exe
else:
    STATIC_DIR = Path(__file__).parent / 'static'
    APP_DIR = Path(__file__).parent

# The Studio lives in <repo>/testhubui, but the framework it drives —
# src/, test-data/, node_modules/, playwright.config.ts — lives one level up
# at the accelerator ROOT. All relative paths (from the Paths dialog) resolve
# against this root, never against testhubui/, so generated files land where
# the accelerator can import ../../utils/excelUtils and playwright can run.
def _find_repo_root(start: Path) -> Path:
    for base in [start] + list(start.parents):
        if (base / 'package.json').exists() and (base / 'src').is_dir():
            return base
    # Fallback: if we're inside a 'frontend' folder, the root is its parent
    if start.name in ('frontend', 'testhubui'):
        return start.parent
    return start

# Since 2026-09-06 the repo is the client's parent layout: the Studio in testhubui/,
# the Playwright + Axios accelerator in testhub-api-quality-accelerator/, and
# one testhub-<x>-quality-accelerator folder per standalone framework, all
# siblings. Two roots follow from that. STUDIO_ROOT is the parent folder, and
# every relative path — Paths dialog, engine defaults — resolves against it,
# so a path names its accelerator explicitly. REPO_ROOT stays the API
# accelerator: where Playwright runs, where Ortoni writes, where Smart Run
# heals. Found by walking up from wherever the Studio is running (source
# checkout or the compiled binary under dist/<platform>/), so the layout is
# load-bearing and a binary dropped somewhere else says so rather than guessing.
API_DIR_NAME = 'testhub-api-quality-accelerator'

def _find_studio_root(start: Path) -> Path | None:
    for base in [start] + list(start.parents):
        if (base / API_DIR_NAME).is_dir() or (base / 'testhubui').is_dir():
            return base
    return None

STUDIO_ROOT = _find_studio_root(APP_DIR) or _find_repo_root(APP_DIR)
REPO_ROOT = (STUDIO_ROOT / API_DIR_NAME) if (STUDIO_ROOT / API_DIR_NAME).is_dir() \
    else _find_repo_root(APP_DIR)

def abspath(rel_or_abs: str) -> str:
    """Resolve a Paths-dialog value against the STUDIO root, so a relative path
    names its accelerator (testhub-api-quality-accelerator/src/tests, …)."""
    p = Path(rel_or_abs)
    return str(p if p.is_absolute() else (STUDIO_ROOT / p))

app = Flask(__name__, static_folder=str(STATIC_DIR))
DRAFT_FILE = APP_DIR / 'drafts' / 'draft.json'


# ───────────────────────── SEC-4: CSRF defence ─────────────────────────
#
# Binding to 127.0.0.1 is NOT protection: the attacker's request comes FROM the
# tester's own browser, which is already inside the loopback boundary. Any page
# they had open could drive /api/run — and combined with the shell interpolation
# in runner.py (SEC-5) that was remote code execution on a tester's laptop.
#
# What made it exploitable: `request.get_json(force=True)` parses a body
# regardless of Content-Type, so a cross-origin POST with `text/plain` qualifies
# as a CORS "simple request" and is sent WITHOUT a preflight the browser could
# block. Verified: a text/plain POST with an evil Origin spawned a process.
#
# Two independent gates, both required:
#   1. Content-Type must be exactly application/json  -> no longer a simple
#      request, so the browser must preflight, and we never answer preflights.
#   2. Origin/Referer, when present, must be a loopback origin.

_ALLOWED_HOSTS = {'127.0.0.1', 'localhost', '[::1]'}


def _origin_is_local(value: str) -> bool:
    if not value:
        return False
    try:
        from urllib.parse import urlparse
        host = urlparse(value).hostname
    except Exception:
        return False
    return host in _ALLOWED_HOSTS


@app.before_request
def _guard_state_changing_requests():
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    ctype = (request.content_type or '').split(';')[0].strip().lower()
    if ctype != 'application/json':
        return jsonify({'ok': False,
                        'error': 'Content-Type must be application/json'}), 415
    origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if origin and not _origin_is_local(origin):
        return jsonify({'ok': False, 'error': 'cross-origin request rejected'}), 403
    return None


@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.post('/api/draft')
def save_draft():
    data = request.get_json(silent=True) or {}
    DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRAFT_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return jsonify({'ok': True, 'saved': str(DRAFT_FILE)})


@app.get('/api/draft')
def load_draft():
    if DRAFT_FILE.exists():
        return jsonify({'ok': True, 'draft': json.loads(DRAFT_FILE.read_text(encoding='utf-8'))})
    return jsonify({'ok': True, 'draft': None})


@app.delete('/api/draft')
def clear_draft():
    DRAFT_FILE.unlink(missing_ok=True)
    return jsonify({'ok': True})


@app.post('/api/generate')
def generate_assets():
    data = request.get_json(silent=True) or {}
    engine_id = (data.get('engine') or 'api').lower()

    # The draft fallback and the assetName/serviceName pair are API-engine rules
    # — the Salesforce engine keys off sfObject and has no serviceName at all, so
    # these must not gate every engine.
    if engine_id == 'api':
        # if the page sends nothing (e.g. generate straight after restart), fall back to the saved draft
        if not data.get('assetName') and DRAFT_FILE.exists():
            data = json.loads(DRAFT_FILE.read_text(encoding='utf-8'))
        if not data.get('assetName') or not data.get('serviceName'):
            return jsonify({'ok': False, 'error': 'Asset Name and Service Name are required'}), 400

    # Resolve the Paths-dialog values against the accelerator root so assets
    # land where the framework can import them (not inside testhubui/).
    if isinstance(data.get('paths'), dict):
        data['paths'] = {k: abspath(v) for k, v in data['paths'].items()}

    # Engine dispatch. 'api' keeps the original code path byte for byte — the
    # accelerator is in pilot and must not regress. Everything else goes to the
    # registry.
    if engine_id != 'api':
        eng = engines.get(engine_id)
        if eng is None:
            return jsonify({'ok': False, 'error': f'unknown engine: {engine_id}'}), 400
        ready, reason = eng.preflight()
        if not ready:
            return jsonify({'ok': False, 'error': reason}), 409
        try:
            rows = eng.build_matrix(data)
            if not rows:
                return jsonify({'ok': False, 'error': 'No scenarios derived — capture at least one step and one scenario type.'}), 400
            bundle = eng.render(data, rows)
            # An engine's default output dir is relative ('perf', 'mobile', …).
            # Resolve those against the accelerator ROOT, never the Flask process
            # CWD — otherwise assets land inside testhubui/. Done here, once, so
            # every engine inherits it instead of each remembering.
            bundle.files = {
                (p if p.is_absolute() else Path(STUDIO_ROOT) / p): c
                for p, c in bundle.files.items()
            }
            files = engines.write(bundle, overwrite=bool(data.get('overwrite')))
            merged = _apply_extras(bundle)
        except engines.WouldClobber as e:
            # 409, not 400: the request is well-formed, the tree is not in a
            # state where it can be honoured. The client can retry the exact
            # same body with overwrite:true once a human has decided.
            return jsonify({'ok': False, 'error': str(e),
                            'wouldClobber': e.paths}), 409
        except ValueError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        except PermissionError as e:
            return jsonify({'ok': False, 'error': f'Cannot write to path: {e}'}), 500
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
        return jsonify({'ok': True, 'engine': engine_id, 'rows': bundle.rows,
                        'sheet': bundle.sheet, 'files': files,
                        'packageScripts': merged})

    try:
        result = generate(data)
    except engines.WouldClobber as e:
        # Same contract as the engine branch above — see the comment there.
        return jsonify({'ok': False, 'error': str(e),
                        'wouldClobber': e.paths}), 409
    except PermissionError as e:
        return jsonify({'ok': False, 'error': f'Cannot write to path: {e}'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify(result)


@app.post('/api/preview')
def api_preview():
    """Derive scenarios WITHOUT writing anything.

    The Studio's "Derived Scenarios" list calls this, so what a tester reviews is
    produced by the same build_matrix() that generation uses. Re-implementing the
    matrix in JavaScript is how a preview quietly stops matching the output —
    which would make "displayed before you run, never a black box" untrue.
    """
    data = request.get_json(silent=True) or {}
    eng = engines.get((data.get('engine') or '').lower())
    if eng is None:
        return jsonify({'ok': False, 'error': 'unknown engine'}), 400
    try:
        rows = eng.build_matrix(data)
    except ValueError as e:
        return jsonify({'ok': True, 'rows': [], 'blocked': str(e)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'rows': [
        {'name': r.name, 'kind': r.kind, 'detail': r.detail} for r in rows]})


def _apply_extras(bundle) -> list[str]:
    """Side effects an engine asked for beyond its files. Today: the perf engine's
    three npm scripts (<slug>:gen/:smoke/:<profile>) merged into the performance
    accelerator's package.json — what the client's new-endpoint scaffold does, so a
    Studio-generated endpoint runs with the same `npm run` theirs do. Idempotent:
    keys are set to the same strings every time; nothing else in the file moves.
    Editing his file lives here, not in render(), which stays pure (afc rule)."""
    scripts = (bundle.extras or {}).get('npmScripts') or {}
    target = (bundle.extras or {}).get('packageJson')
    if not scripts or not target:
        return []
    pkg = Path(abspath(target))
    if not pkg.is_file():
        return []
    try:
        doc = json.loads(pkg.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []
    current = doc.setdefault('scripts', {})
    if all(current.get(k) == v for k, v in scripts.items()):
        return list(scripts)
    current.update(scripts)
    pkg.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    return list(scripts)


@app.get('/api/engines')
def api_engines():
    """Honest capability catalogue — drives the rail's badges.

    `ready` reflects what this machine can actually do right now, so a missing
    runtime shows as a clear reason instead of a failed run.
    """
    return jsonify({'ok': True, 'engines': engines.catalog()})


CANDIDATE_PORTS = (5000, 5050, 8000)


def _free_port(preferred=5000):
    import socket
    for port in (*CANDIDATE_PORTS, 0):
        try:
            s = socket.socket()
            s.bind(('127.0.0.1', port))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            continue
    return preferred


def _studio_on(port: int) -> bool:
    """Is a TestHub Studio — not merely *something* — listening on this port?

    AVL-1: the old check probed only 5000 and treated ANY HTTP 200 as "the Studio
    is up", while _free_port() might bind 5050, 8000 or a random port. Starting
    twice therefore gave two instances on different ports writing the same
    drafts/draft.json, with neither aware of the other. Observed in practice.

    Now: probe every port the Studio could have chosen, and verify the response is
    actually ours before reusing it.
    """
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/engines', timeout=1) as r:
            if r.status != 200:
                return False
            body = _json.loads(r.read().decode('utf-8', 'replace'))
            return isinstance(body, dict) and 'engines' in body
    except Exception:
        return False


def _find_running_studio() -> int | None:
    for port in CANDIDATE_PORTS:
        if _studio_on(port):
            return port
    return None


def main():
    import threading, webbrowser
    # TESTHUB_PORT forces a specific port AND bypasses the reuse guard below.
    # Verification (build-protected.sh, package-release.sh) needs to prove THIS
    # binary serves, but the guard makes any second instance defer to a Studio
    # already on 5000/5050/8000 — so a stale `python app.py` would answer the
    # check instead of the binary, and the build would verify the wrong process.
    # A pinned port the guard never considers removes that entirely.
    forced = os.environ.get('TESTHUB_PORT')
    if forced:
        port = int(forced)
        url = f'http://127.0.0.1:{port}'
        print(f'TestHub Automation Studio → {url}  (TESTHUB_PORT, no browser, no reuse)')
        print(f'  studio root: {STUDIO_ROOT}\n  api accelerator: {REPO_ROOT}')
        app.run(host='127.0.0.1', port=port, debug=False)
        return
    running = _find_running_studio()
    if running:
        url = f'http://127.0.0.1:{running}'
        webbrowser.open(url)
        print(f'TestHub Automation Studio is already running at {url} — opened it in your browser.')
        print('Refusing to start a second instance: two Studios would share one drafts/draft.json.')
        return
    port = _free_port(5000)
    url = f'http://127.0.0.1:{port}'
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f'TestHub Automation Studio → {url}  (close this window to stop)')
    app.run(host='127.0.0.1', port=port, debug=False)


# ───────────── Test Runner API ─────────────

def _contained(candidate: Path, root: Path = None) -> Path | None:
    """Resolve `candidate` and return it ONLY if it lives under the repo root.

    SEC-1/2/3. Containment must be checked against a SERVER-controlled root.
    Every earlier version of this let the caller supply the base — via ?root= or
    via ?spec= doubling as the allow-list — which makes the check validate a path
    against a base the attacker chose. `?root=/etc&path=hosts` returned /etc/hosts;
    `?spec=/` read any .ts on disk.

    is_relative_to(), not startswith(): '/repo/src/tests-evil' has the string
    prefix '/repo/src/tests' but is not inside it.
    """
    base = (root or Path(STUDIO_ROOT)).resolve()
    try:
        resolved = Path(candidate).resolve()
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_relative_to(base) else None


@app.get('/api/tests')
def api_tests():
    spec = request.args.get('spec', '')
    req = request.args.get('request', '') or None
    perf = request.args.get('perf', '') or None
    if not spec:
        return jsonify({'ok': False, 'error': 'spec path required'}), 400
    spec_p = _contained(abspath(spec))
    req_p = _contained(abspath(req)) if req else None
    if spec_p is None:
        return jsonify({'ok': False, 'error': 'path outside the accelerator root'}), 403
    # perf is a Paths-dialog value the tester configured directly, not
    # arbitrary caller input — the whole point is that it can live anywhere
    # (a different drive, a renamed folder), same trust level /api/generate
    # already gives every path in that dialog when it writes there. No
    # STUDIO_ROOT containment on this one.
    perf_p = abspath(perf) if perf else None
    try:
        data = runner.list_assets(str(spec_p), str(req_p) if req_p else None, perf_p)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, **data})


@app.get('/api/tests/file')
def api_tests_file():
    # SEC-2: the caller no longer supplies the allow-list. The only readable
    # region is the repo root, derived server-side; ?spec=/ is now meaningless.
    target = _contained(abspath(request.args.get('path', '')))
    if target is None or target.suffix != '.ts' or not target.is_file():
        return jsonify({'ok': False, 'error': 'file not readable'}), 404
    return jsonify({'ok': True, 'content': target.read_text(encoding='utf-8', errors='replace')})


@app.post('/api/run')
def api_run():
    data = request.get_json(silent=True) or {}
    rel = data.get('rel')
    env = data.get('environment', 'dev')
    # Always run from the accelerator root — that's where node_modules,
    # playwright.config.ts and cross-env live. Ignore any frontend-derived root.
    root = str(REPO_ROOT)
    if not rel:
        return jsonify({'ok': False, 'error': 'rel test path required'}), 400
    run_id = runner.start_run(rel, env, root)
    return jsonify({'ok': True, 'runId': run_id})


@app.post('/api/smart-run')
def api_smart_run():
    """Smart Run: capture -> heal the excel -> verify -> evidence.

    Ported from the reference accelerator; rules in SMART-RUN.md. A proxy URL accepts
    any status, a non-proxy URL accepts below 500, and a 5xx on a non-proxy URL
    becomes a documented defect that is kept OUT of the excel.

    dev / sit / uat / prod only, never mock — enforced here and again in
    runner.start_smart_run, because healing rewrites the governed sheet from what
    a live service returned and a mock would teach the sheet the mock's answers.

    Note the root: his version takes repoRoot from the request body. This one does
    not, for the same reason /api/run does not — a caller-supplied root is a way
    out of the repo, and the run has to happen where node_modules and
    playwright.config.ts actually live.
    """
    data = request.get_json(silent=True) or {}
    rel = data.get('rel')
    env = data.get('environment', 'dev')
    if not rel:
        return jsonify({'ok': False, 'error': 'rel test path required'}), 400
    if str(env).lower() not in runner.HEAL_ENVIRONMENTS:
        return jsonify({
            'ok': False,
            'error': f'Smart Run applies on '
                     f'{", ".join(sorted(e.upper() for e in runner.HEAL_ENVIRONMENTS))} only, '
                     f'never MOCK. Selected: {str(env).upper()}. '
                     f'Use Execute Tests for this environment.'}), 400
    return jsonify({'ok': True, 'runId': runner.start_smart_run(rel, env, str(REPO_ROOT))})


@app.get('/api/run/<run_id>/stream')
def api_run_stream(run_id):
    return Response(runner.stream(run_id), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/run/<run_id>/stop')
def api_run_stop(run_id):
    return jsonify({'ok': runner.stop_run(run_id)})


@app.get('/api/report')
def api_report():
    """
    Serve the Ortoni HTML report so Generated Tests can open it after a run.
    Prefers the path parsed from the run output; otherwise serves the newest
    .html found under the repo's ortoni-report / playwright-report folders.
    """
    # SEC-1: the `root` query parameter is GONE. It used to become the
    # containment base, so `?root=/etc&path=hosts` served /etc/hosts — the guard
    # below validated the path against a base the caller chose. The base is now
    # always the server's REPO_ROOT — which is also what runner._resolve_report()
    # anchors every returned `report` path against (including its cross-
    # accelerator copy-fallback), so this has to match that, not STUDIO_ROOT
    # (one level up). Mismatched, a report from any standalone accelerator
    # (k6, mobilewright, …) resolved to a path one directory too shallow and
    # 404'd even though the file existed right where the run said it would.
    rel = request.args.get('path', '')
    base = Path(REPO_ROOT).resolve()

    # EVID-1: the "newest HTML under ortoni-report/playwright-report/reports"
    # fallback is GONE. It fired whenever the runner could not name a report,
    # which was every k6, ZAP, garak and mobilewright run, because the only
    # resolution was a regex shaped for Ortoni's stdout line. The result was a
    # PREVIOUS Playwright run's Ortoni report presented as this run's evidence:
    # a green report over a gate that never ran, and the reason each framework
    # looked like it had no report of its own. runner._resolve_report now finds
    # each tool's own HTML where that tool writes it, anchored on the run's start
    # time. No path, no report.
    if not rel:
        return jsonify({'ok': False, 'error': 'no report path given for this run'}), 404
    p = Path(rel)
    candidate = _contained(p if p.is_absolute() else (base / rel))

    if not candidate or not candidate.exists():
        return jsonify({'ok': False, 'error': 'report not found'}), 404
    # Belt and braces: _contained() already enforced this for the ?path= branch,
    # and the fallback only walks dirs under `base` — but re-check, because this
    # is the line that actually hands bytes to the caller.
    if _contained(candidate) is None or candidate.suffix.lower() != '.html':
        return jsonify({'ok': False, 'error': 'report outside repo'}), 403
    return send_from_directory(candidate.parent, candidate.name)


# ── Agentforce Configuration ────────────────────────────────────────────────
#
# MoM points 3-5, 30 Aug 2026. These are separate endpoints rather than part of
# /api/generate on purpose: generate WRITES NEW ASSETS into this repo, whereas
# this EDITS a hand-written file inside the team's agentforce-testing-framework.
# Merging needs the file's current contents, and engines/render() must stay pure
# (see docs/DECISIONS.md), so the read-merge-write lives here — the caller's job.

def _afc_config_path(root: str) -> Path | None:
    """agentforce.config.ts under a caller-supplied repo root.

    The root is never defaulted and never guessed. An empty one returns None so
    the caller reports "no path" rather than this creating a phantom config
    somewhere under REPO_ROOT that no framework will ever read.
    """
    root = str(root or '').strip()
    if not root:
        return None
    base = Path(root).expanduser()
    if not base.is_absolute():
        return None
    return base / 'agentforce.config.ts'


@app.get('/api/agentforce/config')
def api_afc_read():
    """What the file declares today, so the UI shows the real keys, not a guess."""
    from engines.agentforce_config import parse_suites

    path = _afc_config_path(request.args.get('root', ''))
    if path is None:
        return jsonify({'ok': False, 'error': 'Give an absolute path to the '
                                              'agentforce-testing-framework repo.'}), 400
    if not path.is_file():
        return jsonify({'ok': False, 'error': f'No agentforce.config.ts at {path}'}), 404
    try:
        text = path.read_text(encoding='utf-8')
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Cannot read {path}: {e}'}), 500
    return jsonify({'ok': True, 'path': str(path), 'suites': parse_suites(text)})


@app.post('/api/agentforce/config')
def api_afc_update():
    """Update-or-append the suites, preserving everything else in the file."""
    from engines.agentforce_config import ConfigError, merge_suites

    data = request.get_json(silent=True) or {}
    path = _afc_config_path(data.get('frameworkRoot', ''))
    if path is None:
        return jsonify({'ok': False, 'error': 'Give an absolute path to the '
                                              'agentforce-testing-framework repo.'}), 400
    if not path.is_file():
        # Never created. A config the framework has not declared is one this
        # Studio would be inventing, and a run against it proves nothing.
        return jsonify({'ok': False, 'error': f'No agentforce.config.ts at {path}. '
                                              'This edits an existing file; it does not create one.'}), 404

    eng = engines.get('afc')
    try:
        rows = eng.build_matrix(data)                  # validates keys before touching disk
        text = path.read_text(encoding='utf-8')
        merged, report = merge_suites(text, [r.data for r in rows])
    except (ValueError, ConfigError) as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Cannot read {path}: {e}'}), 500

    if merged == text:
        return jsonify({'ok': True, 'path': str(path), 'changed': False, 'report': report})

    # A .bak beside it before the first write of a session. This file is
    # hand-maintained in someone else's repo and is not ours to lose; the
    # overwrite guard cannot help here because editing it IS the operation.
    backup = path.with_suffix('.ts.testhub-bak')
    try:
        if not backup.exists():
            backup.write_text(text, encoding='utf-8')
        path.write_text(merged, encoding='utf-8')
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Cannot write {path}: {e}'}), 500
    return jsonify({'ok': True, 'path': str(path), 'changed': True,
                    'backup': str(backup), 'report': report})


@app.post('/api/agentforce/run')
def api_afc_run():
    """Run Selected / Run All against QA or UAT.

    Wired end to end and deliberately inert: the MoM records that the QA/UAT
    command is the client's to supply and it has not arrived. Refusing with the reason
    is the honest answer — inventing a command here would run something unknown
    against a live Salesforce org.
    """
    from engines.agentforce_config import ENVIRONMENTS, command_for, validate_key

    data = request.get_json(silent=True) or {}
    env = str(data.get('environment') or '').upper()
    if env not in ENVIRONMENTS:
        return jsonify({'ok': False, 'error': f'Pick an environment: {", ".join(ENVIRONMENTS)}'}), 400
    try:
        keys = [validate_key(k) for k in (data.get('keys') or [])]
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if not keys:
        return jsonify({'ok': False, 'error': 'No suites selected. Use Run All to run every '
                                              'key declared in agentforce.config.ts.'}), 400

    argv = command_for(env, keys)
    if not argv:
        return jsonify({
            'ok': False,
            'pending': True,
            'error': f'No {env} command is configured yet. The 30 Aug MoM records this as '
                     f'the client\'s to supply. Add it to COMMANDS in '
                     f'testhubui/engines/agentforce_config.py and this runs as-is.',
            'wouldRun': {'environment': env, 'keys': keys},
        }), 409

    path = _afc_config_path(data.get('frameworkRoot', ''))
    if path is None or not path.is_file():
        return jsonify({'ok': False, 'error': 'Set the framework repo path before running.'}), 400

    # MoM point 6 — View Results in Ortoni Report. The framework is Playwright-based,
    # so Ortoni is where its own report lands; resolution is anchored on this run's
    # start time inside that repo, the same rule every other framework follows here.
    # If it writes none, the run says so rather than surfacing an earlier one.
    run_id = runner.start_argv(
        argv, cwd=str(path.parent),
        report_globs=('ortoni-report/**/*.html', 'playwright-report/**/*.html'),
        report_label='Ortoni')
    return jsonify({'ok': True, 'runId': run_id})


if __name__ == '__main__':
    main()
