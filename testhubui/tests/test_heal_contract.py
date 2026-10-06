"""
Smart Run contract test — src/utils/healMode.ts  <->  testhubui/heal.py

The seam between the two halves of Smart Run is a directory of JSON files.
It crosses a language boundary, so neither `tsc` nor a Python import can
check it: the TypeScript side can compile perfectly while writing a shape the
Python side never reads. This test drives the REAL HealMode.record() through
ts-node, hands the real capture files to the real heal.apply(), and asserts on
the excel that comes out the other side.

Run:
    pip install -r testhubui/requirements.txt
    python testhubui/test_heal_contract.py        (or: npm run test:heal-contract)

It never touches the repo's own workbook — everything happens on a copy in a
temp directory that is removed afterwards.

What it proves, end to end:
  * a non proxy row below 500 is written back into the excel
  * a non proxy row at 500 is NOT written back, and becomes a defect with a
    skip-list entry, an evidence file and a consolidated report
  * a proxy row is accepted at ANY status, 500 included, and is written back
  * rows nobody captured are left byte for byte alone
  * credential headers never reach a capture, the evidence or the report
  * a multi-megabyte Buffer body is summarised, not expanded
  * the verify pass finds the defect row through HEAL_SKIP_FILE
  * the environment gate holds: dev/sit/uat/prod yes, mock and qa no
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Ported from testhub-api-quality-accelerator's reference branch into
# testhubui/tests/, so heal.py is one level up rather than beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import heal  # noqa: E402

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit('openpyxl is required: pip install -r testhubui/requirements.txt')

# parents[2] not parent.parent: this file moved from testhubui/ into
# testhubui/tests/ when Smart Run was ported, so the repo root is one
# level further up. Getting this wrong resolves REPO to testhubui/ and
# the workbook copy fails with a confusing FileNotFoundError.
REPO = Path(__file__).resolve().parents[2] / 'testhub-api-quality-accelerator'   # the API accelerator
WORKBOOK = 'complex.xlsx'
SHEET = 'users1'

# Rows the capture driver touches. Everything else must stay untouched.
CAPTURED = {'Users1 Happy Path', 'Mandatory Only', 'Missing Name',
            'Empty Payload', 'Invalid JSON'}

failures: list[str] = []


def check(label, got, want):
    ok = got == want
    print(('  PASS  ' if ok else '  FAIL  ') + label)
    if not ok:
        print(f'         got  {got!r}\n         want {want!r}')
        failures.append(label)


def status_cells(path: Path) -> dict:
    ws = load_workbook(path)[SHEET]
    headers = {str(c.value).strip(): c.column for c in ws[1] if c.value}
    name_col, status_col = headers['TestName'], headers['ExpectedStatus']
    return {ws.cell(r, name_col).value: ws.cell(r, status_col).value
            for r in range(2, ws.max_row + 1)}


def run_ts(script: str, env: dict) -> str:
    """Runs one of the ts-node phases from the repo root."""
    child = dict(os.environ)
    # The repo tsconfig sets outDir without rootDir, which ts-node rejects for
    # anything outside src/. Harmless override, scoped to this process.
    child['TS_NODE_COMPILER_OPTIONS'] = '{"rootDir":"."}'
    child.update(env)
    proc = subprocess.run(
        f'npx ts-node -T scripts/{script}',
        cwd=REPO, shell=True, text=True, env=child,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    print(proc.stdout.rstrip())
    if proc.returncode != 0:
        failures.append(f'{script} exited {proc.returncode}')
    return proc.stdout


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix='heal-contract-'))
    try:
        excel_dir = sandbox / 'repo' / 'test-data' / 'excel'
        excel_dir.mkdir(parents=True)
        shutil.copy(REPO / 'test-data' / 'excel' / WORKBOOK, excel_dir)
        captures = sandbox / 'captures'
        captures.mkdir()

        print('\n=== PHASE 1 · capture (real HealMode.record) ===')
        run_ts('healContract.capture.ts', {
            'HEAL_MODE': 'capture',
            'ENVIRONMENT': 'dev',
            'HEAL_RUN_DIR': str(captures),
        })

        written = sorted(captures.glob('*.json'))
        check('one capture file per row', len(written), 5)
        check('capture filenames are unique',
              len({f.name for f in written}), len(written))

        big = json.loads(next(
            f for f in written if 'Missing-Name' in f.name
        ).read_text(encoding='utf-8'))
        check('3 MB Buffer body summarised, not expanded',
              big['requestBody'], '<Buffer 3000000 bytes>')
        check('Authorization redacted in the capture',
              big['requestHeaders']['Authorization'], '***redacted***')
        check('x-api-key redacted in the capture',
              big['requestHeaders']['x-api-key'], '***redacted***')

        print('\n=== PHASE 2 · heal (real heal.apply) ===')
        summary = heal.apply(sandbox / 'repo', captures, 'dev',
                             'src/tests/complex/users1.test.ts')

        cells = status_cells(excel_dir / WORKBOOK)
        pristine = status_cells(REPO / 'test-data' / 'excel' / WORKBOOK)

        check('non proxy 201 -> 200 written back',
              cells['Users1 Happy Path'], 200)
        check('non proxy 415 written back', cells['Missing Name'], 415)
        check('proxy 500 written back (proxy rule accepts anything)',
              cells['Mandatory Only'], 500)
        check('non proxy 500 NOT written back (defect)',
              cells['Empty Payload'], pristine['Empty Payload'])
        check('rows nobody captured are untouched',
              {k: v for k, v in cells.items() if k not in CAPTURED},
              {k: v for k, v in pristine.items() if k not in CAPTURED})

        check('updated rows', sorted(u['row'] for u in summary['updated']),
              ['Mandatory Only', 'Missing Name', 'Users1 Happy Path'])
        check('already correct row counted as unchanged',
              summary['unchanged'], 1)
        check('one defect raised', len(summary['defects']), 1)
        check('defect is the 5xx row',
              summary['defects'][0]['row'], 'Empty Payload')
        check('proxy 5xx listed as informational',
              [p['row'] for p in summary['proxy_5xx']], ['Mandatory Only'])
        check('no warnings', summary['warnings'], [])
        check('no unmatched rows', summary['unmatched'], [])

        print('\n=== PHASE 3 · defect pack ===')
        skip = json.loads(Path(summary['skip_file']).read_text(encoding='utf-8'))
        check('skip-list key matches the spec lookup shape',
              skip['defects'][0]['key'], f'{SHEET}::Empty Payload')

        report = Path(summary['report_html']).read_text(encoding='utf-8')
        evidence = Path(summary['report_dir'], 'evidence.json') \
            .read_text(encoding='utf-8')
        check('report names the defect', 'Empty Payload' in report, True)
        check('report carries the plain-language explanation',
              'inside the service' in report, True)
        check('report flags the accepted proxy 5xx',
              'auto accepted per the proxy rule' in report, True)
        check('no token leaked into the report',
              'super-secret-mulesoft-token' in report, False)
        check('no token leaked into the evidence',
              'super-secret-mulesoft-token' in evidence, False)
        check('evidence keeps the 5xx response body',
              'NullPointerException' in evidence, True)

        print('\n=== PHASE 4 · verify pass + environment gate ===')
        run_ts('healContract.verify.ts', {
            'HEAL_MODE': 'verify',
            'ENVIRONMENT': 'dev',
            'HEAL_SKIP_FILE': summary['skip_file'],
        })
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    print()
    if failures:
        print(f'FAILED ({len(failures)}):')
        for f in failures:
            print(f'  - {f}')
        return 1
    print('ALL CHECKS PASSED — healMode.ts and heal.py agree.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
