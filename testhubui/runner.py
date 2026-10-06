"""
TestHub Automation Studio — test runner.

Discovers .data.ts / .test.ts files inside the framework paths and executes
Playwright specs with live, line-by-line output streaming (SSE) so the
frontend can render a real CLI view.

Command executed (exactly as specified, placeholders filled from the UI):
    npx cross-env ENVIRONMENT=<env> playwright test src/tests/<asset>/<service>.test.ts
run from the framework repo root (derived from the configured Test Script path).
"""

from __future__ import annotations   # keep signatures un-evaluated.
# Without this, `X | None` in a signature is evaluated at def time and the
# module simply will not import below Python 3.10 — the Studio would fail to
# start, not degrade. Costs nothing and removes a version constraint nobody
# chose. Note the docs still say 3.10+: that is the version actually tested,
# and this import alone is not evidence 3.9 works end to end.

import json
import os
import re
import queue
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

import heal          # Smart Run: the accept/defect decision and the excel edit

ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')

RUNS = {}          # run_id -> {'proc', 'queues', 'done', 'exit', 'lines', 'report'}

# REL-2: RUNS grew forever — every process handle, queue and captured line was
# retained for the life of the Studio. Completed runs are evicted oldest-first
# once the cap is reached, so a long session cannot leak indefinitely.
MAX_RETAINED_RUNS = 20

# REL-4: a hung Playwright run used to occupy its slot forever. Hard ceiling.
RUN_TIMEOUT_S = int(os.environ.get('TESTHUB_RUN_TIMEOUT_S', '1800'))


def _evict_finished_runs() -> None:
    finished = [rid for rid, r in RUNS.items() if r.get('done')]
    while len(RUNS) > MAX_RETAINED_RUNS and finished:
        RUNS.pop(finished.pop(0), None)




# ───────────────────── executable asset kinds ─────────────────────
#
# The Studio emits assets for nine engines, but this runner could only ever
# execute ONE of them: `npx playwright test`. A client could generate a k6
# script, a ZAP plan or a garak scan and then have no way to run it from the
# Studio at all — they had to drop to a terminal, which defeats the point of a
# governed workspace.
#
# Each kind declares how to FIND its assets and how to RUN them. Adding a tenth
# engine means adding a row here, not editing the runner.
#
# `cmd` receives (path_to_asset, repo_root, env_name) and returns argv.
# `probe` reports whether the runtime is present, so the UI can say "k6 is not
# installed" instead of failing a run.

def _accelerator_script(asset: str) -> str:
    """tests/<slug>/<slug>-<profile>-test.js  ->  <slug>:<profile>"""
    stem = Path(asset).name[:-len('-test.js')]
    slug, _, profile = stem.rpartition('-')
    return f'{slug}:{profile}'


def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _garak_bin():
    """garak is deliberately installed OUTSIDE the Studio venv (it pulls torch),
    so it is usually not on the Studio process's PATH. Look where the common
    isolated-install tools put it before giving up."""
    found = _which('garak')
    if found:
        return found
    home = Path.home()
    for c in (home / '.venvs/garak/bin/garak',
              home / '.local/bin/garak',                      # pipx / uv tool
              home / '.local/pipx/venvs/garak/bin/garak'):
        if c.is_file():
            return str(c)
    return None


def _zap_bin():
    # zap.bat is the Windows launcher — see SecurityZapEngine.LAUNCHERS. The
    # runner probes independently of the engine, so it has to know this too.
    for launcher in ('zap.sh', 'zap.bat'):
        found = _which(launcher)
        if found:
            return found
    for p in ('/Applications/ZAP.app/Contents/Java/zap.sh',
              '/Applications/OWASP ZAP.app/Contents/Java/zap.sh'):
        if Path(p).is_file():
            return p
    return None


ASSET_KINDS = {
    'playwright': {
        'label': 'Playwright',
        'globs': ('*.test.ts', '*.spec.ts'),
        'probe': lambda: _which('npx'),
        'cmd': lambda f, root, env: [_which('npx'), 'cross-env', f'ENVIRONMENT={env}',
                                     'playwright', 'test', f],
        # Ortoni IS this framework's own standard report, not a wrapper around one.
        'report_label': 'Ortoni',
        'reports': lambda f, root: ['ortoni-report/**/*.html', 'playwright-report/**/*.html'],
    },
    'k6': {
        'label': 'k6 performance',
        'globs': ('*.k6.js',),
        'probe': lambda: _which('k6'),
        'cmd': lambda f, root, env: [_which('k6'), 'run', f],
        # handleSummary() in the emitted script writes these beside the run.
        'report_label': 'k6',
        'reports': lambda f, root: ['perf-report-*.html'],
    },
    'k6-accelerator': {
        # The client's testhub-performance-quality-accelerator: tests/<slug>/<slug>-<profile>-test.js
        # read the compiled JSON beside them, so the run IS the npm script the Studio
        # merged into his package.json — gen first, then k6. cwd resolves to the
        # accelerator root (nearest package.json), which is where npm needs to be.
        'label': 'k6 (performance accelerator)',
        'globs': ('*-smoke-test.js', '*-load-test.js', '*-stress-test.js', '*-spike-test.js', '*-soak-test.js'),
        'probe': lambda: _which('k6') and _which('npm.cmd', 'npm'),
        'cmd': lambda f, root, env: [_which('npm.cmd', 'npm'), 'run', _accelerator_script(f)],
        'report_label': 'k6 html-reporter',
        # His buildSummary() writes reports/<reportName>.html at the accelerator root.
        'reports': lambda f, root: ['reports/*.html'],
    },
    'zap': {
        'label': 'OWASP ZAP scan',
        'globs': ('*.zap.yaml',),
        'probe': _zap_bin,
        'cmd': lambda f, root, env: [_zap_bin(), '-cmd', '-autorun', str(Path(root) / f)],
        # ZAP resolves a relative reportFile against its OWN install directory,
        # not the working directory, so look there too. _resolve_report copies
        # anything found outside the repo into reports/ rather than serving it
        # from outside the containment boundary.
        'report_label': 'ZAP',
        'reports': lambda f, root: ['zap-report-*.html',
                                    str(Path(f).parent / 'zap-report-*.html'),
                                    *( [str(Path(_zap_bin()).parent / 'zap-report-*.html')]
                                       if _zap_bin() else [] )],
    },
    'garak': {
        'label': 'garak LLM scan',
        'globs': ('*.garak.sh',),
        # bash alone is not enough — the script needs garak itself.
        'probe': lambda: _garak_bin() and _which('bash'),
        'cmd': lambda f, root, env: [_which('bash'), f],
        # OUT_DIR defaults to $SCRIPT_DIR/garak-runs inside the emitted script.
        'report_label': 'garak',
        'reports': lambda f, root: [str(Path(f).parent / 'garak-runs' / '*.report.html')],
        # The emitted script honours GARAK_BIN, which is exactly how it tells you
        # to resolve an isolated install. Hand it the path we found.
        'env': lambda: {'GARAK_BIN': _garak_bin() or ''},
    },
    'mobilewright': {
        'label': 'Mobilewright mobile',
        # The workspace is identified by its config, not by the spec files —
        # mobilewright runs a whole project, and the specs are plain *.test.ts
        # which would otherwise be mistaken for Playwright.
        'globs': ('mobilewright.config.ts',),
        'probe': lambda: _which('npx'),
        # Runs IN the generated workspace, which has its own node_modules: the
        # accelerator cannot host it (@mobilewright/test bundles a conflicting
        # @playwright/test). cwd is therefore the config's directory.
        'cmd': lambda f, root, env: [_which('npx'), 'mobilewright', 'test'],
        'cwd': lambda f, root: str((Path(root) / f).parent),
        # Mobile is the one engine that cannot host Ortoni, so mobilewright's own
        # HTML is the evidence. Patterns resolve against the run cwd, which for
        # this kind is the generated workspace.
        'report_label': 'mobilewright',
        # The workspace sets reporter ['html', {open:'never'}] with no outputFolder,
        # so this is the reporter's default. The committed evidence in
        # samples/reports/mobile/index.html is a 'Mobilewright Test Report' single
        # HTML file, consistent with that. Unverified against a live device run:
        # the extra patterns are there so a different output folder still resolves.
        'reports': lambda f, root: ['playwright-report/**/*.html',
                                    'mobilewright-report/**/*.html',
                                    'test-results/**/*.html'],
    },
    'agentforce': {
        'label': 'Agentforce test spec',
        'globs': ('*.agentforce-test.yaml',),
        'probe': lambda: _which('sf'),
        'cmd': lambda f, root, env: [_which('sf'), 'agent', 'test', 'create',
                                     '--spec', f, '--preview', '--api-name', 'TestHub_Preview'],
        # `sf agent test run` has no HTML format at all; scripts/agentforce-report.py
        # renders the CLI's JSON. Nothing is produced by this command, and saying so
        # is better than pointing at another framework's report.
        'report_label': 'Agentforce',
        'reports': lambda f, root: [],
    },
}


def _resolve_report(kind: str, rel: str, repo_root: str, run_cwd: str,
                    started: float) -> str | None:
    """The report THIS run produced, found where the tool itself writes it.

    Every framework here already emits its own standard report: k6 writes an HTML
    digest from handleSummary(), ZAP and garak write theirs, mobilewright writes a
    Playwright HTML report, and for the Playwright-native suites Ortoni IS the
    framework's own report rather than a wrapper around one. What was missing was
    a way to FIND them: the only resolution was a regex over stdout shaped for
    Ortoni's "Report generated at" line, which no other tool prints. Verified
    against a real k6 run: 108 lines of output, zero matches.

    Resolution is anchored on mtime >= run start. A file older than the run is a
    previous run's evidence, and serving it would put a green report over a gate
    that never ran, which is a failure this repo has already recorded once.
    """
    spec = ASSET_KINDS.get(kind) or {}
    patterns = spec.get('reports')
    if not patterns:
        return None
    root = Path(repo_root).resolve()
    base = Path(run_cwd).resolve()
    newest, newest_m = None, started
    for pattern in patterns(rel, repo_root):
        pat = Path(pattern)
        anchor_dir, glob = (pat.parent, pat.name) if pat.is_absolute() else (base, pattern)
        try:
            matches = list(anchor_dir.glob(glob))
        except (OSError, ValueError):
            continue
        for f in matches:
            if f.suffix.lower() != '.html':
                continue
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            if m >= newest_m:
                newest, newest_m = f, m
    if newest is None:
        return None
    resolved = newest.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        # Outside the repo. ZAP resolves a relative reportFile against its own
        # install directory, so its HTML can land there. Copy it in rather than
        # loosening the containment check on the serving side.
        dest_dir = root / 'reports'
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / resolved.name
        shutil.copy2(resolved, dest)
        return str(dest.relative_to(root))


def kind_for(path: str) -> str | None:
    """Which runner handles this asset? Most specific suffix wins — a
    '.mobile.spec.ts' is Playwright-shaped but belongs to wdio via its caps file,
    so order matters and the compound suffixes are checked first."""
    name = Path(path).name
    for kind, spec in ASSET_KINDS.items():
        if kind == 'playwright':
            continue
        for g in spec['globs']:
            if name.endswith(g.lstrip('*')):
                return kind
    for g in ASSET_KINDS['playwright']['globs']:
        if name.endswith(g.lstrip('*')):
            return 'playwright'
    return None


def runtime_status() -> dict:
    """kind -> {label, available, hint}. Drives honest UI badges."""
    hints = {
        'k6': 'brew install k6  (Windows: winget install k6 · Linux: see k6.io/docs)',
        'zap': 'brew install --cask zap, or run via Docker',
        'garak': 'pipx install garak (pulls torch, ~1.5 GB)',
        'wdio': 'npm i -D @wdio/cli, plus a booted device',
        'agentforce': 'npm i -g @salesforce/cli and authenticate an org',
        'playwright': 'install Node.js 18+',
    }
    out = {}
    for kind, spec in ASSET_KINDS.items():
        ok = bool(spec['probe']())
        out[kind] = {'label': spec['label'], 'available': ok,
                     'hint': '' if ok else hints.get(kind, '')}
    return out


# ───────────────────────── discovery ─────────────────────────

def repo_root_from_spec(spec_path: str) -> Path:
    """
    C:/.../testhub-api-quality-accelerator/src/tests → repo root is the folder
    containing 'src'. Fallback: two levels up from the tests folder.
    """
    p = Path(spec_path)
    for parent in [p] + list(p.parents):
        if parent.name.lower() == 'src':
            return parent.parent
    return p.parent.parent if len(p.parents) >= 2 else p


def list_assets(spec_path: str, request_path: str | None = None,
                perf_path: str | None = None) -> dict:
    """Walk the framework and return every RUNNABLE asset, of any engine.

    Previously this globbed '*.test.ts' only, so k6 scripts, ZAP plans, garak
    scans, Appium capability files and Agentforce specs were invisible in the
    Studio even though the engines had just written them.
    """
    root = repo_root_from_spec(spec_path)
    tests_dir = Path(spec_path)
    assets: dict = {}

    def add(f: Path, kind: str):
        group = f.parent.name if f.parent != root else '(root)'
        try:
            rel = f.relative_to(root).as_posix()
        except ValueError:
            rel = f.as_posix()
        entry = assets.setdefault(group, {'asset': group, 'tests': [], 'data': []})
        entry['tests'].append({
            'name': f.name,
            'service': re.sub(r'\.(test|spec|k6|caps|garak)\..*$|\.(ts|js|sh|yaml)$', '', f.name),
            'rel': rel, 'abs': str(f), 'kind': kind,
            'kindLabel': ASSET_KINDS[kind]['label'],
            'runnable': bool(ASSET_KINDS[kind]['probe']()),
            'mtime': int(f.stat().st_mtime),
        })

    # Two callers, two scopes. The API Test Automation view passes no perf_path
    # and must see ONLY its own Test Script folder — performance (or any other
    # engine's) assets never belong in the API accelerator's Generated Assets.
    # The generic-engine view passes perf_path (a Paths-dialog value, so a
    # relocated or renamed copy is searched wherever it actually is) and sees
    # the engine output dirs, never the API spec dir. Since 2026-09-06 each
    # standalone framework has its own sibling accelerator folder; the bare
    # root names are the pre-move defaults, kept so older assets still show up.
    if perf_path is None:
        search_dirs = [tests_dir]
    else:
        # root is the API accelerator; the other accelerators are its siblings.
        studio = root.parent if (root.parent / 'testhubui').is_dir() else root
        perf_root = Path(perf_path)
        search_dirs = [perf_root / 'studio', perf_root / 'tests'] + [studio / d for d in
                                     ('testhub-ui-quality-accelerator/tests',
                                      'testhub-ai-agentic-quality-accelerator/tests',
                                      'testhub-salesforce-quality-accelerator/tests',
                                      'testhub-security-quality-accelerator', 'testhub-mobile-quality-accelerator',
                                      'testhub-agentforce-quality-accelerator', 'testhub-llm-security-quality-accelerator',
                                      'testhub-contract-quality-accelerator',
                                      'perf', 'security', 'mobile', 'agentforce', 'llmsec', 'ai-agentic')]
    seen: set[str] = set()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob('*')):
            if not f.is_file() or str(f) in seen:
                continue
            kind = kind_for(f.name)
            if kind:
                seen.add(str(f))
                add(f, kind)

    if request_path and Path(request_path).is_dir():
        for f in sorted(Path(request_path).rglob('*.data.ts')):
            group = f.parent.name
            assets.setdefault(group, {'asset': group, 'tests': [], 'data': []})
            assets[group]['data'].append({'name': f.name, 'abs': str(f),
                                          'mtime': int(f.stat().st_mtime)})

    return {'repoRoot': str(root),
            'runtimes': runtime_status(),
            'assets': sorted(assets.values(), key=lambda a: a['asset'])}


def read_file(abs_path: str, spec_path: str, request_path: str | None) -> str | None:
    """Safe read: only .ts files inside the configured framework folders.

    SEC-3: containment was `str(p).startswith(str(a))`, which is a STRING prefix
    test, not a path test — '/repo/src/tests-evil/x.ts' passes as inside
    '/repo/src/tests'. `is_relative_to` compares path components.

    NOTE: app.py's /api/tests/file no longer calls this with caller-supplied
    roots (SEC-2); it validates against REPO_ROOT itself. This function is kept
    correct for any internal caller.
    """
    p = Path(abs_path).resolve()
    allowed = [Path(spec_path).resolve()]
    if request_path:
        allowed.append(Path(request_path).resolve())
    if not any(p.is_relative_to(a) for a in allowed):
        return None
    if p.suffix != '.ts' or not p.is_file():
        return None
    return p.read_text(encoding='utf-8', errors='replace')


# ───────────────────────── execution ─────────────────────────

def _resolve_npx() -> str | None:
    """Locate npx without a shell. On Windows it is npx.cmd, which is exactly
    what `shell=True` used to resolve for us."""
    for name in ('npx.cmd', 'npx') if os.name == 'nt' else ('npx',):
        found = shutil.which(name)
        if found:
            return found
    return None


def _project_root_for(asset: str, repo_root: str) -> str:
    """Where to run an asset from: the nearest ancestor that is a Playwright
    project (playwright.config.ts) or an npm package. The API accelerator is
    one such project; a standalone accelerator beside it is another, and an
    asset generated into it must run there, not from the API folder."""
    p = Path(asset)
    if p.is_absolute():
        for base in p.parents:
            if (base / 'playwright.config.ts').is_file() or (base / 'package.json').is_file():
                return str(base)
    return repo_root


def start_run(rel_test_path: str, environment: str, repo_root: str) -> str:
    """Spawn the playwright run; returns a run id whose output can be streamed.

    SEC-5: this used to build ONE STRING and hand it to `shell=True`, with
    `shlex.quote` applied only when `os.name != 'nt'`. On Windows the
    caller-supplied test path went in raw, so rel = 'x.test.ts & whoami'
    executed. Chained with the CSRF hole (SEC-4) that was remote code execution
    on a tester's machine — and Windows is a first-class target here
    (build_exe.bat, the PyInstaller spec, the .bat launcher all ship).

    Now: an argv list with shell=False. No quoting, no interpolation, no shell to
    inject into on any platform.

    REL-1: `shell=False` also fixes stop. Previously terminate() killed the shell
    and left npx/playwright orphaned. start_new_session puts the child in its own
    process group so stop_run can signal the whole tree.
    """
    env_name = re.sub(r'[^A-Za-z0-9_-]', '', environment or 'dev').lower()
    rel = rel_test_path.replace('\\', '/')

    run_id = uuid.uuid4().hex[:12]
    q = queue.Queue()
    npx = _resolve_npx()

    if npx is None and (kind_for(rel) or 'playwright') in ('playwright', 'wdio'):
        RUNS[run_id] = {'proc': None, 'queues': [], 'lock': threading.Lock(),
                        'lines': ['[runner] npx not found on PATH — install Node.js 18+'],
                        'done': True, 'exit': -1, 'report': None}
        return run_id

    kind = kind_for(rel) or 'playwright'
    spec = ASSET_KINDS[kind]
    if not spec['probe']():
        RUNS[run_id] = {'proc': None, 'queues': [], 'lock': threading.Lock(),
                        'lines': [f'[runner] {spec["label"]} runtime is not installed — '
                                  f'cannot run {rel}'],
                        'done': True, 'exit': -1, 'report': None}
        return run_id
    argv = spec['cmd'](rel, repo_root, env_name)

    q.put('$ ' + ' '.join(shlex.quote(a) for a in argv))   # display only
    q.put(f'  (cwd: {repo_root})')
    q.put('')

    child_env = dict(os.environ)
    child_env['FORCE_COLOR'] = '0'          # clean text for the CLI window
    child_env['CI'] = '1'                    # non-interactive playwright output
    extra = ASSET_KINDS[kind].get('env')
    if extra:
        child_env.update({k: v for k, v in extra().items() if v})

    popen_kw = {}
    if os.name != 'nt':
        popen_kw['start_new_session'] = True          # own process group -> killpg
    else:
        popen_kw['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

    started = time.time()          # report resolution is anchored on this
    try:
        cwd_fn = ASSET_KINDS[kind].get('cwd')
        run_cwd = cwd_fn(rel, repo_root) if cwd_fn else _project_root_for(rel, repo_root)
        proc = subprocess.Popen(
            argv,
            cwd=run_cwd,
            shell=False,                     # SEC-5 — never a shell
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=child_env,
            bufsize=1,
            **popen_kw,
        )
    except Exception as e:
        RUNS[run_id] = {'proc': None, 'queues': [], 'lock': threading.Lock(),
                        'lines': [f'[runner] failed to start: {e}'],
                        'done': True, 'exit': -1, 'report': None}
        return run_id

    # REL-3: one shared queue meant one consumer. Two browser tabs streaming the
    # same run each stole half the lines, and a reconnect lost everything already
    # drained. Every consumer now gets its own queue, fed from a replay buffer so
    # a late or reconnecting subscriber sees the run from the beginning.
    seeded = []
    while True:
        try:
            seeded.append(q.get_nowait())
        except queue.Empty:
            break

    RUNS[run_id] = {'proc': proc, 'queues': [], 'lines': list(seeded),
                    'done': False, 'exit': None, 'report': None,
                    'lock': threading.Lock()}
    _evict_finished_runs()

    report_re = re.compile(r'(?:Ortoni Report generated at|report[:\s]+)\s*(.+?\.html)', re.IGNORECASE)

    def _broadcast(run_id, item):
        run = RUNS.get(run_id)
        if not run:
            return
        with run['lock']:
            if item is not None:
                run['lines'].append(item)
            for cq in list(run['queues']):
                cq.put(item)

    def pump():
        deadline = time.monotonic() + RUN_TIMEOUT_S
        try:
            for line in proc.stdout:
                clean = ANSI.sub('', line.rstrip('\n'))
                m = report_re.search(clean)
                if m:
                    RUNS[run_id]['report'] = m.group(1).strip().strip('"')
                _broadcast(run_id, clean)
                if time.monotonic() > deadline:
                    # REL-4: hard ceiling. Kill the tree, do not just stop reading.
                    _broadcast(run_id, f'[runner] run exceeded {RUN_TIMEOUT_S}s — terminating')
                    stop_run(run_id)
                    break
            proc.wait()
        finally:
            run = RUNS.get(run_id)
            if run is not None:
                run['exit'] = proc.returncode
                run['done'] = True
                label = ASSET_KINDS.get(kind, {}).get('report_label') or 'Report'
                run['reportLabel'] = label
                if not run.get('report'):
                    try:
                        run['report'] = _resolve_report(kind, rel, repo_root,
                                                        run_cwd, started)
                    except Exception as e:                     # never fail a run over its report
                        _broadcast(run_id, f'[runner] could not resolve the {label} report: {e}')
                # State it either way. A run whose framework produced no report of
                # its own must say so, not quietly show another framework's.
                if run.get('report'):
                    _broadcast(run_id, f'[runner] {label} report: {run["report"]}')
                else:
                    _broadcast(run_id, f'[runner] this run produced no {label} report')
            _broadcast(run_id, None)         # end-of-stream sentinel
            _evict_finished_runs()

    threading.Thread(target=pump, daemon=True).start()
    return run_id


# ───────────────────────── Smart Run (heal) ─────────────────────────
#
# Ported 2026-08-30 from testhub-api-quality-accelerator's reference branch;
# the rules and artefacts are documented in SMART-RUN.md. Two passes:
# capture what the service ACTUALLY returns, heal the governed excel, then rerun
# for clean evidence. See heal.py for the accept/defect decision.
#
# The orchestration is his; the process handling deliberately is NOT. His _phase
# builds one shell string and runs it with shell=True, and keys RUNS on a single
# shared queue. This repo fixed both — SEC-5 (an interpolated test path executed
# on Windows) and REL-3 (one queue meant one consumer, so two tabs streaming a
# run each stole half the lines). Re-importing either to save a few lines would
# reintroduce a fixed vulnerability and a fixed reliability bug.
HEAL_ENVIRONMENTS = {'dev', 'sit', 'uat', 'prod'}   # sync: heal.py, healMode.ts


def _smart_phase(run_id: str, argv: list[str], repo_root: str,
                 extra_env: dict, emit, label: str) -> int:
    """One Playwright pass, streamed. argv + shell=False, as everywhere here."""
    emit('')
    emit(f'━━━ {label} ━━━')
    emit('$ ' + ' '.join(argv))
    emit('')

    child_env = dict(os.environ)
    child_env['FORCE_COLOR'] = '0'
    child_env['CI'] = '1'
    child_env.update(extra_env)

    popen_kw = {'start_new_session': True} if os.name != 'nt' else \
        {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)}
    try:
        proc = subprocess.Popen(
            argv, cwd=repo_root, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            env=child_env, bufsize=1, **popen_kw)
    except Exception as e:
        emit(f'[smart-run] failed to start phase: {e}')
        return -1

    RUNS[run_id]['proc'] = proc
    for line in proc.stdout:
        emit(ANSI.sub('', line.rstrip('\n')))
    proc.wait()
    RUNS[run_id]['proc'] = None
    return proc.returncode


def start_smart_run(rel_test_path: str, environment: str, repo_root: str) -> str:
    """Two-pass self-healing run. Returns a run id streamable like any other."""
    env_name = re.sub(r'[^A-Za-z0-9_-]', '', environment or 'dev').lower()
    rel = rel_test_path.replace('\\', '/')
    npx = _resolve_npx()
    argv = [npx, 'cross-env', f'ENVIRONMENT={env_name}', 'playwright', 'test', rel]

    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {'proc': None, 'queues': [], 'lines': [], 'lock': threading.Lock(),
                    'done': False, 'exit': None, 'report': None,
                    'reportLabel': 'Ortoni', 'stop': False}
    _evict_finished_runs()

    def emit(item):
        run = RUNS.get(run_id)
        if not run:
            return
        with run['lock']:
            if item is not None:
                run['lines'].append(item)
            for cq in list(run['queues']):
                cq.put(item)

    def finish(code):
        run = RUNS.get(run_id)
        if run is not None:
            run['exit'], run['done'] = code, True
        emit(None)
        _evict_finished_runs()

    def orchestrate():
        emit(f'⚡ Smart Run · {rel} · environment {env_name.upper()}')

        if npx is None:
            emit('[smart-run] blocked: npx not found on PATH.')
            return finish(2)
        # The gate is the point of the feature, not a guard around it: healing
        # rewrites the governed sheet from what a live service returned, so a
        # mock would teach the sheet the mock's answers.
        if env_name not in HEAL_ENVIRONMENTS:
            emit(f'[smart-run] blocked: Smart Run applies on '
                 f'{", ".join(sorted(e.upper() for e in HEAL_ENVIRONMENTS))} only, '
                 f'never MOCK. Selected: {env_name.upper()}.')
            emit('[smart-run] use the normal Execute Tests for this environment.')
            return finish(2)
        if 'mock' in Path(rel).name.lower():
            emit('[smart-run] blocked: mock suites are outside the Smart Run scope.')
            return finish(2)

        run_dir = Path(repo_root) / '.testhub' / 'heal' / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        code1 = _smart_phase(run_id, argv, repo_root,
                             {'HEAL_MODE': 'capture', 'HEAL_RUN_DIR': str(run_dir)},
                             emit, 'PASS 1 / 2 · capture actual statuses')
        if RUNS[run_id]['stop']:
            emit('[smart-run] stopped during pass 1; excel untouched')
            return finish(code1 if code1 is not None else -1)

        emit('')
        emit('━━━ HEAL · updating the excel from the captured statuses ━━━')
        try:
            summary = heal.apply(repo_root, run_dir, env_name, rel)
        except Exception as e:
            emit(f'[smart-run] heal step failed: {e}')
            return finish(-1)

        for u in summary['updated']:
            emit(f"  ✓ {u['workbook']} · {u['sheet']} · \"{u['row']}\": "
                 f"expectedStatus {u['old']} → {u['new']}" + (' · proxy' if u['proxy'] else ''))
        if summary['unchanged']:
            emit(f"  = {summary['unchanged']} row(s) already correct")
        for p5 in summary['proxy_5xx']:
            emit(f"  ! proxy row \"{p5['row']}\" returned HTTP {p5['status']} "
                 f"and was auto-accepted per the proxy rule")
        for d in summary['defects']:
            emit(f"  ✘ DEFECT {d['id']} · \"{d['row']}\" · {d['method']} {d['endpoint']} "
                 f"returned HTTP {d['status']} (kept out of the excel)")
        for w in summary['warnings']:
            emit(f'  ⚠ {w}')
        for u in summary['unmatched']:
            emit(f'  ⚠ could not locate excel row for "{u}"')
        if summary['report_html']:
            emit(f"  ▸ defect report: {summary['report_html']}")
        if not summary['updated'] and not summary['defects']:
            emit('  = nothing to heal; the sheet already matches the system')

        if RUNS[run_id]['stop']:
            emit('[smart-run] stopped before the verification pass')
            return finish(0)

        extra = {'HEAL_MODE': 'verify'}
        if summary['skip_file']:
            extra['HEAL_SKIP_FILE'] = summary['skip_file']
        pass2_started = time.time()
        code2 = _smart_phase(run_id, argv, repo_root, extra, emit,
                             'PASS 2 / 2 · verification + evidence')

        # Evidence resolution is this repo's rule, not his auto-open: anchored on
        # the pass-2 start so an earlier report can never be served as this run's,
        # and surfaced through the Studio's own report view rather than a browser
        # the Studio may not be running beside.
        run = RUNS.get(run_id)
        if run is not None:
            newest, newest_m = None, pass2_started
            base = Path(repo_root) / 'ortoni-report'
            if base.is_dir():
                for f in base.rglob('*.html'):
                    try:
                        m = f.stat().st_mtime
                    except OSError:
                        continue
                    if m >= newest_m:
                        newest, newest_m = f, m
            run['report'] = str(newest) if newest else None
            emit(f'[runner] Ortoni report: {run["report"]}' if newest
                 else '[runner] this run produced no Ortoni report')
            if summary['report_html']:
                run['defectReport'] = summary['report_html']

        n_def = len(summary['defects'])
        emit('')
        emit(f"[smart-run] done · {len(summary['updated'])} status(es) updated · "
             f"{n_def} defect(s)" + (' · defect rows excluded from evidence' if n_def else ''))
        finish(code2)

    threading.Thread(target=orchestrate, daemon=True).start()
    return run_id


def start_argv(argv: list[str], cwd: str, report_globs: tuple[str, ...] = (),
               report_label: str = 'Report') -> str:
    """Run an explicit argv in an explicit directory, streamed like any other run.

    Added for the Agentforce Configuration engine, which drives a framework in
    ANOTHER repo: there is no spec file here to derive a kind from, so start_run's
    path-based dispatch does not apply. Everything else is deliberately identical —
    shell=False with a real argv (SEC-5), own process group so stop_run can signal
    the tree (REL-1), per-consumer queues fed from a replay buffer (REL-3), and the
    hard timeout ceiling (REL-4).

    Report resolution follows the same rule as every other framework: anchored on
    the run's start time, so a report written before this run can never be served
    as its evidence, and no report means no report rather than an older one.
    """
    run_id = uuid.uuid4().hex[:12]
    popen_kw = {}
    if os.name != 'nt':
        popen_kw['start_new_session'] = True
    else:
        popen_kw['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

    started = time.time()
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1, **popen_kw)
    except Exception as e:
        RUNS[run_id] = {'proc': None, 'queues': [], 'lock': threading.Lock(),
                        'lines': [f'[runner] failed to start: {e}'],
                        'done': True, 'exit': -1, 'report': None}
        return run_id

    RUNS[run_id] = {'proc': proc, 'queues': [], 'lines': [f'[runner] $ {" ".join(argv)}'],
                    'done': False, 'exit': None, 'report': None,
                    'reportLabel': report_label, 'lock': threading.Lock()}
    _evict_finished_runs()

    def _broadcast(item):
        run = RUNS.get(run_id)
        if not run:
            return
        with run['lock']:
            if item is not None:
                run['lines'].append(item)
            for cq in list(run['queues']):
                cq.put(item)

    def _find_report():
        base = Path(cwd).resolve()
        newest, newest_m = None, started
        for pattern in report_globs:
            try:
                matches = list(base.glob(pattern))
            except (OSError, ValueError):
                continue
            for f in matches:
                if f.suffix.lower() != '.html':
                    continue
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if m >= newest_m:
                    newest, newest_m = f, m
        return str(newest) if newest else None

    def pump():
        deadline = time.monotonic() + RUN_TIMEOUT_S
        try:
            for line in proc.stdout:
                _broadcast(ANSI.sub('', line.rstrip('\n')))
                if time.monotonic() > deadline:
                    _broadcast(f'[runner] run exceeded {RUN_TIMEOUT_S}s — terminating')
                    stop_run(run_id)
                    break
            proc.wait()
        finally:
            run = RUNS.get(run_id)
            if run is not None:
                run['exit'] = proc.returncode
                run['done'] = True
                try:
                    run['report'] = _find_report()
                except Exception as e:              # never fail a run over its report
                    _broadcast(f'[runner] could not resolve the {report_label} report: {e}')
                _broadcast(f'[runner] {report_label} report: {run["report"]}' if run.get('report')
                           else f'[runner] this run produced no {report_label} report')
            _broadcast(None)
            _evict_finished_runs()

    threading.Thread(target=pump, daemon=True).start()
    return run_id


def stream(run_id: str):
    """SSE generator. Each caller gets its OWN queue, pre-seeded with everything
    already emitted (REL-3), so multiple tabs and reconnects both work."""
    run = RUNS.get(run_id)
    if not run:
        yield 'event: end\ndata: {"exit": -1, "error": "unknown run"}\n\n'
        return

    my_q = queue.Queue()
    with run['lock']:
        backlog = list(run['lines'])
        already_done = run['done']
        run['queues'].append(my_q)

    try:
        for line in backlog:
            yield 'data: ' + json.dumps({'line': line}) + '\n\n'
        if already_done:
            yield ('event: end\ndata: '
                   + json.dumps({'exit': run['exit'], 'report': run.get('report'),
                                   'reportLabel': run.get('reportLabel')}) + '\n\n')
            return

        while True:
            try:
                line = my_q.get(timeout=30)
            except queue.Empty:
                yield ': keepalive\n\n'
                continue
            if line is None:
                yield ('event: end\ndata: '
                       + json.dumps({'exit': run['exit'], 'report': run.get('report'),
                                   'reportLabel': run.get('reportLabel')}) + '\n\n')
                return
            yield 'data: ' + json.dumps({'line': line}) + '\n\n'
    finally:
        with run['lock']:
            if my_q in run['queues']:
                run['queues'].remove(my_q)


def stop_run(run_id: str) -> bool:
    run = RUNS.get(run_id)
    if not run or run['done'] or not run['proc']:
        return False
    try:
        if os.name == 'nt':
            # argv form, no shell — the PID is ours, but keep it out of a shell anyway.
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(run['proc'].pid)],
                           capture_output=True)
        else:
            # REL-1: terminate() only ever killed the shell, leaving npx ->
            # playwright -> workers running. start_new_session() gave the child
            # its own process group, so signal the GROUP and the tree dies.
            try:
                os.killpg(os.getpgid(run['proc'].pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                run['proc'].terminate()
        return True
    except Exception:
        return False
