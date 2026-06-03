#!/usr/bin/env python3
"""Audit every guide against the four Silver-tier gates (heuristic calibration only).

!!!!! NOT AUTHORITATIVE !!!!!

This script is a fast, line-count-based calibration signal useful during
active authoring. The authoritative Silver roster is produced by
`scripts/audit_silver.py`, which applies semantic checks (question
counts, role-delta markers, canonical IC.md sections, out-of-scope and
aggregator waivers per tier_model.md §9). The two scripts can disagree ---
when they do, `audit_silver.py` wins.

Use `audit_silver.py --summary` for the roster you quote to anyone.
Use this script only for fast feedback while you are authoring a guide and
want quick line-count-level signal on scaffolding gaps.

Per `docs/standards/00_universal/tier_model.md`, Silver = Bronze 9/9 plus:
  1. Source manifest PASS (audit_source_manifest.py, <30% TODO density)
  2. Real Appendix D (non-stub D_interview_prep.tex)
  3. Real interview_connections.md (>30 lines, 0 TODO/TBD placeholders)
  4. Non-stub dashboard (real qa-health metrics, not scaffold text)

Usage:
    scripts/audit_silver_fleet.py                # per-guide table
    scripts/audit_silver_fleet.py --summary      # counts only
    scripts/audit_silver_fleet.py --failing      # only guides that FAIL Silver
    scripts/audit_silver_fleet.py --guide SLUG   # single guide

Exit code: 0 if the fleet Silver PASS count meets --target (default 25).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tooling import discovery, layout, paths
from tooling.audits.fleet.audit_source_manifest import audit_guide as audit_manifest
MANIFEST_THRESHOLD = 30.0

# Stub-detection heuristics. Conservative: when the reader can eyeball a
# scaffolded placeholder, the regex catches it; when in doubt the gate passes,
# so spot-checking the non-stub count against the sweep-report baselines
# (27 non-stub IC.md, 72 non-stub Appendix D) is the calibration signal.
DASHBOARD_STUB_PHRASES = (
    "run `make qa-health`",
    "run make qa-health",
    "populated after content is authored",
    "todo: run health check",
    "dashboard not yet generated",
)
IC_STUB_PHRASES = (
    "no direct mapping to specific interview questions",
    "this course provides supporting knowledge",
    "questions will be mapped here",
)
APPENDIX_D_STUB_MIN_LINES = 100
IC_STUB_MIN_LINES = 30


def check_manifest(guide_dir: Path) -> tuple[bool, str]:
    failures = audit_manifest(guide_dir, MANIFEST_THRESHOLD)
    if not failures:
        return True, ""
    # Summarize: one-line reason, preferring the TODO-density message since
    # that is the gate blocking the 17 known FAILs.
    for f in failures:
        if "too many TODOs" in f:
            return False, f
    return False, failures[0]


def find_appendix_d(guide_dir: Path) -> Path | None:
    """Locate D_interview_prep.tex regardless of which per-guide layout is used."""
    path = layout.appendix_d(guide_dir)
    if path.exists():
        return path
    # Fallback: any file matching D_*.tex under appendices/ (either layout)
    parent = layout.appendices_dir(guide_dir)
    if parent.is_dir():
        matches = sorted(parent.glob("D_*.tex"))
        if matches:
            return matches[0]
    return None


def check_appendix_d(guide_dir: Path) -> tuple[bool, str]:
    path = find_appendix_d(guide_dir)
    if path is None:
        return False, "appendix_d_missing"
    text = path.read_text(errors="replace")
    nonblank = sum(1 for line in text.splitlines() if line.strip())
    if nonblank < APPENDIX_D_STUB_MIN_LINES:
        return False, f"appendix_d_stub ({nonblank} non-blank lines < {APPENDIX_D_STUB_MIN_LINES})"
    return True, ""


def check_ic_md(guide_dir: Path) -> tuple[bool, str]:
    path = layout.ic_md(guide_dir)
    if not path.exists():
        return False, "ic_missing"
    text = path.read_text(errors="replace")
    total_lines = len(text.splitlines())
    if total_lines < IC_STUB_MIN_LINES:
        return False, f"ic_stub ({total_lines} lines < {IC_STUB_MIN_LINES})"
    if re.search(r"\bTODO\b", text) or re.search(r"\bTBD\b", text):
        return False, "ic_has_todo_or_tbd"
    lower = text.lower()
    for phrase in IC_STUB_PHRASES:
        if phrase in lower:
            return False, f"ic_stub_phrase: {phrase!r}"
    return True, ""


def check_dashboard(guide_dir: Path) -> tuple[bool, str]:
    path = layout.dashboard(guide_dir)
    if not path.exists():
        return False, "dashboard_missing"
    text = path.read_text(errors="replace")
    lower = text.lower()
    for phrase in DASHBOARD_STUB_PHRASES:
        if phrase in lower:
            return False, f"dashboard_stub_phrase: {phrase!r}"
    # Real qa-health dashboards render a "| Status |" metrics table; absence
    # of that column is a strong stub signal.
    if "| status |" not in lower:
        return False, "dashboard_no_metrics_table"
    return True, ""


GATES = [
    ("Manifest", check_manifest),
    ("App-D", check_appendix_d),
    ("IC.md", check_ic_md),
    ("Dashboard", check_dashboard),
]


def audit_silver(guide_dir: Path) -> dict:
    results = {}
    for name, fn in GATES:
        ok, reason = fn(guide_dir)
        results[name] = {"pass": ok, "reason": reason}
    results["silver_pass"] = all(r["pass"] for r in results.values() if isinstance(r, dict))
    return results


def discover_guides() -> list[Path]:
    return discovery.iter_guide_dirs()


def format_row(name: str, results: dict, width: int) -> str:
    cells = []
    for gate, _ in GATES:
        cells.append("PASS" if results[gate]["pass"] else "FAIL")
    silver = "PASS" if results["silver_pass"] else "FAIL"
    return f"  {name:<{width}}  {cells[0]:<8}  {cells[1]:<6}  {cells[2]:<6}  {cells[3]:<10}  {silver}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--summary", action="store_true", help="Counts only, no per-guide rows")
    parser.add_argument("--failing", action="store_true", help="Only guides that FAIL Silver")
    parser.add_argument("--guide", help="Single guide slug")
    parser.add_argument("--target", type=int, default=25,
                        help="Exit 0 when Silver PASS count >= target (default 25)")
    args = parser.parse_args()

    if args.guide:
        target = paths.host_root() / args.guide
        if not target.is_dir():
            print(f"Workspace not found: {target}", file=sys.stderr)
            return 1
        guides = [target]
    else:
        guides = discover_guides()

    if not guides:
        print("No guides found.", file=sys.stderr)
        return 1

    width = max(len(g.name) for g in guides)
    gate_counts = {name: 0 for name, _ in GATES}
    silver_count = 0
    rows_printed = 0
    fail_details: list[tuple[str, dict]] = []

    if not args.summary and not args.failing and not args.guide:
        header = f"  {'Guide':<{width}}  {'Manifest':<8}  {'App-D':<6}  {'IC.md':<6}  {'Dashboard':<10}  Silver"
        print(header)
        print(f"  {'-' * width}  {'-' * 8}  {'-' * 6}  {'-' * 6}  {'-' * 10}  ------")

    for guide in guides:
        results = audit_silver(guide)
        for name, _ in GATES:
            if results[name]["pass"]:
                gate_counts[name] += 1
        if results["silver_pass"]:
            silver_count += 1

        if args.summary:
            continue
        if args.failing and results["silver_pass"]:
            continue
        if results["silver_pass"] or not args.failing:
            print(format_row(guide.name, results, width))
            rows_printed += 1
        if not results["silver_pass"]:
            fail_details.append((guide.name, results))

    total = len(guides)
    print()
    print(f"Silver PASS:   {silver_count}/{total}")
    for name, _ in GATES:
        print(f"  {name + ' PASS':<14} {gate_counts[name]}/{total}")

    if args.failing and fail_details:
        print("\nFirst-failing gate per FAIL guide:")
        for name, results in fail_details:
            for gate, _ in GATES:
                if not results[gate]["pass"]:
                    print(f"  {name:<{width}}  {gate:<10}  {results[gate]['reason']}")
                    break

    if args.guide:
        return 0 if silver_count == 1 else 1
    return 0 if silver_count >= args.target else 1


if __name__ == "__main__":
    sys.exit(main())
