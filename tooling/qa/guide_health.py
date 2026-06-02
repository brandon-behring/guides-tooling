#!/usr/bin/env python3
"""
Config-driven quality dashboard for LaTeX course guides.

Reads metric definitions from guide_qa.yaml, runs shell commands to collect
current values, categorizes as GREEN/YELLOW/RED, detects regressions from
historical data, and generates a markdown dashboard report.

Usage:
    python guide_health.py --config guide_qa.yaml
    python guide_health.py                          # auto-find config
    python guide_health.py --json                   # machine-readable output
    python guide_health.py --dry-run                # show commands, don't run
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from tooling import layout
from tooling.qa.guide_qa_config import GuideConfig, MetricDef, load_config


# ── Traffic-light thresholds ────────────────────────────────────────────────

@dataclass
class MetricResult:
    """Result of evaluating a single metric."""

    name: str
    description: str
    value: int | None
    target: int
    yellow: int
    status: str  # GREEN, YELLOW, RED
    trend: str  # up, down, stable, new
    error: str | None = None


def categorize_metric(value: int, target: int, yellow: int, inverted: bool = False) -> str:
    """Categorize a metric value as GREEN, YELLOW, or RED.

    For normal metrics (higher is better): value >= target → GREEN.
    For inverted metrics (lower is better): value <= target → GREEN.
    """
    if inverted:
        if value <= target:
            return "GREEN"
        elif value <= yellow:
            return "YELLOW"
        return "RED"
    else:
        if value >= target:
            return "GREEN"
        elif value >= yellow:
            return "YELLOW"
        return "RED"


def compute_trend(current: int | None, previous: int | None) -> str:
    """Compute trend indicator from current vs previous value."""
    if current is None or previous is None:
        return "new"
    if current > previous:
        return "up"
    elif current < previous:
        return "down"
    return "stable"


# ── Shell command execution ─────────────────────────────────────────────────

def run_metric_check(check_cmd: str, config: GuideConfig) -> tuple[int | None, str | None]:
    """Run a metric check command and parse the last line as an integer.

    Commands run from the config file's parent directory.

    Returns:
        (value, error) — value is None if command failed.
    """
    try:
        result = subprocess.run(
            check_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(config.config_path.parent),
        )
        output = result.stdout.strip()

        if not output:
            # Some commands put output on stderr
            output = result.stderr.strip()

        if not output:
            return None, f"No output from: {check_cmd}"

        # Take the last line, try to parse as int
        last_line = output.strip().split("\n")[-1].strip()
        return int(last_line), None

    except subprocess.TimeoutExpired:
        return None, f"Timeout (30s): {check_cmd}"
    except ValueError:
        return None, f"Non-numeric output '{last_line}' from: {check_cmd}"
    except Exception as e:
        return None, f"Error running '{check_cmd}': {e}"


# ── History management ──────────────────────────────────────────────────────

def history_path(config: GuideConfig) -> Path:
    """Path to dashboard history file."""
    return config.review_dir / ".dashboard_history.yml"


def load_previous_metrics(config: GuideConfig) -> dict[str, int]:
    """Load most recent metric values from history."""
    hp = history_path(config)
    if not hp.exists():
        return {}

    with open(hp, "r", encoding="utf-8") as f:
        history = yaml.safe_load(f) or []

    if not history:
        return {}

    # Last entry's metrics
    return history[-1].get("metrics", {})


def save_metrics_history(config: GuideConfig, results: list[MetricResult]) -> None:
    """Append current metrics to history file."""
    hp = history_path(config)
    hp.parent.mkdir(parents=True, exist_ok=True)

    history = []
    if hp.exists():
        with open(hp, "r", encoding="utf-8") as f:
            history = yaml.safe_load(f) or []

    entry = {
        "timestamp": datetime.now().isoformat(),
        "version": config.version,
        "metrics": {r.name: r.value for r in results if r.value is not None},
    }
    history.append(entry)

    # Keep last 50 entries
    history = history[-50:]

    with open(hp, "w", encoding="utf-8") as f:
        yaml.dump(history, f, default_flow_style=False)


# ── Dashboard generation ────────────────────────────────────────────────────

STATUS_ICONS = {"GREEN": "G", "YELLOW": "Y", "RED": "R"}
TREND_ICONS = {"up": "^", "down": "v", "stable": "=", "new": "*"}


def evaluate_metrics(config: GuideConfig, dry_run: bool = False) -> list[MetricResult]:
    """Evaluate all metrics defined in config."""
    previous = load_previous_metrics(config)
    results = []

    for metric in config.metrics:
        if dry_run:
            print(f"  [DRY RUN] {metric.name}: {metric.check_cmd}")
            results.append(
                MetricResult(
                    name=metric.name,
                    description=metric.description,
                    value=None,
                    target=metric.target,
                    yellow=metric.yellow,
                    status="UNKNOWN",
                    trend="new",
                )
            )
            continue

        value, error = run_metric_check(metric.check_cmd, config)
        if value is not None:
            status = categorize_metric(value, metric.target, metric.yellow, metric.inverted)
        else:
            status = "RED"

        trend = compute_trend(value, previous.get(metric.name))

        results.append(
            MetricResult(
                name=metric.name,
                description=metric.description,
                value=value,
                target=metric.target,
                yellow=metric.yellow,
                status=status,
                trend=trend,
                error=error,
            )
        )

    return results


def generate_markdown_report(config: GuideConfig, results: list[MetricResult]) -> str:
    """Generate markdown dashboard report."""
    lines = [
        f"# Quality Dashboard: {config.name} v{config.version}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## Metrics",
        f"",
        f"| Status | Metric | Value | Target | Trend |",
        f"|--------|--------|------:|-------:|-------|",
    ]

    for r in results:
        icon = STATUS_ICONS.get(r.status, "?")
        trend = TREND_ICONS.get(r.trend, "?")
        val = str(r.value) if r.value is not None else "ERR"
        lines.append(f"| [{icon}] | {r.description} | {val} | {r.target} | {trend} |")

    # Summary
    green = sum(1 for r in results if r.status == "GREEN")
    yellow = sum(1 for r in results if r.status == "YELLOW")
    red = sum(1 for r in results if r.status == "RED")

    lines.extend([
        f"",
        f"## Summary",
        f"",
        f"- GREEN: {green}/{len(results)}",
        f"- YELLOW: {yellow}/{len(results)}",
        f"- RED: {red}/{len(results)}",
    ])

    # Regressions
    regressions = [r for r in results if r.trend == "down"]
    if regressions:
        lines.extend([
            f"",
            f"## Regressions Detected",
            f"",
        ])
        for r in regressions:
            lines.append(f"- {r.description}: value dropped to {r.value} (target: {r.target})")

    # Errors
    errors = [r for r in results if r.error]
    if errors:
        lines.extend([
            f"",
            f"## Errors",
            f"",
        ])
        for r in errors:
            lines.append(f"- {r.name}: {r.error}")

    return "\n".join(lines) + "\n"


# ── Card Health Metrics ────────────────────────────────────────────────────

@dataclass
class CardHealthResult:
    """Aggregate card health metrics for one guide."""

    guide: str
    total_cards: int
    cards_with_los: int
    traceability_pct: float
    presentation_issues: int
    presentation_clean_pct: float
    id_collisions: int
    status: str  # GREEN, YELLOW, RED


def _load_cards(cards_path: Path) -> list[dict]:
    """Load cards from all_cards.yml."""
    if not cards_path.exists():
        return []
    try:
        with open(cards_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "cards" in data:
            return data["cards"] or []
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _count_presentation_issues(cards: list[dict]) -> int:
    """Count P1 presentation issues (run-on lists, inline sections)."""
    import re

    patterns = [
        re.compile(r'(?<=\S)[^\n]*\s([1-9]\.)\s+[A-Z]'),  # run-on numbered
        re.compile(r'(?<=\S)[^\n]*\s\([a-z]\)\s+'),  # run-on lettered
        re.compile(r'(?<=\S)[^\n]*\s-\s+[A-Z]'),  # run-on bullets
        re.compile(
            r'(?:Approach|Context|Analysis|Solution|Framework):[^\n]*'
            r'(?:Approach|Context|Analysis|Solution|Framework):',
            re.IGNORECASE,
        ),
    ]
    count = 0
    for card in cards:
        back = card.get("back", "")
        for pat in patterns:
            if pat.search(back):
                count += 1
                break  # Count each card at most once
    return count


def evaluate_card_health(config: GuideConfig) -> CardHealthResult | None:
    """Evaluate card health metrics for the guide.

    Returns None if no card files exist.
    """
    guide_dir = config.config_path.parent
    # Cards live under guide/cards/ (the role layout).
    cards_path = layout.cards_yaml(guide_dir)
    if not cards_path.exists():
        cards_path = None

    if cards_path is None:
        return None

    cards = _load_cards(cards_path)
    if not cards:
        return None

    total = len(cards)
    with_los = sum(1 for c in cards if c.get("los_id"))
    traceability = (with_los / total * 100) if total > 0 else 0.0

    pres_issues = _count_presentation_issues(cards)
    clean_pct = ((total - pres_issues) / total * 100) if total > 0 else 0.0

    # ID collision detection
    ids = [c.get("id", "") for c in cards if c.get("id")]
    id_collisions = len(ids) - len(set(ids))

    # Overall status
    if traceability >= 80 and clean_pct >= 85 and id_collisions == 0:
        status = "GREEN"
    elif traceability >= 60 and clean_pct >= 70:
        status = "YELLOW"
    else:
        status = "RED"

    return CardHealthResult(
        guide=config.name,
        total_cards=total,
        cards_with_los=with_los,
        traceability_pct=round(traceability, 1),
        presentation_issues=pres_issues,
        presentation_clean_pct=round(clean_pct, 1),
        id_collisions=id_collisions,
        status=status,
    )


def card_health_markdown(result: CardHealthResult) -> str:
    """Generate card health section for the dashboard report."""
    icon = STATUS_ICONS.get(result.status, "?")
    lines = [
        "",
        "## Card Health",
        "",
        f"| Status | Metric | Value |",
        f"|--------|--------|------:|",
        f"| [{icon}] | Total cards | {result.total_cards} |",
        f"| [{icon}] | LOS traceability | {result.traceability_pct}% ({result.cards_with_los}/{result.total_cards}) |",
        f"| [{icon}] | Presentation clean | {result.presentation_clean_pct}% ({result.presentation_issues} issues) |",
        f"| [{icon}] | ID collisions | {result.id_collisions} |",
        "",
    ]
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Guide quality dashboard")
    parser.add_argument("--config", help="Path to guide_qa.yaml (auto-search if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without running")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--no-save", action="store_true", help="Don't save to history")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Dashboard: {config.name} v{config.version}")
    print(f"Config: {config.config_path}\n")

    results = evaluate_metrics(config, dry_run=args.dry_run)

    # Evaluate card health (optional — only if cards exist)
    card_result = evaluate_card_health(config)

    if args.json:
        data = [
            {
                "name": r.name,
                "description": r.description,
                "value": r.value,
                "target": r.target,
                "status": r.status,
                "trend": r.trend,
                "error": r.error,
            }
            for r in results
        ]
        if card_result:
            data.append({
                "name": "card_health",
                "description": "Card quality (traceability, presentation, collisions)",
                "value": card_result.total_cards,
                "target": 0,
                "status": card_result.status,
                "trend": "new",
                "error": None,
                "card_traceability_pct": card_result.traceability_pct,
                "card_presentation_clean_pct": card_result.presentation_clean_pct,
                "card_id_collisions": card_result.id_collisions,
            })
        print(json.dumps(data, indent=2))
    else:
        report = generate_markdown_report(config, results)
        if card_result:
            report += card_health_markdown(card_result)
        print(report)

        # Save report file
        if not args.dry_run:
            config.review_dir.mkdir(parents=True, exist_ok=True)
            report_path = config.review_dir / "dashboard.md"
            report_path.write_text(report, encoding="utf-8")
            print(f"Report saved: {report_path}")

    # Save history
    if not args.dry_run and not args.no_save:
        save_metrics_history(config, results)

    # Exit code: 1 if any RED
    if any(r.status == "RED" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
