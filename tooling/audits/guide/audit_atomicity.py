#!/usr/bin/env python3
"""Audit card atomicity across course learning guides.

Detects cards that violate the minimum information principle by testing
multiple concepts, containing too many steps, or exceeding length limits.
Uses string heuristics on card YAML — no NLP or LaTeX parsing required.

Steps:
  1. Parse all_cards.yml per guide
  2. Apply per-type atomicity heuristics (steps, questions, sections, length)
  3. Classify: atomic / borderline / compound
  4. Generate structured YAML report

Audit-only — does not modify any files.

Usage:
    python shared/audits/audit_atomicity.py
    python shared/audits/audit_atomicity.py --guide dlai_advanced_rag
    python shared/audits/audit_atomicity.py --report
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from tooling.audits.guide._guide_scope import (
    cards_dir,
    get_repo_root,
    guide_dir_for_slug,
    guide_dirs,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Card types to audit for atomicity
_AUDITABLE_TYPES = {
    "problem", "vignette", "keyconcept", "term", "drill", "redflag",
    "interview", "interviewcontext", "pitfall", "interviewtip", "decisiontree",
}

# Card types structurally multi-part by design — exempt from atomicity checks
_EXEMPT_TYPES = {
    "cloze", "formula", "comparison",
}

# Per-type thresholds
_THRESHOLDS: dict[str, dict[str, int]] = {
    "problem": {"max_steps": 5, "max_back_len": 1000},
    "vignette": {"max_questions": 4, "max_back_len": 1000},
    "keyconcept": {"max_sections": 4, "max_back_len": 800},
    "term": {"max_back_len": 500},
    "drill": {"max_back_len": 300},
    "_default": {"max_back_len": 1000},
}


# ---------------------------------------------------------------------------
# Heuristic counting functions
# ---------------------------------------------------------------------------

def count_step_markers(back: str) -> int:
    """Count **Step N:** markers in card back."""
    return len(re.findall(r"\*\*Step\s+\d+", back))


def count_question_markers(back: str) -> int:
    """Count Question/Q markers in card back."""
    return len(re.findall(
        r"(?:\*\*Q\d+|\*\*Question\s+\d+|(?<!\w)Question\s+\d+:)", back
    ))


def count_section_headers(back: str) -> int:
    """Count **Header:** sections in card back."""
    return len(re.findall(r"\*\*[A-Z][^*]+:\*\*", back))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_atomicity(card: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify a card as atomic, borderline, or compound.

    Returns:
        Tuple of (severity, list_of_reasons).
    """
    card_type = card.get("type", "")
    back = card.get("back", "")
    reasons: list[str] = []

    if card_type in _EXEMPT_TYPES:
        return "atomic", []
    if card_type not in _AUDITABLE_TYPES:
        return "atomic", []

    thresholds = _THRESHOLDS.get(card_type, _THRESHOLDS["_default"])
    back_len = len(back)

    # Type-specific checks
    if card_type == "problem":
        steps = count_step_markers(back)
        max_steps = thresholds["max_steps"]
        if steps > max_steps:
            reasons.append(f"{steps} steps (threshold: {max_steps})")

    elif card_type == "vignette":
        questions = count_question_markers(back)
        max_q = thresholds["max_questions"]
        if questions > max_q:
            reasons.append(f"{questions} questions (threshold: {max_q})")

    elif card_type == "keyconcept":
        sections = count_section_headers(back)
        max_sec = thresholds["max_sections"]
        if sections > max_sec:
            reasons.append(f"{sections} sections (threshold: {max_sec})")

    # Universal length check
    max_len = thresholds.get("max_back_len", _THRESHOLDS["_default"]["max_back_len"])
    if back_len > max_len:
        reasons.append(f"back length {back_len} chars (threshold: {max_len})")

    # Classify severity
    if not reasons:
        return "atomic", []
    elif len(reasons) == 1:
        return "borderline", reasons
    else:
        return "compound", reasons


def suggest_action(card: dict[str, Any], reasons: list[str]) -> str:
    """Generate a split/fix suggestion for non-atomic cards."""
    card_type = card.get("type", "")

    if card_type == "problem":
        if any("steps" in r for r in reasons):
            return "Split at step boundaries (use split_long_cards.py)"
        return "Consider condensing solution or splitting approach vs calculation"

    if card_type == "vignette":
        if any("questions" in r for r in reasons):
            return "Split at question boundaries (use split_long_cards.py)"
        return "Reduce question count or split into multiple vignette cards"

    if card_type == "keyconcept":
        return "Extract secondary insights into separate keyconcept cards"

    if card_type == "term":
        return "Shorten definition or extract sub-concepts as separate term cards"

    if card_type == "drill":
        return "Trim answer to essential — drills should be quick recall"

    return "Review for multiple concepts; consider splitting"


# ---------------------------------------------------------------------------
# Guide scanning
# ---------------------------------------------------------------------------

def load_cards(cards_path: Path) -> list[dict[str, Any]]:
    """Load cards from a YAML file."""
    if not cards_path.exists():
        return []
    try:
        with open(cards_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return []
        if isinstance(data, dict) and "cards" in data:
            return data["cards"] or []
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def find_guide_dirs() -> list[str]:
    """Slugs of guides that carry an all_cards.yml (topic-nested, discovery-based)."""
    return [
        d.name for d in guide_dirs()
        if (cards_dir(d) / "all_cards.yml").exists()
    ]


def scan_guide(guide_name: str) -> dict[str, Any]:
    """Scan a guide's cards for atomicity issues."""
    guide_dir = guide_dir_for_slug(guide_name)
    cards_path = (cards_dir(guide_dir) / "all_cards.yml") if guide_dir else Path()
    cards = load_cards(cards_path)

    result: dict[str, Any] = {
        "guide": guide_name,
        "total": 0,
        "atomic": 0,
        "borderline": 0,
        "compound": 0,
        "issues": [],
    }

    for card in cards:
        card_type = card.get("type", "")
        if card_type in _EXEMPT_TYPES or card_type not in _AUDITABLE_TYPES:
            continue

        result["total"] += 1
        severity, reasons = classify_atomicity(card)

        if severity == "atomic":
            result["atomic"] += 1
        elif severity == "borderline":
            result["borderline"] += 1
            result["issues"].append({
                "id": card.get("id", "unknown"),
                "type": card_type,
                "guide": guide_name,
                "severity": "borderline",
                "reasons": reasons,
                "suggestion": suggest_action(card, reasons),
            })
        else:
            result["compound"] += 1
            result["issues"].append({
                "id": card.get("id", "unknown"),
                "type": card_type,
                "guide": guide_name,
                "severity": "compound",
                "reasons": reasons,
                "suggestion": suggest_action(card, reasons),
            })

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def build_report(guide_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build YAML-serializable report from guide scan results."""
    total = sum(v["total"] for v in guide_results)
    atomic = sum(v["atomic"] for v in guide_results)
    borderline = sum(v["borderline"] for v in guide_results)
    compound = sum(v["compound"] for v in guide_results)

    atomic_pct = f"{100 * atomic / total:.1f}" if total > 0 else "0.0"

    by_guide = []
    for v in sorted(guide_results, key=lambda x: x["guide"]):
        entry: dict[str, Any] = {
            "guide": v["guide"],
            "total": v["total"],
            "atomic": v["atomic"],
            "borderline": v["borderline"],
            "compound": v["compound"],
        }
        worst = [i["id"] for i in v["issues"] if i["severity"] == "compound"][:5]
        if worst:
            entry["worst_cards"] = worst
        by_guide.append(entry)

    all_issues: list[dict] = []
    for v in guide_results:
        all_issues.extend(v["issues"])
    all_issues.sort(key=lambda x: (
        0 if x["severity"] == "compound" else 1, x["guide"], x["id"],
    ))

    return {
        "summary": {
            "total_cards": total,
            "atomic": atomic,
            "borderline": borderline,
            "compound": compound,
            "atomic_pct": f"{atomic_pct}%",
        },
        "by_guide": by_guide,
        "issues": all_issues[:200],
    }


def report_to_markdown(guide_results: list[dict[str, Any]]) -> str:
    """Generate Markdown summary of atomicity audit."""
    data = build_report(guide_results)
    s = data["summary"]
    lines: list[str] = []

    lines.append("# Card Atomicity Audit\n")
    lines.append(f"**Total auditable cards:** {s['total_cards']}  ")
    lines.append(f"**Atomic:** {s['atomic']} ({s['atomic_pct']})  ")
    lines.append(f"**Borderline:** {s['borderline']}  ")
    lines.append(f"**Compound:** {s['compound']}\n")

    lines.append("## By Guide\n")
    lines.append("| Guide | Total | Atomic | Borderline | Compound |")
    lines.append("|-------|-------|--------|------------|----------|")
    for v in data["by_guide"]:
        lines.append(
            f"| {v['guide']} | {v['total']} | {v['atomic']} | "
            f"{v['borderline']} | {v['compound']} |"
        )

    issues = data["issues"]
    compound_issues = [i for i in issues if i["severity"] == "compound"]
    if compound_issues:
        lines.append(f"\n## Compound Cards ({len(compound_issues)})\n")
        for issue in compound_issues[:30]:
            reasons_str = "; ".join(issue["reasons"])
            lines.append(f"- **{issue['id']}** ({issue['type']}) -- {reasons_str}")
            lines.append(f"  - {issue['suggestion']}")
        if len(compound_issues) > 30:
            lines.append(f"\n... and {len(compound_issues) - 30} more")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point.

    Returns
    -------
    int
        Exit code. 0 on success. 1 when `--check` is passed and any
        guide has compound cards (the Gold gate signal). The `FAIL`
        lines emitted per-guide are detected by `audit_gold_fleet.FAIL_RE`
        when this audit runs as part of the G2 11-audit suite.
    """
    parser = argparse.ArgumentParser(
        description="Audit card atomicity across course learning guides",
    )
    parser.add_argument("--guide", type=str, default=None, help="Audit a single guide")
    parser.add_argument("--report", action="store_true", help="Output Markdown report")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when any audited guide has compound cards (Gold gate signal)",
    )
    parser.add_argument("-o", "--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    if args.guide:
        guide_path = guide_dir_for_slug(args.guide)
        if guide_path is None or not guide_path.is_dir():
            print(f"Error: guide directory not found for slug: {args.guide}", file=sys.stderr)
            return 1
        scan_dirs = [args.guide]
    else:
        scan_dirs = find_guide_dirs()

    results: list[dict[str, Any]] = []
    for guide in scan_dirs:
        vr = scan_guide(guide)
        results.append(vr)
        if vr["total"] > 0:
            flag = ""
            if vr["compound"] > 0:
                flag = f" [!{vr['compound']} compound]"
            elif vr["borderline"] > 0:
                flag = f" [{vr['borderline']} borderline]"
            print(f"  {guide}: {vr['total']} cards, {vr['atomic']} atomic{flag}")
            # Emit FAIL line on compound>0 so audit_gold_fleet.FAIL_RE
            # catches it during G2 11-audit clean check (Gold gate).
            if vr["compound"] > 0:
                print(
                    f"FAIL {guide}: {vr['compound']} compound card(s) "
                    f"(Gold requires 0)"
                )

    total = sum(v["total"] for v in results)
    atomic = sum(v["atomic"] for v in results)
    compound = sum(v["compound"] for v in results)
    borderline = sum(v["borderline"] for v in results)
    pct = f"{100 * atomic / total:.1f}" if total > 0 else "0.0"
    print(f"\nTotal: {total} auditable cards, {atomic} atomic ({pct}%), "
          f"{borderline} borderline, {compound} compound")

    if args.report:
        print(report_to_markdown(results))
    elif not args.guide or args.output:
        # Only write the global YAML when scanning the full fleet, OR
        # when --output overrides the path. A `--guide <slug>` invocation
        # without --output would clobber docs/review/atomicity.yml with
        # single-guide data — that's now suppressed.
        report_data = build_report(results)
        output_path = Path(args.output) if args.output else (
            get_repo_root() / "reports" / "_scratch" / "atomicity.yml"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump(report_data, f, default_flow_style=False,
                      sort_keys=False, allow_unicode=True, width=120)
        print(f"Report saved to {output_path}")

    if args.check and compound > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
