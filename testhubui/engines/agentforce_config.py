"""
TestHub Automation Studio — Agentforce Configuration engine.

Asked for on the Automation call, 30 Aug 2026 (MoM points 1-5). This is NOT the
`af` engine. That one emits AiEvaluationDefinition specs from utterances — a
generate-assets concern. This one manages `agentforce.config.ts` in the team's
`agentforce-testing-framework` repo and drives its runs: different input,
different verb, different output. Separate engine, per the registry contract.

The config file is HAND-WRITTEN and lives in someone else's repo. It carries a
comment block, a type annotation, and `org` / `waitMinutes` lines that read from
`.env`. Regenerating it from a template would destroy all of that, so this module
does a surgical merge instead: everything outside the `suites: [...]` array is
preserved byte for byte, and inside it, an entry whose key is untouched keeps its
original source — including any inline comment on it.

`merge_suites()` is pure, which is what lets it be tested without a repo. Reading
and writing the file is the caller's job, the same rule the perf workbook follows:
`render()` output must be a function of its input alone.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from .base import Assets, Row, field, register, section


_VALID_KEY = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_-]*$')


def validate_key(s: str) -> str:
    """A suite key reaches a CLI as `--test <key>` and becomes a result filename.

    VALIDATED, never sanitised. Stripping the bad characters instead would turn
    `../../etc/passwd` into `etcpasswd` and write that into the team's config —
    a key the user never typed, silently, for a suite that does not exist. The
    leading character is constrained separately so a key can never be read as a
    flag: `--force` is a valid identifier to a sanitiser and an argument to a CLI.
    """
    key = str(s or '').strip()
    if not _VALID_KEY.match(key):
        raise ValueError(
            f'Suite key "{key}" is not usable: it is passed to the CLI as --test <key> '
            'and used as a result filename, so it must be letters, digits, - or _, and '
            'must not start with a dash.')
    return key


# ── The config file ─────────────────────────────────────────────────────────

def _suites_span(text: str) -> tuple[int, int] | None:
    """Indices of the `[...]` following `suites:`, bracket-matched.

    Quote-aware: a bracket inside a suite name is data, not structure. Returns
    None when there is no suites array, which the caller reports rather than
    silently "fixing" by inventing one.
    """
    m = re.search(r'\bsuites\s*:\s*\[', text)
    if not m:
        return None
    start = m.end() - 1
    depth, i, n = 0, start, len(text)
    in_str, quote, esc = False, '', False
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == quote:
                in_str = False
        elif c in '"\'`':
            in_str, quote = True, c
        elif c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return None


def _entry_spans(body: str) -> list[tuple[int, int]]:
    """Top-level `{...}` spans inside the array body, quote-aware."""
    spans, depth, begin = [], 0, None
    in_str, quote, esc = False, '', False
    for i, c in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == quote:
                in_str = False
            continue
        if c in '"\'`':
            in_str, quote = True, c
        elif c == '{':
            if depth == 0:
                begin = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and begin is not None:
                spans.append((begin, i + 1))
                begin = None
    return spans


_KEY_RE = re.compile(r'\bkey\s*:\s*(["\'])(.*?)\1', re.IGNORECASE)
_NAME_RE = re.compile(r'\bsfSuiteName\s*:\s*(["\'])(.*?)\1', re.IGNORECASE)


def parse_suites(text: str) -> list[dict]:
    """Suites currently declared in the file, in file order.

    Case-insensitive on the field names on purpose: the screenshot of the real
    file shows a hand-added entry written `Key:` rather than `key:`. Reading it
    as a different field would silently duplicate the suite on the next merge.
    """
    span = _suites_span(text)
    if span is None:
        return []
    body = text[span[0] + 1:span[1] - 1]
    out = []
    for a, b in _entry_spans(body):
        chunk = body[a:b]
        k, n = _KEY_RE.search(chunk), _NAME_RE.search(chunk)
        if k:
            out.append({'key': k.group(2), 'sfSuiteName': n.group(2) if n else ''})
    return out


class ConfigError(ValueError):
    """The file is not in a shape this merge understands. Never guess past it."""


def merge_suites(text: str, incoming: list[dict]) -> tuple[str, dict]:
    """Update-or-append suites, preserving everything else. PURE.

    Update  — an incoming key that already exists rewrites only its sfSuiteName
              string, in place, so a comment or extra field on that entry survives.
    Append  — a new key is added at the end of the array, matching the indentation
              already in use rather than imposing this module's own.
    Untouched — an existing entry not mentioned by the caller is left byte for byte.

    Nothing is ever removed. Deleting a suite from someone else's config because it
    was absent from a form submission is not an edit anyone asked for.
    """
    span = _suites_span(text)
    if span is None:
        raise ConfigError(
            'No `suites: [ ... ]` array found in agentforce.config.ts. '
            'Point the Studio at the real file, or add the array first — this will '
            'not invent one, because writing a config the framework never declared '
            'is how a run silently tests nothing.')

    lo, hi = span
    body = text[lo + 1:hi - 1]
    existing = parse_suites(text)
    by_key = {s['key']: s for s in existing}

    seen, updated, added = set(), [], []
    new_body, cursor = [], 0
    for a, b in _entry_spans(body):
        chunk = body[a:b]
        km = _KEY_RE.search(chunk)
        key = km.group(2) if km else None
        seen.add(key)
        want = next((s for s in incoming if s['key'] == key), None)
        if want and want['sfSuiteName'] != by_key.get(key, {}).get('sfSuiteName'):
            nm = _NAME_RE.search(chunk)
            if nm:
                q = nm.group(1)
                chunk = chunk[:nm.start()] + f'sfSuiteName: {q}{want["sfSuiteName"]}{q}' + chunk[nm.end():]
            else:
                chunk = chunk.rstrip()[:-1].rstrip().rstrip(',') + \
                    f',\n            sfSuiteName: "{want["sfSuiteName"]}"\n        }}'
            updated.append(key)
        new_body.append(body[cursor:a] + chunk)
        cursor = b
    new_body.append(body[cursor:])
    body = ''.join(new_body)

    fresh = [s for s in incoming if s['key'] not in seen]
    if fresh:
        # Match the file's own indentation rather than imposing ours: this file is
        # read by people, and a merge that reformats reads as a rewrite in review.
        spans = _entry_spans(body)
        if spans:
            line_start = body.rfind('\n', 0, spans[-1][0]) + 1
            entry_indent = body[line_start:spans[-1][0]]
            inner_indent = entry_indent + '    '
        else:
            entry_indent, inner_indent = '        ', '            '
        blocks = [
            f'{entry_indent}{{\n{inner_indent}key: "{s["key"]}",\n'
            f'{inner_indent}sfSuiteName: "{s["sfSuiteName"]}"\n{entry_indent}}}'
            for s in fresh]
        added = [s['key'] for s in fresh]
        if spans:
            tail = body[spans[-1][1]:]
            body = body[:spans[-1][1]] + ',\n' + ',\n'.join(blocks) + tail
        else:
            body = '\n' + ',\n'.join(blocks) + '\n' + (entry_indent[:-4] or '')

    return text[:lo] + '[' + body + ']' + text[hi:], {
        'updated': updated, 'added': added,
        'unchanged': [k for k in by_key if k not in updated],
    }


# ── Running ─────────────────────────────────────────────────────────────────
#
# MoM point 5: "Once we select Execute Tests it has ask for QA, UAT. it has pick
# the command once we select the QA options or UAT option." The same MoM records
# who supplies it — "the client has to provide the command" — and it has not arrived.
#
# So the table is declared and empty. The selector, the key selection and the
# wiring are built; the command string is one entry away. It is NOT guessed:
# the only clue in the repo is the comment `--test <key>`, which does not say
# whether QA/UAT is an org alias, an --env flag or a separate npm script, and a
# wrong guess here runs against a live Salesforce org.
ENVIRONMENTS = ('QA', 'UAT')

COMMANDS: dict[str, list[str]] = {
    'QA': [],
    'UAT': [],
}


def command_for(env: str, keys: list[str]) -> list[str]:
    """Argv for an environment, or [] when the command has not been supplied.

    Returns a list, never a string: the suite keys are user input, and building a
    shell string out of them is the injection this avoids by construction.
    """
    template = COMMANDS.get((env or '').upper()) or []
    if not template:
        return []
    argv = []
    for token in template:
        argv.append('--test' if token == '{keys}' else token)
        if token == '{keys}':
            argv.append(','.join(keys))
    return argv


class AgentforceConfigEngine:
    id = 'afc'
    title = 'Agentforce Configuration'
    emits_assets = False

    @property
    def can_execute(self) -> bool:
        # Honest: a run needs the sf CLI AND the framework repo AND a command that
        # has not been supplied yet. The last one is why this is False today.
        return bool(command_for('QA', ['x'])) and shutil.which('sf') is not None

    def preflight(self) -> tuple[bool, str]:
        sf = shutil.which('sf')
        missing = []
        if not sf:
            missing.append('the sf CLI is not installed')
        if not any(COMMANDS.values()):
            missing.append('no QA/UAT command has been supplied yet (owner: the client, per the '
                           '30 Aug MoM) — keys can be configured and written, but not run')
        if missing:
            return True, ('Configures agentforce.config.ts in the framework repo. '
                          'Cannot run here: ' + '; '.join(missing) + '.')
        return True, f'sf found at {sf} — suites can be configured and run.'

    def schema(self):
        return [
            section('Framework Repo', [
                field('frameworkRoot', 'agentforce-testing-framework path', width='full',
                      required=True, placeholder='/path/to/agentforce-testing-framework',
                      hint='The repo holding agentforce.config.ts. This engine EDITS that file '
                           'in place, so it is never defaulted — an empty path writes nothing.'),
            ], note='org and waitMinutes are not set here. The config reads them from that repo\'s '
                    '.env (SF_ORG_ALIAS, SF_WAIT_MINUTES), and this merge leaves those lines alone.'),
            section('Agentforce Configuration', [
                field('suites', 'Suites', 'rows', width='full',
                      options=['key', 'sfSuiteName'],
                      hint='key = the short identifier the CLI takes as --test <key>, and the one '
                           'result files are named after. sfSuiteName = the suite name exactly as '
                           'it reads in the Agentforce Testing Center UI.'),
            ], note='Update or append only. A key already in the file has its sfSuiteName rewritten '
                    'in place; a new key is appended; anything already there and not listed here is '
                    'left untouched. Nothing is ever removed.'),
            section('Execute Tests', [
                field('environment', 'Environment', 'select', options=list(ENVIRONMENTS), default='QA',
                      hint='Picks which command runs. Neither is supplied yet.'),
            ], note='Run Selected runs the keys you tick; Run All runs every key in the file. '
                    'Both are wired and both will refuse until the QA/UAT command is supplied.'),
        ]

    def build_matrix(self, cfg: dict) -> list[Row]:
        rows_in = cfg.get('suites') or []
        if not rows_in:
            raise ValueError('Add at least one suite — a key and its Agentforce suite name.')
        out = []
        for s in rows_in:
            key = validate_key(s.get('key'))
            name = str(s.get('sfSuiteName') or '').strip()
            if not name:
                raise ValueError(f'Suite "{key}" needs its Agentforce Testing Center suite name.')
            out.append(Row(name=f'{key} → {name}', kind='positive',
                           detail=f'CLI --test {key}; results are named after the key.',
                           data={'key': key, 'sfSuiteName': name}))
        return out

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        """This engine writes no assets — it edits a file in another repo.

        That edit needs the file's current contents, so it cannot happen here:
        render() must stay pure. `/api/agentforce/config` reads, merges and writes.
        """
        return Assets(rows=len(rows), sheet='agentforce')


engine = register(AgentforceConfigEngine())
