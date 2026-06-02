#!/usr/bin/env python3
"""Generate stub ``review/dashboard.md`` files for guides missing them.

The Bronze auditor (:mod:`tooling.audits.fleet.audit_all_courses`) requires a
``review/dashboard.md`` to exist for each guide; the file itself is gitignored
derived data, so a freshly-carved publisher repo starts without it. This
regenerates a placeholder for every guide that lacks one, reading the guide
name + metric targets from ``guide_qa.yaml``.

Run from the host repo root (the consuming publisher repo):

    python -m tooling.generate.dashboards [--dry-run]

Iteration goes through :func:`tooling.discovery.iter_guide_dirs` and the write
path through :func:`tooling.layout.dashboard`, so it follows ``host_root()`` and
the ``guide/`` role layout. Existing dashboards are never overwritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import yaml

from tooling import discovery, layout


def generate_stub_dashboard(guide_name: str, metrics: dict) -> str:
    """Render placeholder dashboard markdown.

    Includes a ``| Status |`` metrics table (one row per ``guide_qa.yaml``
    metric) so the structure matches a real qa-health dashboard; the rows stay
    unpopulated, which is the honest signal that this is a stub awaiting
    ``make qa-health``.
    """
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Quality Dashboard: {guide_name} v1.0",
        "",
        f"Generated: {date}",
        "",
        "## Metrics",
        "",
        "| Status | Metric | Value | Target | Trend |",
        "|--------|--------|------:|-------:|-------|",
    ]
    for key, info in (metrics or {}).items():
        info = info if isinstance(info, dict) else {}
        desc = info.get("description", key)
        target = info.get("target", "?")
        lines.append(f"| [--] | {desc} | -- | {target} | = |")

    lines += [
        "",
        "## Summary",
        "",
        "Stub dashboard. Run `make qa-health` after content is authored to "
        "populate metrics.",
        "",
    ]
    return "\n".join(lines)


def _read_qa(qa_file: Path, fallback_name: str) -> tuple[str, dict]:
    with open(qa_file) as f:
        config = yaml.safe_load(f) or {}
    guide_name = config.get("guide", {}).get("name", fallback_name)
    metrics = config.get("metrics", {})
    return guide_name, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be created without writing",
    )
    args = parser.parse_args()

    created = 0
    for guide_dir in discovery.iter_guide_dirs():
        dashboard = layout.dashboard(guide_dir)
        if dashboard.exists():
            continue

        qa_file = guide_dir / "guide_qa.yaml"
        try:
            guide_name, metrics = _read_qa(qa_file, guide_dir.name)
        except Exception as e:  # noqa: BLE001 — surface, never fail the sweep
            print(f"  WARN  {guide_dir.name}: {e}")
            continue

        rel = dashboard.relative_to(guide_dir.parent)
        if args.dry_run:
            print(f"  WOULD CREATE  {rel}")
        else:
            dashboard.parent.mkdir(parents=True, exist_ok=True)
            dashboard.write_text(
                generate_stub_dashboard(guide_name, metrics), encoding="utf-8"
            )
            print(f"  CREATED  {rel}")
        created += 1

    action = "Would create" if args.dry_run else "Created"
    print(f"\n{action}: {created} dashboard file(s)")


if __name__ == "__main__":
    main()
