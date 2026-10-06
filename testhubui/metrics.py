"""
TestHub value-metrics / ROI engine.

Turns real generation + test-run data into the numbers that justify the tool:
how many test scenarios the Studio produced, how many ran and passed, and the
engineering hours (and cost) that would otherwise have gone into hand-writing
and maintaining them.

Two inputs, both already produced by the pipeline:
  * generation summary — the manifest generator.generate() returns per asset
    ({'rows': N, 'bodyFormat': fmt, 'totalTime': secs, ...}); collect a list.
  * a Playwright JSON report — `playwright test --reporter=json` writes it;
    we read total/expected/unexpected/skipped and duration.

Assumptions are explicit and configurable (see ROIAssumptions) so the ROI number
is defensible in a pricing conversation, not a black box.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


@dataclass
class ROIAssumptions:
    # Minutes to hand-write one solid, data-driven API test (setup + payload
    # builder + assertions + a negative or two). Industry-typical 15-30; we
    # default to a conservative 20.
    minutes_per_test_manual: float = 20.0
    # Loaded hourly cost of a QA/SDET engineer (salary + overhead). Configurable
    # per market — e.g. ~$50/hr is conservative for many regions.
    engineer_hourly_rate: float = 50.0
    # Fraction of authoring effort re-incurred each time an API changes and the
    # suite must be reworked by hand. The Studio regenerates in seconds instead.
    annual_rework_factor: float = 0.5


def summarize_generation(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of generator.generate() result dicts."""
    per_format: dict[str, int] = {}
    total_rows = 0
    total_secs = 0.0
    for m in manifests:
        fmt = str(m.get("bodyFormat", "unknown"))
        rows = int(m.get("rows", 0))
        per_format[fmt] = per_format.get(fmt, 0) + rows
        total_rows += rows
        total_secs += float(m.get("totalTime", 0) or 0)
    return {
        "scenarios_generated": total_rows,
        "formats": len(per_format),
        "per_format": per_format,
        "generation_seconds": round(total_secs, 3),
    }


def summarize_runs(playwright_json: dict[str, Any]) -> dict[str, Any]:
    """Read a Playwright JSON report's top-level stats."""
    stats = playwright_json.get("stats", {}) or {}
    expected = int(stats.get("expected", 0))
    unexpected = int(stats.get("unexpected", 0))
    flaky = int(stats.get("flaky", 0))
    skipped = int(stats.get("skipped", 0))
    total = expected + unexpected + flaky + skipped
    duration_ms = float(stats.get("duration", 0) or 0)
    return {
        "tests_run": total,
        "passed": expected,
        "failed": unexpected,
        "flaky": flaky,
        "skipped": skipped,
        "pass_rate": round(expected / total, 4) if total else 0.0,
        "duration_seconds": round(duration_ms / 1000.0, 3),
    }


def compute_roi(scenarios_generated: int, a: ROIAssumptions) -> dict[str, Any]:
    """Hours and cost saved vs hand-authoring the same scenarios."""
    hours_manual = scenarios_generated * a.minutes_per_test_manual / 60.0
    authoring_cost = hours_manual * a.engineer_hourly_rate
    annual_rework_hours = hours_manual * a.annual_rework_factor
    annual_rework_cost = annual_rework_hours * a.engineer_hourly_rate
    return {
        "hours_saved_authoring": round(hours_manual, 1),
        "cost_saved_authoring": round(authoring_cost, 2),
        "annual_maintenance_hours_saved": round(annual_rework_hours, 1),
        "annual_maintenance_cost_saved": round(annual_rework_cost, 2),
        "first_year_cost_saved": round(authoring_cost + annual_rework_cost, 2),
        "assumptions": asdict(a),
    }


def build_report(manifests: list[dict[str, Any]],
                 playwright_json: dict[str, Any] | None = None,
                 assumptions: ROIAssumptions | None = None) -> dict[str, Any]:
    a = assumptions or ROIAssumptions()
    gen = summarize_generation(manifests)
    report: dict[str, Any] = {"generation": gen, "roi": compute_roi(gen["scenarios_generated"], a)}
    if playwright_json is not None:
        report["runs"] = summarize_runs(playwright_json)
    return report


def _load_json(p: str) -> dict[str, Any]:
    return json.loads(Path(p).read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="TestHub ROI / value metrics")
    ap.add_argument("--generation", help="JSON file: list of generate() manifests")
    ap.add_argument("--playwright", help="Playwright --reporter=json output file")
    ap.add_argument("--rate", type=float, default=50.0, help="engineer hourly rate")
    ap.add_argument("--minutes", type=float, default=20.0, help="minutes to hand-write one test")
    ap.add_argument("--out", default="-", help="output file or - for stdout")
    args = ap.parse_args()

    manifests = _load_json(args.generation) if args.generation else []
    pw = _load_json(args.playwright) if args.playwright else None
    a = ROIAssumptions(minutes_per_test_manual=args.minutes, engineer_hourly_rate=args.rate)
    report = build_report(manifests, pw, a)
    text = json.dumps(report, indent=2)
    if args.out == "-":
        print(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
