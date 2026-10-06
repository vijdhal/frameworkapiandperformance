"""
TestHub Automation Studio — Smart Run heal engine.

Runs between the two Playwright passes of a Smart Run:

  Pass 1 (HEAL_MODE=capture) executed every excel row and dropped one JSON
  capture per row into a run directory. This module reads those captures,
  applies the status rules, writes the accepted statuses back into the
  governed excel workbook, and produces the defect pack + skip list that
  drive Pass 2 (HEAL_MODE=verify).

The rules (single source of truth; src/utils/healMode.ts only gates and
records):

  proxy endpoint      resolved URL contains "proxy" (eproxy, experience
                      proxy, salesforce proxy, ...). No restriction: ANY
                      status the system returns is accepted and written
                      back to the excel automatically.
  normal endpoint     status below 500 (200 / 201 / 207 / 400 / ...) is
                      accepted and written back automatically.
  normal endpoint     status 500 and above is NEVER written back. The row
                      becomes a DEFECT: the full evidence is retained in a
                      separate defect pack with a consolidated explanation
                      so the tester can raise a bug for the responsible
                      developer, and the row is skipped in the verify pass
                      so the final evidence contains the successful runs.

Applies only when ENVIRONMENT is dev / sit / uat / prod. Never mock.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from openpyxl import load_workbook

# Keep in sync with HEAL_ENVIRONMENTS in src/utils/healMode.ts and the
# gating in static/index.html. Mock is intentionally excluded.
HEAL_ENVIRONMENTS = {'dev', 'sit', 'uat', 'prod'}

# Any status at or above this value on a NON-proxy endpoint is a defect.
SERVER_ERROR_MIN = 500

# Column aliases across the two governed excel schemas.
STATUS_COLS   = ('ExpectedStatus', 'expectedStatus')
NAME_COLS     = ('TestName', 'name')
ENDPOINT_COLS = ('Endpoint', 'endpoint')
METHOD_COLS   = ('Method', 'method')


def is_proxy_url(url: str) -> bool:
    """Mirror of HealMode.isProxyUrl: 'proxy' anywhere in the resolved URL."""
    return bool(re.search(r'proxy', url or '', re.IGNORECASE))


def load_captures(run_dir: str | Path) -> list[dict]:
    """Reads every per-row capture file Pass 1 wrote into the run dir."""
    out = []
    d = Path(run_dir)
    if not d.is_dir():
        return out
    for f in sorted(d.glob('*.json')):
        try:
            out.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception:
            continue
    return out


def resolve_excel(repo_root: Path, excel_name: str) -> Path | None:
    """
    Captures may carry either a repo-relative path
    ('test-data/excel/clients-tests.xlsx') or a bare file name ('life.xlsx',
    the excelUtils.loadExcel convention).
    """
    p = Path(excel_name)
    candidates = [p if p.is_absolute() else repo_root / p,
                  repo_root / 'test-data' / 'excel' / p.name]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _header_map(ws) -> dict:
    """Maps header text (row 1) to its 1-based column index."""
    return {
        str(c.value).strip(): c.column
        for c in ws[1]
        if c.value is not None and str(c.value).strip() != ''
    }


def _col(headers: dict, aliases: tuple) -> int | None:
    for a in aliases:
        if a in headers:
            return headers[a]
    return None


def _norm(v) -> str:
    return str(v).strip().lower() if v is not None else ''


def _find_row(ws, name_col: int, endpoint_col, method_col, cap: dict):
    """
    Locates the excel row for a capture. Primary match: test name. When
    names repeat, the recorded rowIndex (0-based within the loaded rows)
    breaks the tie; endpoint + method act as a sanity check.
    Returns (row_number, warning_or_None) or (None, reason).
    """
    target = _norm(cap.get('rowName'))
    hint = int(cap.get('rowIndex', -1)) + 2  # header on row 1

    matches = []
    for r in range(2, ws.max_row + 1):
        if _norm(ws.cell(r, name_col).value) == target and target != '':
            matches.append(r)

    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        if hint in matches:
            return hint, None
        return matches[0], (
            f'row name "{cap.get("rowName")}" appears {len(matches)} times; '
            f'updated the first occurrence'
        )

    # Name not found; fall back to the positional hint if endpoint + method
    # agree, which covers a renamed scenario cell.
    if 2 <= hint <= ws.max_row:
        ep_ok = endpoint_col is None or \
            _norm(ws.cell(hint, endpoint_col).value) == _norm(cap.get('endpoint'))
        m_ok = method_col is None or \
            _norm(ws.cell(hint, method_col).value) == _norm(cap.get('method'))
        if ep_ok and m_ok:
            return hint, (
                f'row name "{cap.get("rowName")}" not found; matched by '
                f'position + endpoint/method'
            )

    return None, f'row "{cap.get("rowName")}" not found in sheet'


def classify(cap: dict) -> str:
    """
    'accept'  status is taken as-is and written back to the excel.
    'defect'  HTTP 5xx on a non-proxy endpoint. Never written back.
    """
    status = int(cap.get('actualStatus', 0))
    if cap.get('proxy') or is_proxy_url(cap.get('resolvedUrl', '')):
        return 'accept'
    return 'defect' if status >= SERVER_ERROR_MIN else 'accept'


def apply(repo_root: str | Path,
          run_dir: str | Path,
          environment: str,
          rel_spec: str = '') -> dict:
    """
    Applies the rules to every capture from Pass 1.

    Returns a summary:
      updated     rows whose ExpectedStatus changed (old -> new, proxy flag)
      unchanged   rows already correct
      defects     5xx rows on non-proxy endpoints, with full evidence
      proxy_5xx   informational: 5xx accepted on proxy rows per the rule
      warnings    matching issues, unreadable workbooks, ...
      skip_file   path Pass 2 reads to exclude the defect rows
      report_html path of the consolidated defect report (when defects exist)
    """
    root = Path(repo_root)
    env = (environment or '').lower()

    summary = {
        'environment': env,
        'updated': [], 'unchanged': 0, 'defects': [],
        'proxy_5xx': [], 'warnings': [], 'unmatched': [],
        'workbooks': [], 'skip_file': None, 'report_html': None,
        'report_dir': None,
    }

    if env not in HEAL_ENVIRONMENTS:
        summary['warnings'].append(
            f'environment "{environment}" is outside the Smart Run scope '
            f'({", ".join(sorted(HEAL_ENVIRONMENTS))}); nothing was changed'
        )
        return summary

    captures = load_captures(run_dir)
    if not captures:
        summary['warnings'].append(
            'no captures were recorded in pass 1; the excel was not touched'
        )
        return summary

    stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
    defects, service_name = [], None

    # Group captures per workbook + sheet so each file opens once.
    groups: dict[tuple, list] = {}
    for cap in captures:
        groups.setdefault(
            (cap.get('excelName', ''), cap.get('sheetName', '')), []
        ).append(cap)

    for (excel_name, sheet_name), caps in groups.items():
        service_name = service_name or (
            (caps[0].get('suite') or sheet_name or 'service').split('/')[-1]
        )
        xls = resolve_excel(root, excel_name)
        if xls is None:
            summary['warnings'].append(f'excel not found: {excel_name}')
            continue

        wb = load_workbook(xls)
        if sheet_name not in wb.sheetnames:
            summary['warnings'].append(
                f'sheet "{sheet_name}" not found in {xls.name}'
            )
            continue
        ws = wb[sheet_name]

        headers = _header_map(ws)
        status_col = _col(headers, STATUS_COLS)
        name_col = _col(headers, NAME_COLS)
        endpoint_col = _col(headers, ENDPOINT_COLS)
        method_col = _col(headers, METHOD_COLS)

        if status_col is None or name_col is None:
            summary['warnings'].append(
                f'{xls.name} · {sheet_name}: could not locate the '
                f'ExpectedStatus / TestName columns; sheet left untouched'
            )
            continue

        changed = False
        for cap in caps:
            expected = int(cap.get('expectedStatus', 0) or 0)
            actual = int(cap.get('actualStatus', 0) or 0)
            proxy = bool(cap.get('proxy')) or is_proxy_url(
                cap.get('resolvedUrl', '')
            )
            verdict = classify(cap)

            if verdict == 'defect':
                defects.append(cap)
                continue

            if proxy and actual >= SERVER_ERROR_MIN:
                # Accepted per the proxy rule, but worth a heads-up.
                summary['proxy_5xx'].append({
                    'row': cap.get('rowName'), 'status': actual,
                    'endpoint': cap.get('endpoint'),
                })

            if actual == expected:
                summary['unchanged'] += 1
                continue

            row_no, warn = _find_row(ws, name_col, endpoint_col,
                                     method_col, cap)
            if warn:
                summary['warnings'].append(f'{xls.name} · {sheet_name}: {warn}')
            if row_no is None:
                summary['unmatched'].append(cap.get('rowName'))
                continue

            ws.cell(row_no, status_col).value = actual
            changed = True
            summary['updated'].append({
                'workbook': xls.name, 'sheet': sheet_name,
                'row': cap.get('rowName'), 'endpoint': cap.get('endpoint'),
                'method': cap.get('method'),
                'old': expected, 'new': actual, 'proxy': proxy,
            })

        if changed:
            wb.save(xls)
            summary['workbooks'].append(str(xls))

    if defects or summary['proxy_5xx']:
        pack = write_defect_pack(
            root, service_name or 'service', env, defects,
            summary['proxy_5xx'], stamp, rel_spec
        )
        summary['skip_file'] = pack['skip_file']
        summary['report_html'] = pack['report_html']
        summary['report_dir'] = pack['dir']
        summary['defects'] = pack['defects']

    return summary


# ─────────────────────────── defect pack ───────────────────────────

def _fmt_json(value) -> str:
    if value is None or value == '':
        return '(no body)'
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return str(value)


def _explanation(cap: dict, env: str) -> str:
    """Consolidated plain-language explanation for the bug ticket."""
    name = cap.get('rowName', 'The scenario')
    method = cap.get('method', 'GET')
    url = cap.get('resolvedUrl') or cap.get('endpoint', '')
    status = cap.get('actualStatus')
    expected = cap.get('expectedStatus')
    elapsed = cap.get('elapsedMs')
    has_body = cap.get('requestBody') not in (None, '')

    parts = [
        f'The scenario "{name}" sent a {method} request to {url} on the '
        f'{env.upper()} environment'
        + (' with the request payload shown below.' if has_body else
           ' with no request payload.'),
        f'The service responded with HTTP {status}'
        + (f' after {elapsed} ms' if elapsed is not None else '')
        + f' instead of the governed expectation of HTTP {expected}.',
        'An HTTP 5xx response means the failure happened inside the service, '
        'not in the request that was sent.',
        'The framework therefore classifies this as a defect for the '
        'development team rather than a test data correction, and the '
        'expected status in the excel sheet was left unchanged.',
        'The full request and response evidence is attached below and in '
        'evidence.json, ready to be pasted into a bug for the responsible '
        'developer.',
    ]
    return ' '.join(parts)


def write_defect_pack(repo_root: Path, service: str, environment: str,
                      defects: list[dict], proxy_5xx: list[dict],
                      stamp: str, rel_spec: str = '') -> dict:
    """
    Writes defect-reports/<service>_<env>_<stamp>/ containing:
      DEFECT-REPORT.html  consolidated, self-contained, printable
      evidence.json       raw captures for the defect rows
      skiplist.json       read by Pass 2 to exclude the defect rows
    """
    safe = re.sub(r'[^A-Za-z0-9._-]+', '-', service or 'service')
    out_dir = Path(repo_root) / 'defect-reports' / f'{safe}_{environment}_{stamp}'
    out_dir.mkdir(parents=True, exist_ok=True)

    tagged = []
    for i, cap in enumerate(defects, 1):
        d = dict(cap)
        d['defectId'] = f'DEF-{stamp}-{i:02d}'
        tagged.append(d)

    (out_dir / 'evidence.json').write_text(
        json.dumps(tagged, indent=2, ensure_ascii=False), encoding='utf-8'
    )

    skip = {
        'generatedAt': stamp,
        'environment': environment,
        'defects': [
            {
                'key': f'{d.get("sheetName")}::{d.get("rowName")}',
                'id': d['defectId'],
                'status': d.get('actualStatus'),
                'reason': f'HTTP {d.get("actualStatus")} on non-proxy '
                          f'endpoint {d.get("endpoint")}',
            }
            for d in tagged
        ],
    }
    skip_file = out_dir / 'skiplist.json'
    skip_file.write_text(json.dumps(skip, indent=2), encoding='utf-8')

    report = out_dir / 'DEFECT-REPORT.html'
    report.write_text(
        _render_report(service, environment, tagged, proxy_5xx, stamp,
                       rel_spec),
        encoding='utf-8'
    )

    return {
        'dir': str(out_dir),
        'report_html': str(report),
        'skip_file': str(skip_file),
        'defects': [
            {
                'id': d['defectId'], 'row': d.get('rowName'),
                'method': d.get('method'), 'endpoint': d.get('endpoint'),
                'status': d.get('actualStatus'),
            }
            for d in tagged
        ],
    }


def _render_report(service: str, environment: str, defects: list[dict],
                   proxy_5xx: list[dict], stamp: str,
                   rel_spec: str = '') -> str:
    e = html.escape
    env = environment.upper()

    rows = ''.join(
        f'<tr><td class="mono">{e(d["defectId"])}</td>'
        f'<td>{e(str(d.get("rowName", "")))}</td>'
        f'<td class="mono">{e(str(d.get("method", "")))} '
        f'{e(str(d.get("endpoint", "")))}</td>'
        f'<td class="status bad">HTTP {e(str(d.get("actualStatus", "")))}</td>'
        f'<td>HTTP {e(str(d.get("expectedStatus", "")))}</td></tr>'
        for d in defects
    ) or '<tr><td colspan="5">No defect rows in this run.</td></tr>'

    sections = ''
    for d in defects:
        repro = (
            f'npx cross-env ENVIRONMENT={environment} playwright test '
            f'{rel_spec or "&lt;spec&gt;"} -g "{e(str(d.get("rowName", "")))}"'
        )
        sections += f'''
  <section class="defect">
    <h2><span class="mono id">{e(d["defectId"])}</span>
        {e(str(d.get("rowName", "")))}</h2>
    <table class="kv">
      <tr><th>Classification</th>
          <td>Defect. HTTP {e(str(d.get("actualStatus")))} server error on a
              non proxy endpoint.</td></tr>
      <tr><th>Environment</th><td>{e(env)}</td></tr>
      <tr><th>Request</th>
          <td class="mono">{e(str(d.get("method", "")))}
              {e(str(d.get("resolvedUrl") or d.get("endpoint", "")))}</td></tr>
      <tr><th>Expected status</th>
          <td>HTTP {e(str(d.get("expectedStatus", "")))}</td></tr>
      <tr><th>Actual status</th>
          <td class="status bad">HTTP {e(str(d.get("actualStatus", "")))}</td></tr>
      <tr><th>Response time</th>
          <td>{e(str(d.get("elapsedMs", "n/a")))} ms</td></tr>
      <tr><th>Captured at</th>
          <td class="mono">{e(str(d.get("capturedAt", "")))}</td></tr>
    </table>
    <h3>What happened</h3>
    <p>{e(_explanation(d, environment))}</p>
    <h3>Request headers</h3>
    <pre>{e(_fmt_json(d.get("requestHeaders")))}</pre>
    <h3>Request body</h3>
    <pre>{e(_fmt_json(d.get("requestBody")))}</pre>
    <h3>Response body</h3>
    <pre>{e(_fmt_json(d.get("responseBody")))}</pre>
    <h3>Reproduce</h3>
    <pre>{repro}</pre>
  </section>'''

    info = ''
    if proxy_5xx:
        items = ''.join(
            f'<li><span class="mono">{e(str(p.get("row", "")))}</span> '
            f'returned HTTP {e(str(p.get("status", "")))} on proxy endpoint '
            f'<span class="mono">{e(str(p.get("endpoint", "")))}</span> and '
            f'was auto accepted per the proxy rule.</li>'
            for p in proxy_5xx
        )
        info = f'''
  <section class="note">
    <h2>Informational: 5xx accepted on proxy endpoints</h2>
    <p>Proxy endpoints accept every status the system returns, so the rows
       below were written back to the excel and will pass. They are listed
       here so the team can decide whether any of them deserve a closer
       look.</p>
    <ul>{items}</ul>
  </section>'''

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Defect Report · {e(service)} · {e(env)} · {e(stamp)}</title>
<style>
  :root {{ --bg:#0D1117; --panel:#161B22; --border:#30363D; --text:#C9D1D9;
           --hi:#F0F6FC; --muted:#8B949E; --bad:#F85149; --accent:#58A6FF; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:36px 20px; background:var(--bg); color:var(--text);
          font:14px/1.6 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }}
  main {{ max-width:900px; margin:0 auto; }}
  h1 {{ color:var(--hi); font-size:22px; margin:0 0 4px; }}
  h2 {{ color:var(--hi); font-size:16px; margin:0 0 12px; }}
  h3 {{ color:var(--accent); font-size:12px; letter-spacing:.08em;
        text-transform:uppercase; margin:18px 0 6px; }}
  p {{ margin:6px 0; }}
  .meta {{ color:var(--muted); margin-bottom:22px; }}
  .mono {{ font-family:ui-monospace,'Cascadia Code',Consolas,monospace;
           font-size:12.5px; }}
  .id {{ color:var(--accent); margin-right:8px; }}
  .status.bad {{ color:var(--bad); font-weight:700; }}
  table.summary {{ width:100%; border-collapse:collapse; margin-bottom:26px;
                   background:var(--panel); }}
  table.summary th, table.summary td {{ border:1px solid var(--border);
        padding:8px 10px; text-align:left; font-size:13px; }}
  table.summary th {{ color:var(--muted); font-weight:600; }}
  section.defect, section.note {{ background:var(--panel);
        border:1px solid var(--border); border-radius:10px;
        padding:18px 20px; margin-bottom:22px; }}
  table.kv {{ border-collapse:collapse; width:100%; }}
  table.kv th {{ text-align:left; color:var(--muted); font-weight:600;
        padding:3px 14px 3px 0; white-space:nowrap; vertical-align:top;
        width:150px; }}
  table.kv td {{ padding:3px 0; }}
  pre {{ background:#0A0D12; border:1px solid var(--border); border-radius:8px;
         padding:10px 12px; overflow:auto; font-size:12px; margin:0; }}
  section.note {{ border-color:#3D3320; }}
  @media print {{ body {{ background:#fff; color:#111; }}
                  section.defect, section.note, table.summary {{
                      background:#fff; }} }}
</style>
</head>
<body>
<main>
  <h1>Defect Report · {e(service)}</h1>
  <div class="meta">Environment {e(env)} · generated {e(stamp)} by TestHub
       Automation Studio Smart Run. Rows below returned an HTTP 5xx server
       error on a non proxy endpoint. Their expected statuses were not
       changed in the excel and they were excluded from the evidence run.
       Raise each one as a bug using the details in its section.</div>
  <table class="summary">
    <tr><th>Defect</th><th>Scenario</th><th>Request</th><th>Actual</th>
        <th>Expected</th></tr>
    {rows}
  </table>
  {sections}
  {info}
</main>
</body>
</html>
'''
