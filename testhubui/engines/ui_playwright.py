"""
TestHub Automation Studio — UI Test Automation engine (Playwright Web).

Emits Playwright specs that call ONLY the TestHub keyword layer
(`src/ui/browserActions.ts`, `src/ui/elementActions.ts`) — never raw Playwright.
That indirection is deliberate: when the framework team's `BrowserActions.ts`
lands, swapping the keyword implementation leaves every generated test valid.

Negative matrix follows the same principle the API engine uses — derive the
negatives from the captured intent rather than inventing them:

    for every field the journey fills:
        · empty  -> the journey must NOT reach its success state
        · invalid-> the journey must NOT reach its success state

No scenario is invented that the intent does not imply.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .base import ACCEL, API_DIR, Assets, Row, register

# Keyword names the emitted spec is allowed to call. Anything outside this set
# is a template bug — asserted in render() so it fails at generate time, not in
# the client's CI.
ELEMENT_KEYWORDS = {
    'click', 'doubleClick', 'fill', 'type', 'clear', 'check', 'uncheck',
    'selectOption', 'hover', 'pressKey', 'uploadFile', 'selectRadio',
}
VALUE_KEYWORDS = {'fill', 'type', 'selectOption', 'uploadFile', 'pressKey'}


def _ts(s: str) -> str:
    """Escape a Python string for embedding in a single-quoted TS literal."""
    return (str(s).replace('\\', '\\\\').replace("'", "\\'")
            .replace('\n', '\\n').replace('\r', ''))


def _pascal(s: str) -> str:
    return ''.join(w[:1].upper() + w[1:] for w in str(s).replace('-', ' ').replace('_', ' ').split())


def _safe(s: str) -> str:
    return ''.join(c for c in str(s or '').strip() if c.isalnum() or c in '-_') or 'asset'


def _repo_root() -> Path:
    """The accelerator root — the folder holding package.json and src/."""
    here = Path(__file__).resolve()
    if (here.parents[2] / ACCEL['ui'] / 'src' / 'ui').is_dir():
        return here.parents[2] / ACCEL['ui']
    if (here.parents[2] / API_DIR / 'src').is_dir():
        return here.parents[2] / API_DIR
    for base in here.parents:
        if (base / 'package.json').exists() and (base / 'src').is_dir():
            return base
    return here.parents[2]


class UiPlaywrightEngine:
    id = 'ui'
    title = 'UI Test Automation'
    emits_assets = True
    can_execute = True

    def preflight(self) -> tuple[bool, str]:
        if shutil.which('npx') is None:
            return False, 'npx not found — install Node.js 18+ to run UI tests.'
        return True, 'Playwright + chromium (shared with the API accelerator).'

    # ───────────────────────── matrix ─────────────────────────

    def build_matrix(self, cfg: dict) -> list[Row]:
        steps = [s for s in (cfg.get('steps') or []) if s.get('action')]
        want_pos = cfg.get('positive', True) is not False
        want_neg = cfg.get('negative', True) is not False
        journey = cfg.get('journeyName') or 'Journey'

        rows: list[Row] = []

        if want_pos:
            rows.append(Row(
                name=f'{journey} — happy path',
                kind='positive',
                detail='All steps execute; success state is reached.',
                data={'steps': steps, 'expectSuccess': True},
            ))

        if not want_neg:
            return rows

        # One negative pair per data-bearing field, derived from the journey.
        for idx, step in enumerate(steps):
            action = step.get('action')
            if action not in ('fill', 'type'):
                continue
            label = step.get('label') or step.get('locator') or f'field {idx + 1}'

            empty = [dict(s) for s in steps]
            empty[idx] = {**empty[idx], 'value': ''}
            rows.append(Row(
                name=f'{journey} — {label} empty',
                kind='negative',
                detail=f'{label} left blank; success state must not be reached.',
                data={'steps': empty, 'expectSuccess': False},
            ))

            invalid = [dict(s) for s in steps]
            invalid[idx] = {**invalid[idx], 'value': '__invalid__'}
            rows.append(Row(
                name=f'{journey} — {label} invalid',
                kind='negative',
                detail=f'{label} set to an invalid value; success state must not be reached.',
                data={'steps': invalid, 'expectSuccess': False},
            ))

        return rows

    # ───────────────────────── render ─────────────────────────

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        asset = _safe(cfg.get('assetName'))
        service = _safe(cfg.get('serviceName'))
        base_url = cfg.get('baseUrl') or ''
        success = cfg.get('successLocator') or ''
        expect_title = cfg.get('expectTitle') or ''
        expect_url = cfg.get('expectUrlContains') or ''

        for r in rows:
            for s in r.data.get('steps', []):
                if s.get('action') not in ELEMENT_KEYWORDS:
                    raise ValueError(f"unsupported UI keyword: {s.get('action')!r}")

        paths = cfg.get('paths') or {}
        # Its own accelerator, never the API one: the `spec` key is the API testDir.
        spec_dir = Path(paths.get('ui') or ACCEL['ui'] + '/tests') / asset
        spec_path = spec_dir / f'{service}.ui.test.ts'

        assets = Assets(rows=len(rows), sheet=f'{_pascal(service)}UI')
        assets.add(spec_path, self._spec(
            asset, service, base_url, success, expect_title, expect_url, rows,
            spec_dir=spec_dir))
        return assets

    @staticmethod
    def _repo_relative_file_url(base_url: str, spec_dir: Path | None) -> str | None:
        """For a file:// URL inside the repo, the hop from the spec to it.

        Returns None for http(s) — a real application URL is meant to be
        absolute — and None for a file:// URL outside the repo, which cannot be
        expressed relatively in any useful way.

        The bug this exists to stop: fixtures live in the repo, so a tester
        pointing the Studio at test-data/fixtures/login.html got their own
        absolute path frozen into a committed spec. It passed for them and
        failed for everyone else, including CI, which is the worst shape a test
        failure can take — it looks like the other machine is broken.
        """
        raw = str(base_url or '').strip()
        if not raw.startswith('file://'):
            return None
        from urllib.parse import unquote, urlparse
        target = Path(unquote(urlparse(raw).path))
        # Engine defaults are repo-relative; app.py resolves them against the
        # repo root before render(), so spec_dir is absolute in normal use.
        base = spec_dir if spec_dir and spec_dir.is_absolute() else None
        if base is None:
            return None
        try:
            root = Path(_repo_root())
            if not target.resolve().is_relative_to(root):
                return None
            import os as _os
            return _os.path.relpath(target.resolve(), base.resolve())
        except (OSError, ValueError):
            return None

    def _spec(self, asset, service, base_url, success, expect_title,
              expect_url, rows, spec_dir: Path | None = None) -> str:
        tag = f'@{_pascal(asset)}_UI'
        # The keyword layer sits at src/ui in both places the spec can land: two
        # hops up from src/tests/<asset>/ in the API accelerator, or from
        # tests/<asset>/ in the UI accelerator where src/ is a sibling of tests/.
        sd = (spec_dir or Path('')).as_posix()
        ui_rel = '../../ui' if f'/src/tests/' in sd + '/' else '../../src/ui'
        el_used = sorted({s['action'] for r in rows for s in r.data.get('steps', [])})
        el_import = ', '.join(el_used + ['expectVisible', 'expectHidden',
                                         'expectTitle', 'expectUrlContains'])

        out: list[str] = []
        out.append('/**')
        out.append(f' * {asset} — {service} · UI Test Automation')
        out.append(' *')
        out.append(' * GENERATED by TestHub Automation Studio. Every step below calls the TestHub')
        out.append(' * keyword layer, never raw Playwright, so the execution engine can be')
        out.append(' * replaced without regenerating this file.')
        out.append(' */')
        # A file:// base URL pointing inside the repo is emitted as a path
        # resolved at RUN time. Baking the absolute path in is correct exactly
        # once — on the machine that generated it — and this actually shipped:
        # a committed suite carried an author's scratchpad path and failed on
        # CI and on every other clone while passing for its author.
        local_rel = self._repo_relative_file_url(base_url, spec_dir)
        if local_rel:
            out.append("import * as path from 'node:path';")
            out.append("import { pathToFileURL } from 'node:url';")
        out.append("import { test } from '@playwright/test';")
        # goToURL, NOT openURL. In the team's BrowserActions, openURL() opens a NEW
        # browser (openBrowser + goToURL), so calling it per test would leak one
        # browser per test on top of the one opened in beforeAll.
        out.append("import { openBrowser, goToURL, closeAllBrowsers } from '" + ui_rel + "/browserActions';")
        out.append(f"import {{ {el_import} }} from '{ui_rel}/elementActions';")
        out.append('')
        if local_rel:
            out.append('// Resolved from THIS file at run time, so the suite travels between')
            out.append('// machines and CI. Set UI_BASE_URL to point it somewhere else.')
            out.append("const BASE_URL = process.env.UI_BASE_URL")
            out.append(f"  || pathToFileURL(path.resolve(__dirname, '{_ts(local_rel)}')).href;")
        else:
            out.append(f"const BASE_URL = process.env.UI_BASE_URL || '{_ts(base_url)}';")
        out.append('')
        out.append(f"test.describe('{_ts(asset)} UI — {_ts(service)}', () => {{")
        out.append('  test.beforeAll(async () => { await openBrowser(); });')
        out.append('  test.afterAll(async () => { await closeAllBrowsers(); });')
        out.append('')

        for i, r in enumerate(rows, 1):
            steps = r.data.get('steps', [])
            expect_ok = r.data.get('expectSuccess', True)
            out.append(f"  // {r.detail}")
            out.append(f"  test('{tag} @{r.kind} [{i}] {_ts(r.name)}', async () => {{")
            out.append('    await goToURL(BASE_URL);')
            for s in steps:
                out.append('    ' + self._call(s))
            out.append('')
            if expect_ok:
                if success:
                    out.append(f"    await expectVisible('{_ts(success)}');")
                if expect_title:
                    out.append(f"    await expectTitle('{_ts(expect_title)}');")
                if expect_url:
                    out.append(f"    await expectUrlContains('{_ts(expect_url)}');")
                if not (success or expect_title or expect_url):
                    out.append('    // no success assertion captured — add one in the Studio')
            else:
                if success:
                    out.append(f"    await expectHidden('{_ts(success)}');")
                else:
                    out.append('    // no success locator captured — negative cannot assert')
            out.append('  });')
            out.append('')

        out.append('});')
        return '\n'.join(out) + '\n'

    def _call(self, step: dict) -> str:
        action = step['action']
        loc = _ts(step.get('locator') or '')
        val = _ts(step.get('value') or '')
        if action == 'pressKey':
            return f"await pressKey('{val}');"
        if action in VALUE_KEYWORDS:
            return f"await {action}('{loc}', '{val}');"
        return f"await {action}('{loc}');"


engine = register(UiPlaywrightEngine())
