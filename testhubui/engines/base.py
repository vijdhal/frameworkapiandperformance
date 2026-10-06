"""
TestHub Automation Studio — engine contract.

Every testing capability in the rail (UI, Mobile, Salesforce, Performance,
Security, Agentforce, AI Agentic) is an Engine. An Engine turns captured test
intent into governed, runnable assets.

The contract exists to stop the thing that would otherwise kill this codebase:
`generator.py` already carries six near-duplicate renderers and four
near-duplicate matrix builders across ONE axis (body format). Adding engines as
a second axis by the same copy-paste method is multiplicative. A new engine is
a new module implementing this interface plus one line of registration — no
edits to shared files.

Two capabilities are declared separately and honestly:

    emits_assets     — the engine can produce governed assets offline.
    can_execute      — the engine's runtime exists and can be driven locally.

Nothing may claim `can_execute` unless it has been proven to run. Mobile needs a
booted device; Performance needs the k6 binary; Agentforce and AI Agentic need
live endpoints that do not exist on a laptop. Declaring that truthfully in code
is what keeps the rail's badges honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class Row:
    """One governed scenario. Becomes one test and one spreadsheet row."""
    name: str
    kind: str                       # 'positive' | 'negative'
    detail: str = ''
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Assets:
    """What an engine produced. `files` maps absolute path -> content."""
    files: dict[Path, str | bytes] = field(default_factory=dict)
    rows: int = 0
    sheet: str = ''
    # Side effects that are not files, for app.py to apply after the write —
    # e.g. npm scripts to merge into another repo's package.json. Kept out of
    # `files` so the overwrite guard and the write stay about files.
    extras: dict = field(default_factory=dict)

    def add(self, path: Path, content: str | bytes) -> None:
        self.files[path] = content


def field(key, label, kind='text', placeholder='', hint='', options=None,
          required=False, width='half', default=''):
    """One control in an engine's intent form.

    Engines describe their form declaratively and the Studio renders it. This is
    the same registry principle applied to the UI: a new engine ships a schema
    and needs zero frontend code.
    """
    return {'key': key, 'label': label, 'kind': kind, 'placeholder': placeholder,
            'hint': hint, 'options': options or [], 'required': required,
            'width': width, 'default': default}


def section(title, fields, note=''):
    return {'title': title, 'fields': fields, 'note': note}


class Engine(Protocol):
    id: str
    title: str
    emits_assets: bool
    can_execute: bool

    def schema(self) -> list[dict]:
        """Declarative intent form — a list of section() dicts."""
        ...

    def preflight(self) -> tuple[bool, str]:
        """Is this engine's runtime actually available here?

        Returns (ready, human-readable reason). The Studio shows the reason
        verbatim rather than a stack trace or a silent no-op — a missing k6
        binary must read as 'k6 is not installed', never as a failed run.
        """
        ...

    def build_matrix(self, cfg: dict) -> list[Row]:
        """Captured intent -> the governed scenario set. No I/O."""
        ...

    def render(self, cfg: dict, rows: list[Row]) -> Assets:
        """Scenario set -> files. Pure: same input, same bytes.

        Purity is what makes golden-file tests possible, which is the gap
        `generator.py` currently has.
        """
        ...


# ───────────────────────── registry ─────────────────────────

_ENGINES: dict[str, Engine] = {}

# 16 Sep client call: ship only the complete functional areas — API (wired
# directly in app.py, not through this registry) and Performance. Gating
# happens here, at registration, rather than by deleting each engine module,
# so turning a capability back on once its accelerator is complete is one
# line: add its id to this set. An id outside it never reaches `catalog()`
# or `get()`, so it cannot be listed OR driven via the API — not just hidden
# from the rail.
ACTIVE_ENGINE_IDS = {'perf'}


def register(engine: Engine) -> Engine:
    if engine.id in _ENGINES:
        raise ValueError(f'engine id already registered: {engine.id}')
    if engine.id not in ACTIVE_ENGINE_IDS:
        return engine
    _ENGINES[engine.id] = engine
    return engine


def get(engine_id: str) -> Engine | None:
    return _ENGINES.get(engine_id)


def catalog() -> list[dict]:
    """Everything the rail needs to render honest badges."""
    out = []
    for e in _ENGINES.values():
        # One engine's preflight or schema raising must not take the other nine
        # down with it. Before this, a single exception here 500'd /api/engines,
        # the rail's fetch swallowed the failure, and every schema-driven panel
        # opened empty — Performance, Security, Agentforce, all of them — with
        # nothing on screen or in the log to say why. The broken engine now
        # reports itself as not ready, with the exception as its reason.
        try:
            ready, reason = e.preflight()
        except Exception as exc:                      # noqa: BLE001 — surfaced, not hidden
            ready, reason = False, f'preflight failed: {type(exc).__name__}: {exc}'
        try:
            schema = e.schema() if hasattr(e, 'schema') else []
        except Exception as exc:                      # noqa: BLE001
            schema, ready = [], False
            reason = f'schema failed: {type(exc).__name__}: {exc}'
        out.append({
            'id': e.id,
            'title': e.title,
            'emitsAssets': e.emits_assets,
            'canExecute': e.can_execute,
            'ready': ready,
            'reason': reason,
            # An engine with no schema() is not an error: `api`, `ui` and `sf`
            # predate the declarative panel and ship hand-built HTML instead.
            # But the two cases must stay TELLABLE APART. A bare `else []` reads
            # in the payload as "this engine has zero fields", which is exactly
            # what a NEW engine wired to the generic panel and missing its
            # schema also looks like — and that renders as an empty panel with
            # no error anywhere. `hasSchema` lets the frontend say "bespoke
            # panel" instead of silently drawing nothing.
            'hasSchema': hasattr(e, 'schema'),
            'schema': schema,
        })
    return sorted(out, key=lambda d: d['id'])


# Every generated text asset carries this in its header. It is the only
# reliable way to tell "a file this tool wrote" from "a file a human wrote",
# and that distinction is what makes overwrite safe to automate.
GENERATED_MARKER = 'GENERATED by TestHub'

# Relative engine defaults resolve against the STUDIO root (see app.py), so
# they name their accelerator. The Playwright gate specs of every engine land
# in the API accelerator's testDir; that is what puts them in the Ortoni report.
API_DIR = 'testhub-api-quality-accelerator'
SPEC_DIR_DEFAULT = API_DIR + '/src/tests'
# The client's parent layout: one testhub-<x>-quality-accelerator per framework.
ACCEL = {
    'ui': 'testhub-ui-quality-accelerator',
    'ai': 'testhub-ai-agentic-quality-accelerator',
    'sf': 'testhub-salesforce-quality-accelerator',
    'perf': 'testhub-performance-quality-accelerator',
    'mob': 'testhub-mobile-quality-accelerator',
    'sec': 'testhub-security-quality-accelerator',
    'llmsec': 'testhub-llm-security-quality-accelerator',
    'af': 'testhub-agentforce-quality-accelerator',
    'contract': 'testhub-contract-quality-accelerator',
}


class WouldClobber(Exception):
    """Raised instead of destroying a file the Studio did not write.

    The workflow that motivates this is the normal one, not an exotic one: a
    QA engineer generates a spec, hand-edits it to add the assertions only a
    human knows to add, then regenerates to pick up a new scenario. Before
    this, that silently destroyed every edit and still returned ok:true.

    Regenerating a file the Studio itself produced stays silent — that is the
    intended loop and prompting on it would train people to click through.
    """

    def __init__(self, paths: list[str]):
        self.paths = paths
        # Kept SHORT on purpose. The frontend renders this in a toast that has
        # no max-width and clears itself in a few seconds, so a message full of
        # absolute paths is a message nobody reads. Lead with the decision and
        # the remedy; name files by basename; hand the full paths to callers
        # through .paths / the wouldClobber field instead.
        names = ', '.join(Path(p).name for p in paths[:3])
        if len(paths) > 3:
            names += f' (+{len(paths) - 3} more)'
        # Only offers what the Studio UI can actually do. There is no Overwrite
        # control on the page yet — the overwrite:true flag exists for API
        # callers — so pointing a tester at a button that is not there would
        # turn a clear refusal back into a dead end.
        super().__init__(
            f'Not overwriting {len(paths)} file(s) that were edited by hand: '
            f'{names}. Move or rename them, then generate again.')


def _ooxml_marked(path: Path) -> bool:
    """True if an OOXML file (.xlsx and friends) carries the marker in its
    document properties.

    Needed because OOXML is a ZIP: the marker is written into
    `docProps/core.xml` but stored deflated, so scanning the raw bytes never
    finds it. Without this, an engine that emits a workbook is treated as
    having produced a file it did not write, and blocks its OWN next
    regenerate — the exact failure the text-file marker exists to prevent,
    reappearing the moment an asset is binary.
    """
    if path.suffix.lower() not in ('.xlsx', '.xlsm', '.docx', '.pptx'):
        return False
    try:
        import zipfile
        with zipfile.ZipFile(path) as archive:
            core = archive.read('docProps/core.xml').decode('utf-8', errors='replace')
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    return GENERATED_MARKER.lower() in core.lower()


def _is_ours(path: Path) -> bool:
    """True if `path` looks like something a previous generate() produced."""
    try:
        head = path.read_text(encoding='utf-8', errors='replace')[:4000]
    except (OSError, UnicodeError):
        return _ooxml_marked(path)      # undecodable -> may still be our workbook
    # Case-insensitive on purpose. The marker sits in a TS comment banner in
    # most assets, but in package.json it is a "description" value, where
    # SHOUTING would read as a mistake. Matching loosely costs nothing and
    # stops the guard blocking an engine's own regenerate over letter case.
    if GENERATED_MARKER.lower() in head.lower():
        return True
    # An .xlsx decodes to mojibake rather than raising, so the fallback above is
    # never reached for one. Check its properties before declaring it precious.
    return _ooxml_marked(path)


def _same(path: Path, content) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return data == (content if isinstance(content, bytes) else str(content).encode('utf-8'))


def write(assets: Assets, overwrite: bool = False) -> list[str]:
    """Commit an Assets bundle to disk. Returns the paths written.

    Refuses, before writing ANYTHING, if the bundle would clobber a file the
    Studio did not generate. Checked up front so a rejected bundle leaves the
    tree untouched rather than half-written.
    """
    if not overwrite:
        # A file that is byte-for-byte what we are about to write is not being
        # clobbered, marker or no marker. Matters for the payload JSON the perf
        # engine emits: it must be exactly the body, so it cannot carry a marker,
        # and without this a plain regenerate refused over the Studio's own output.
        clobber = [str(p) for p in assets.files
                   if p.exists() and p.is_file() and not _is_ours(p) and not _same(p, assets.files[p])]
        if clobber:
            raise WouldClobber(sorted(clobber))

    written = []
    for path, content in assets.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            # newline='': text mode's universal-newline translation would turn
            # every '\n' into '\r\n' on Windows, so a markerless file (payload
            # JSON, and now the perf engine's profiles.json / <slug>-scenario.json)
            # never reads back byte-identical to what was just generated — _same()
            # then calls a plain regenerate a hand-edit and refuses it.
            path.write_text(content, encoding='utf-8', newline='')
        written.append(str(path))
    return written
