#!/usr/bin/env python3
"""
Audit solution quality for problem and vignette cards.

Adapted from interview_prep_series for course_learning guide layout.

Checks:
  - Solution content exists and is non-trivial
  - Key Insight section present (two-tier severity)
  - Answer section present
  - Approach section present
  - Solution length within reasonable bounds
  - Vignette rubric/answer presence

Usage:
    python shared/audits/audit_solution_quality.py                  # All Tier 1
    python shared/audits/audit_solution_quality.py --guide dlai_advanced_rag
    python shared/audits/audit_solution_quality.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_guide_by_slug,
)

# ── Constants ────────────────────────────────────────────────────────────────

SOLUTION_TYPES = {"problem", "vignette"}
MIN_SOLUTION_LEN = 50
SHORT_SOLUTION_LEN = 150
LONG_SOLUTION_THRESHOLD = 300
MAX_SOLUTION_LEN = 2000

KEY_INSIGHT_RE = re.compile(
    r"(?:\*\*Key\s+Insight[s]?\s*:?\s*\*\*|^\s*[-\u2022]\s*Key\s+Insight[s]?\s*:|Key\s+Insight[s]?\s*:)",
    re.IGNORECASE | re.MULTILINE,
)
ANSWER_RE = re.compile(
    r"(?:\*\*Answer\s*:?\s*\*\*|^\s*[-\u2022]\s*Answer\s*:|Answer\s*:)",
    re.IGNORECASE | re.MULTILINE,
)
APPROACH_RE = re.compile(
    r"(?:\*\*Approach\s*:?\s*\*\*|^\s*[-\u2022]\s*Approach\s*:|Approach\s*:)",
    re.IGNORECASE | re.MULTILINE,
)
VIGNETTE_RUBRIC_RE = re.compile(
    r"(?:\*\*(?:Answer\s*Rubric|Answer|Rubric|Solution|Response)\s*:?\s*\*\*"
    r"|(?:^|\n)\s*(?:Answer\s*Rubric|Answer|Rubric)\s*:)",
    re.IGNORECASE,
)

# ── Check functions ──────────────────────────────────────────────────────────


def check_solution_exists(back: str, card_type: str) -> tuple[str | None, str]:
    """Check if card has non-trivial solution content."""
    if not back or len(back.strip()) < MIN_SOLUTION_LEN:
        return "error", f"Solution missing or trivial ({len(back.strip()) if back else 0} chars)"
    return None, ""


def check_key_insight(back: str, card_type: str) -> tuple[str | None, str]:
    """Check for Key Insight section in problem cards."""
    if card_type != "problem":
        return None, ""
    if KEY_INSIGHT_RE.search(back):
        return None, ""
    back_len = len(back.strip())
    if back_len > LONG_SOLUTION_THRESHOLD:
        return "warning", f"Missing **Key Insight:** ({back_len} chars)"
    return "info", f"Missing **Key Insight:** ({back_len} chars)"


def check_answer(back: str, card_type: str) -> tuple[str | None, str]:
    """Check for Answer section in problem cards."""
    if card_type != "problem":
        return None, ""
    if ANSWER_RE.search(back):
        return None, ""
    back_len = len(back.strip())
    if back_len > LONG_SOLUTION_THRESHOLD:
        return "warning", f"Missing **Answer:** ({back_len} chars)"
    return "info", f"Missing **Answer:** ({back_len} chars)"


def check_approach(back: str, card_type: str) -> tuple[str | None, str]:
    """Check for Approach section in problem cards."""
    if card_type != "problem":
        return None, ""
    if APPROACH_RE.search(back):
        return None, ""
    return "info", "Missing **Approach:**"


def check_solution_length(back: str, card_type: str) -> tuple[str | None, str]:
    """Check if solution length is within bounds."""
    back_len = len(back.strip())
    if card_type == "problem" and MIN_SOLUTION_LEN <= back_len < SHORT_SOLUTION_LEN:
        return "warning", f"Solution suspiciously short ({back_len} chars)"
    if back_len > MAX_SOLUTION_LEN:
        return "info", f"Solution very long ({back_len} chars) — consider splitting"
    return None, ""


def check_vignette_rubric(back: str, card_type: str) -> tuple[str | None, str]:
    """Check vignette has answer/rubric content."""
    if card_type != "vignette":
        return None, ""
    if VIGNETTE_RUBRIC_RE.search(back):
        return None, ""
    back_len = len(back.strip())
    if back_len > LONG_SOLUTION_THRESHOLD:
        return "warning", "Vignette missing **Answer**/Rubric"
    return "info", "Vignette missing **Answer**/Rubric"


ALL_CHECKS = [
    check_solution_exists,
    check_key_insight,
    check_answer,
    check_approach,
    check_solution_length,
    check_vignette_rubric,
]


# ── Card assessment ──────────────────────────────────────────────────────────


def assess_card(card: dict[str, Any]) -> dict[str, Any] | None:
    """Assess solution quality for a single card. Returns None if not a solution type."""
    card_type = card.get("type", "")
    if card_type not in SOLUTION_TYPES:
        return None

    back = card.get("back", "")
    card_id = card.get("id", "unknown")
    issues: list[dict[str, str]] = []

    for check_fn in ALL_CHECKS:
        severity, reason = check_fn(back, card_type)
        if severity is not None:
            issues.append({"severity": severity, "reason": reason})

    error_count = sum(1 for i in issues if i["severity"] == "error")
    warning_count = sum(1 for i in issues if i["severity"] == "warning")

    if error_count > 0 or warning_count >= 3:
        classification = "deficient"
    elif warning_count > 0:
        classification = "partial"
    else:
        classification = "complete"

    return {
        "id": card_id,
        "type": card_type,
        "classification": classification,
        "issues": issues,
        "back_length": len(back.strip()) if back else 0,
    }


# ── Guide-level audit ────────────────────────────────────────────────────────


@dataclass
class GuideSolutionMetrics:
    """Solution quality metrics for a guide."""

    slug: str
    total_solution_cards: int = 0
    complete: int = 0
    partial: int = 0
    deficient: int = 0
    missing_key_insight: int = 0
    missing_answer: int = 0
    missing_approach: int = 0
    deficient_cards: list[dict] = field(default_factory=list)


def audit_guide_solutions(guide: GuideInfo, repo_root: Path) -> GuideSolutionMetrics | None:
    """Audit solution quality for a guide's cards."""
    cards_dir = guide.resolve_cards_dir(repo_root)
    if not cards_dir.exists():
        return None

    metrics = GuideSolutionMetrics(slug=guide.slug)

    # Prefer all_cards.yml (authoritative, from latest extraction) over
    # stale per-chapter files that may have older/incomplete content.
    all_cards_path = cards_dir / "all_cards.yml"
    if all_cards_path.exists():
        card_files = [all_cards_path]
    else:
        card_files = sorted(cards_dir.glob("*_cards.yml"))

    for cards_file in card_files:
        try:
            with open(cards_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            cards = data.get("cards", []) if isinstance(data, dict) else []
        except Exception:
            continue

        for card in cards:
            assessment = assess_card(card)
            if assessment is None:
                continue

            metrics.total_solution_cards += 1
            cls = assessment["classification"]
            if cls == "complete":
                metrics.complete += 1
            elif cls == "partial":
                metrics.partial += 1
            else:
                metrics.deficient += 1
                if len(metrics.deficient_cards) < 20:
                    metrics.deficient_cards.append(assessment)

            # Count specific missing sections
            for issue in assessment["issues"]:
                reason = issue["reason"]
                if "Key Insight" in reason:
                    metrics.missing_key_insight += 1
                elif "Answer" in reason and "Rubric" not in reason:
                    metrics.missing_answer += 1
                elif "Approach" in reason:
                    metrics.missing_approach += 1

    return metrics if metrics.total_solution_cards > 0 else None


# ── Reporting ────────────────────────────────────────────────────────────────


def print_report(all_metrics: list[GuideSolutionMetrics]) -> None:
    """Print human-readable solution quality report."""
    total = sum(m.total_solution_cards for m in all_metrics)
    total_complete = sum(m.complete for m in all_metrics)
    total_partial = sum(m.partial for m in all_metrics)
    total_deficient = sum(m.deficient for m in all_metrics)
    complete_pct = round(total_complete / total * 100, 1) if total else 0

    print("\n" + "=" * 60)
    print("SOLUTION QUALITY AUDIT — course_learning")
    print("=" * 60)
    print(f"\nGuides:           {len(all_metrics)}")
    print(f"Solution cards:   {total}")
    print(f"  Complete:       {total_complete} ({complete_pct}%)")
    print(f"  Partial:        {total_partial}")
    print(f"  Deficient:      {total_deficient}")

    total_ki = sum(m.missing_key_insight for m in all_metrics)
    total_ans = sum(m.missing_answer for m in all_metrics)
    total_app = sum(m.missing_approach for m in all_metrics)
    print(f"\nMissing sections:")
    print(f"  Key Insight:    {total_ki}")
    print(f"  Answer:         {total_ans}")
    print(f"  Approach:       {total_app}")

    print("\n" + "-" * 60)
    print(f"{'Guide':<48} {'Cards':>5} {'OK':>4} {'Part':>5} {'Def':>4}")
    print("-" * 60)
    for m in sorted(all_metrics, key=lambda x: -x.deficient):
        print(f"  {m.slug:<46} {m.total_solution_cards:>5} {m.complete:>4} {m.partial:>5} {m.deficient:>4}")

    print(f"\n{'=' * 60}")
    if complete_pct >= 80:
        print(f"PASS: {complete_pct}% of solution cards are complete")
    elif complete_pct >= 50:
        print(f"WARN: {complete_pct}% complete (target: 80%)")
    else:
        print(f"FAIL: {complete_pct}% complete (target: 80%)")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit solution quality")
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if <80%% complete")
    args = parser.parse_args()

    repo_root = get_repo_root()

    if args.guide:
        guide = get_guide_by_slug(args.guide)
        if guide is None:
            print(f"Error: guide '{args.guide}' not found", file=sys.stderr)
            sys.exit(1)
        guides = [guide]
    else:
        guides = get_tier1_guides()

    all_metrics: list[GuideSolutionMetrics] = []
    for guide in guides:
        result = audit_guide_solutions(guide, repo_root)
        if result:
            all_metrics.append(result)

    if not all_metrics:
        print("No solution cards found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        total = sum(m.total_solution_cards for m in all_metrics)
        total_complete = sum(m.complete for m in all_metrics)
        output = {
            "summary": {
                "guides": len(all_metrics),
                "total_solution_cards": total,
                "complete": total_complete,
                "complete_pct": round(total_complete / total * 100, 1) if total else 0,
                "partial": sum(m.partial for m in all_metrics),
                "deficient": sum(m.deficient for m in all_metrics),
            },
            "guides": [
                {
                    "slug": m.slug,
                    "total": m.total_solution_cards,
                    "complete": m.complete,
                    "partial": m.partial,
                    "deficient": m.deficient,
                    "missing_key_insight": m.missing_key_insight,
                    "missing_answer": m.missing_answer,
                    "missing_approach": m.missing_approach,
                }
                for m in all_metrics
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(all_metrics)

    if args.strict:
        total = sum(m.total_solution_cards for m in all_metrics)
        total_complete = sum(m.complete for m in all_metrics)
        if total and (total_complete / total * 100) < 80:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
