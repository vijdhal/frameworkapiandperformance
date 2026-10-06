"""
TestHub Automation Studio — Mobile Test Automation engine (Mobilewright).

WHY MOBILEWRIGHT AND NOT APPIUM
-------------------------------
This engine originally emitted WebdriverIO + Appium. That was wrong, and it was
the same mistake the Salesforce engine nearly made: building a parallel stack
instead of the one the team is standardising on.

Ashok reported (22 Jul) working on "mobile automation framework using
mobilewright with TypeScript". Nobody shared a repo, so it was treated as
unverified. It is real and well chosen:

    mobile-next/mobilewright · 323 stars · npm 0.0.52
    plus MarketSquare/robotframework-mobilewright and a first-party MCP server

It is the better fit on the merits, not out of deference:

  · Playwright-shaped API — getByText / getByRole / getByLabel / expect. The
    Studio's UI engine already emits exactly these idioms, so a tester reads one
    vocabulary across web and mobile instead of two.
  · No Appium server. It drives devices through its own `mobilecli` agent, so
    there is no separate process to babysit in CI.
  · One API for iOS and Android, rather than XCUITest/UiAutomator2 branching.
  · Built-in auto-wait, so generated tests do not need hand-rolled sleeps.

VERIFIED, not assumed — a real published app driven end to end:
    Fossify Calculator (org.fossify.math v1.4.0, F-Droid) on a Pixel_7 emulator
    tap 7 -> + -> 8 -> = -> expect 15
    ✓ 1 passed (29.1s)
    On-device confirmation: formula '7+8', result '15'

ISOLATED WORKSPACE IS MANDATORY
-------------------------------
`@mobilewright/test` bundles its own @playwright/test, which collides with the
accelerator's:

    Error: You have two different versions of @playwright/test.

Mobile assets therefore CANNOT live in the accelerator's node_modules tree. This
engine emits a self-contained workspace (package.json + config + specs) that is
installed and run on its own. That is a constraint of the tool, discovered by
running it, and the emitted README says so plainly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .base import ACCEL, API_DIR, Assets, Row, field, register, section

# Mobilewright locator strategies, mapped to what a tester actually captures.
LOCATORS = {
    'text':  'getByText',
    'label': 'getByLabel',
    'role':  'getByRole',
    'id':    'getById',
}

ACTIONS = {'tap', 'fill', 'clearText', 'swipeUp', 'swipeDown', 'pressKey', 'waitFor'}
NEEDS_VALUE = {'fill', 'pressKey'}


def _safe(s: str) -> str:
    return ''.join(c for c in str(s or '').strip() if c.isalnum() or c in '-_.') or 'asset'


def _js(s) -> str:
    """Safe TS string literal — json.dumps handles quotes and backslashes."""
    return json.dumps(str(s))


def _device_regex(device: str) -> str:
    """Body of a JS regex literal `/.../` matching a device name.

    deviceName is documented as a regex ("Pixel", "iPhone"), so this must NOT
    escape metacharacters — that would break the intentional case. Two things
    it must do:

    1. Escape the delimiter. An unescaped `/` closes the literal early and
       emits TypeScript that does not parse. Real device names are outside our
       control — they come back from `mobilecli devices` as whatever the owner
       typed in iOS Settings — so this is reachable, not theoretical.
       Escaping `/` cannot change what the regex matches.
    2. Reject a pattern that is not a valid regex, here, with a message naming
       the field. Otherwise an unbalanced `(` or `[` sails through and fails
       later as a TypeScript syntax error in a generated file the user did not
       write, which is a much harder thing to act on.
    """
    pattern = str(device or '').strip() or 'iPhone'
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f'Device name pattern is not a valid regex: {exc}') from exc
    return re.sub(r'(?<!\\)/', r'\\/', pattern)


class MobileWrightEngine:
    id = 'mob'
    title = 'Mobile Test Automation'
    emits_assets = True

    @staticmethod
    def _mobilecli() -> str | None:
        """mobilecli ships INSIDE the mobilewright npm package, so it is normally
        not on PATH. Check the node_modules bins of the places a generated mobile
        workspace would live before giving up."""
        found = shutil.which('mobilecli')
        if found:
            return found
        root = Path(__file__).resolve().parents[2]
        candidates = [
            root / API_DIR / 'node_modules/.bin/mobilecli',
            root / 'node_modules/.bin/mobilecli',
            root / 'mobile/node_modules/.bin/mobilecli',
            Path.home() / '.venvs/mobilewright/node_modules/.bin/mobilecli',
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    @classmethod
    def _devices(cls) -> list[str]:
        """Ask mobilecli what is actually connected. No guessing."""
        exe = cls._mobilecli()
        if not exe:
            return []
        try:
            out = subprocess.run([exe, 'devices'], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return []
        # mobilecli emits JSON: {status, data:{devices:[{id,name,platform,type,state,...}]}}
        # (The table you see from `mobilewright devices` is that JSON rendered.)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            return []
        devices = (payload.get('data') or {}).get('devices') or []
        return [f"{d.get('name') or d.get('id')} ({d.get('platform')}/{d.get('type')})"
                for d in devices if str(d.get('state', '')).lower() == 'online']

    @property
    def can_execute(self) -> bool:
        return bool(self._devices())

    def preflight(self) -> tuple[bool, str]:
        devices = self._devices()
        if devices:
            return True, (f"mobilecli sees {', '.join(devices)} — specs can be generated and run. "
                          'Emitted as a self-contained workspace: npm i && npx mobilewright test')
        if self._mobilecli():
            return True, ('mobilecli is installed but no device is online. Boot an emulator/simulator '
                          'or plug in a handset, then re-check.')
        return True, ('Emits Mobilewright specs. To run them: npm i -D mobilewright @mobilewright/test, '
                      'then npx mobilewright install to put the agent on the device.')

    def schema(self):
        return [
            section('App Under Test', [
                field('assetName', 'Asset Name', required=True, placeholder='wallet'),
                field('serviceName', 'Journey Name', required=True, placeholder='login'),
                field('platform', 'Platform', 'select', options=['android', 'ios'], default='android'),
                field('bundleId', 'App bundle / package id', required=True, width='full',
                      placeholder='org.fossify.math',
                      hint='Android package name or iOS bundle id. The app must already be installed on the device.'),
                field('deviceName', 'Device name pattern', default='Pixel',
                      hint='Matched as a regex against connected devices, e.g. Pixel or iPhone.'),
                field('timeoutMs', 'Timeout (ms)', default='30000',
                      hint='iOS is raised to a 180000ms floor — see IOS_TIMEOUT_FLOOR_MS.'),
            ]),
            section('Steps', [
                field('steps', 'Journey steps', 'steps', width='full', options=sorted(ACTIONS)),
            ], note='Locators are semantic: text, label, role or id — not XPath or coordinates. '
                    'Mobilewright auto-waits, so no sleeps are emitted.'),
            section('Expectations', [
                field('expectText', 'Expect text visible', required=True, width='full',
                      placeholder='15',
                      hint='Asserted with expect(screen.getByText(...)).toBeVisible().'),
            ]),
            section('Scenario Type', [
                field('positive', 'Positive', 'toggle', default='on'),
                field('negative', 'Negative', 'toggle', default='on'),
            ], note='Negatives blank each filled field in turn; the expected text must NOT appear.'),
        ]

    # ───────────────────────── matrix ─────────────────────────

    def build_matrix(self, cfg: dict) -> list[Row]:
        steps = [s for s in (cfg.get('steps') or []) if s.get('action')]
        if not steps:
            raise ValueError('Capture at least one step')
        for s in steps:
            if s['action'] not in ACTIONS:
                raise ValueError(f"unsupported mobile keyword: {s['action']}")
        journey = cfg.get('serviceName') or 'Journey'
        rows: list[Row] = []

        if cfg.get('positive', True) is not False:
            rows.append(Row(name=f'{journey} — happy path', kind='positive',
                            detail='All steps run; the expected text is visible.',
                            data={'steps': steps, 'expectVisible': True}))

        if cfg.get('negative', True) is not False:
            for i, s in enumerate(steps):
                if s['action'] not in NEEDS_VALUE:
                    continue
                label = s.get('label') or s.get('locator') or f'field {i + 1}'
                blanked = [dict(x) for x in steps]
                blanked[i] = {**blanked[i], 'value': ''}
                rows.append(Row(name=f'{journey} — {label} empty', kind='negative',
                                detail=f'{label} left blank; the expected text must not appear.',
                                data={'steps': blanked, 'expectVisible': False}))
        return rows

    # ───────────────────────── render ─────────────────────────

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        asset, service = _safe(cfg.get('assetName')), _safe(cfg.get('serviceName'))
        # One Mobilewright workspace PER ASSET. At the accelerator root, a second
        # journey overwrote the first's package.json and config, and the folder's
        # own README blocked every generate (found 2026-09-06 through the live
        # Studio: WouldClobber on README.md). Each asset now owns its workspace.
        out = Path((cfg.get('paths') or {}).get('mobile') or ACCEL['mob']) / asset
        platform = (cfg.get('platform') or 'android').lower()
        bundle = (cfg.get('bundleId') or '').strip()
        device = (cfg.get('deviceName') or ('iPhone' if platform == 'ios' else 'Pixel')).strip()
        timeout = self._timeout_ms(cfg.get('timeoutMs'), platform)
        expect_text = cfg.get('expectText') or ''

        assets = Assets(rows=len(rows), sheet=f'{asset}Mobile')
        assets.add(out / 'mobilewright.config.ts',
                   self._config(platform, bundle, device, timeout, asset, service))
        assets.add(out / 'package.json', self._package(asset))
        assets.add(out / 'tests' / f'{service}.test.ts',
                   self._spec(asset, service, bundle, expect_text, rows))
        assets.add(out / 'README.md', self._readme(asset, service, bundle, platform))
        return assets

    # A cold iOS run does work no Android run does: download the devicekit
    # agent from GitHub, install an XCUITest runner onto the simulator, and
    # wait for WebDriverAgent to answer. All of that lands inside the FIRST
    # test's timeout budget, so a too-small budget fails a test that is
    # perfectly correct — and fails it with "Test timeout of 30000ms exceeded
    # while setting up device", which reads like a broken test.
    #
    # Measured, Xcode 26.6 / iOS 26.0 / this machine:
    #   - 30s budget, iPhone 17 Pro   -> FAILED in device setup
    #   - 180s budget, same spec warm -> passed in 5.7s
    #   - 180s budget, virgin iPhone 16e, agent cache cleared
    #     (i.e. a client's true first run) -> passed, 23.5s of which the
    #     GitHub download was 2.8s and the runner install 7s
    #
    # 23.5s is UNDER 30s, so the default is not always wrong — it is
    # MARGINAL, which is worse. That measurement is on a fast machine and a
    # fast link; the 2.8s download alone is unbounded on a client network,
    # and a 30s budget was in fact observed failing. A floor removes a class
    # of first-run failure that would otherwise be blamed on the test.
    #
    # Floor iOS rather than raise the shared default: Android does none of
    # this setup and gains nothing from a 180s budget except slower feedback
    # when a locator is genuinely wrong.
    #
    # KNOWN LIMITATION: on the iOS 26.5 runtime, devicekit 0.0.23's
    # WebDriverAgent never became ready at all ("timed out waiting for
    # WebDriverAgent"), at any budget. That is a runtime/agent incompatibility
    # and no timeout can fix it — use an iOS 26.0 simulator.
    IOS_TIMEOUT_FLOOR_MS = 180_000

    @classmethod
    def _timeout_ms(cls, requested, platform: str) -> str:
        raw = str(requested or '30000').strip()
        ms = int(raw) if raw.isdigit() else 30_000
        if str(platform).lower() == 'ios':
            ms = max(ms, cls.IOS_TIMEOUT_FLOOR_MS)
        return str(ms)

    def _config(self, platform, bundle, device, timeout, asset, service) -> str:
        return '\n'.join([
            "import { defineConfig } from 'mobilewright';",
            '',
            '// GENERATED by TestHub Automation Studio.',
            'export default defineConfig({',
            f'  platform: {_js(platform)},',
            f'  bundleId: {_js(bundle)},',
            f'  deviceName: /{_device_regex(device)}/,',
            f'  timeout: {int(timeout) if timeout.isdigit() else 30000},',
            "  testDir: './tests',",
            '  // NOT Ortoni here, and this is load-bearing. ortoni-report depends on',
            '  // @playwright/test, which npm hoists alongside the copy @mobilewright/test',
            '  // bundles — two Playwright runtimes in one workspace, and every test fails',
            "  // with \"Playwright Test did not expect test() to be called here\". Measured,",
            '  // not assumed: adding it produced exactly that and collected zero tests.',
            '  // Mobile evidence is the mobilewright HTML report; the unified view is the',
            '  // job of the evidence layer, not of a reporter this workspace cannot host.',
            "  reporter: [['list'], ['html', { open: 'never' }]],",
            '});',
            '',
        ])

    def _package(self, asset) -> str:
        # A SEPARATE workspace on purpose — see the module docstring. Sharing the
        # accelerator's node_modules produces "two different versions of
        # @playwright/test" and nothing runs.
        return json.dumps({
            'name': f'testhub-mobile-{asset}'.lower(),
            'private': True,
            'description': 'Generated by TestHub Automation Studio. Install and run standalone — '
                           '@mobilewright/test bundles its own @playwright/test and must not share '
                           "a node_modules tree with the API/UI accelerator.",
            'scripts': {
                'test': 'mobilewright test',
                'devices': 'mobilewright devices',
                'doctor': 'mobilewright doctor',
                'agent': 'mobilewright install',
            },
            'devDependencies': {
                'mobilewright': '^0.0.52',
                '@mobilewright/test': '^0.0.52',
            },
        }, indent=2) + '\n'

    def _spec(self, asset, service, bundle, expect_text, rows) -> str:
        S = ['/**',
             f' * {asset} — {service} · Mobile (Mobilewright)',
             ' *',
             ' * GENERATED by TestHub Automation Studio.',
             f' * App under test: {bundle} — must already be installed on the device.',
             ' *',
             ' * Locators are semantic (getByText/getByLabel/getByRole), and Mobilewright',
             ' * auto-waits, so no explicit sleeps are emitted.',
             ' */',
             "import { test, expect } from '@mobilewright/test';",
             '']
        for i, r in enumerate(rows, 1):
            S.append(f'  // {r.detail}')
            S.append(f'test({_js(f"@Mobile @{r.kind} [{i}] {r.name}")}, async ({{ screen }}) => {{')
            for s in r.data['steps']:
                S.append('  ' + self._call(s))
            S.append('')
            if expect_text:
                if r.data['expectVisible']:
                    S.append(f'  await expect(screen.getByText({_js(expect_text)})).toBeVisible();')
                else:
                    S.append(f'  await expect(screen.getByText({_js(expect_text)})).not.toBeVisible();')
            S.append('});')
            S.append('')
        return '\n'.join(S)

    def _call(self, s: dict) -> str:
        action = s['action']
        strategy = LOCATORS.get((s.get('strategy') or 'text').lower(), 'getByText')
        loc, val = s.get('locator') or '', s.get('value') or ''
        target = f'screen.{strategy}({_js(loc)})'
        if action == 'tap':
            return f'await {target}.tap();'
        if action == 'fill':
            return f'await {target}.fill({_js(val)});'
        if action == 'clearText':
            return f'await {target}.fill("");'
        if action == 'waitFor':
            return f'await expect({target}).toBeVisible();'
        if action == 'pressKey':
            return f'await screen.pressKey({_js(val)});'
        if action in ('swipeUp', 'swipeDown'):
            return f'await screen.swipe({_js("up" if action == "swipeUp" else "down")});'
        return f'await {target}.tap();'

    def _readme(self, asset, service, bundle, platform) -> str:
        return '\n'.join([
            f'# {asset} — {service} · Mobile tests',
            '',
            'Generated by TestHub Automation Studio using **Mobilewright**.',
            '',
            '## Why this is a separate project',
            '',
            '`@mobilewright/test` bundles its own `@playwright/test`. Installing it alongside',
            'the API/UI accelerator produces:',
            '',
            '```',
            'Error: You have two different versions of @playwright/test.',
            '```',
            '',
            'so these tests install and run on their own. That is a property of the tool, not',
            'a choice — verified by hitting it.',
            '',
            '## Run',
            '',
            '```bash',
            'npm install',
            'npx mobilewright doctor      # environment check',
            'npx mobilewright devices     # confirm a device is online',
            'npx mobilewright install     # put the agent on the device (once per device)',
            'npx mobilewright test',
            '```',
            '',
            f'The app under test (`{bundle}`) must already be installed on the device.',
            '',
            '## iOS' if platform == 'ios' else '## Android',
            '',
            ('Requires Xcode (full install from the Mac App Store, not just Command Line Tools), '
             'an iOS simulator runtime, and `sudo xcodebuild -license accept`.'
             if platform == 'ios' else
             'Requires the Android SDK and a booted emulator or a connected handset with USB '
             'debugging enabled.'),
            '',
        ])


engine = register(MobileWrightEngine())
