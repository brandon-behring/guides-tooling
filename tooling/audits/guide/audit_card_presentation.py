#!/usr/bin/env python3
"""
Audit Anki card YAML files for presentation quality issues.

Adapted from interview_prep_series for course_learning guide layout.
Uses guide_scope.py for guide discovery (reads guides.yml).

Detects:
- Run-on numbered lists (1. ... 2. ... on same line)
- Run-on lettered lists ((a) ... (b) ... on same line)
- Run-on bullets (- Item - Item on same line)
- Inline section labels (Approach: ... Context: ... on same line)
- Walls of text (>500 chars without line breaks)
- Very long single lines (>200 chars)
- Comma-heavy lists (>4 commas suggesting list items)
- Semicolon-separated lists

Usage:
    python shared/audits/audit_card_presentation.py                  # All Tier 1
    python shared/audits/audit_card_presentation.py --guide dlai_advanced_rag
    python shared/audits/audit_card_presentation.py --summary-only
    python shared/audits/audit_card_presentation.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_guide_by_slug,
)


# ── Issue detection patterns ─────────────────────────────────────────────────
# Ported verbatim from interview_prep_series/scripts/audits/audit_card_presentation.py

PATTERNS = {
    "run_on_numbered": {
        "pattern": re.compile(r"(?<=\S)[^\n]*[ \t]([1-9]\.)\s+[A-Z]"),
        "description": 'Run-on numbered list (e.g., "text 1. Item 2. Item")',
        "priority": "P1",
        "auto_fixable": True,
    },
    "run_on_lettered": {
        "pattern": re.compile(r"(?<=\S)[^\n]*[ \t]\([a-z]\)[ \t]+"),
        "description": 'Run-on lettered list (e.g., "text (a) Item (b) Item")',
        "priority": "P1",
        "auto_fixable": True,
    },
    "run_on_bullets": {
        "pattern": re.compile(r"(?<=[^\s\-])[^\n]* - [A-Z]"),
        "description": 'Run-on bullet list (e.g., "text - Item - Item")',
        "priority": "P1",
        "auto_fixable": True,
    },
    "inline_sections": {
        "pattern": re.compile(
            r"(?:Approach|Context|Analysis|Diagnosis|Solution|Framework|"
            r"Justification|Recommendation|Summary|Example|Note|Warning|"
            r"Key Insight|Interview Tip|Rationale|Given|Step \d+|Phase \d+):[^\n]*"
            r"(?:Approach|Context|Analysis|Diagnosis|Solution|Framework|"
            r"Justification|Recommendation|Summary|Example|Note|Warning|"
            r"Key Insight|Interview Tip|Rationale|Given|Step \d+|Phase \d+):",
            re.IGNORECASE,
        ),
        "description": "Inline section labels (multiple headers on same line)",
        "priority": "P1",
        "auto_fixable": True,
    },
    "wall_of_text": {
        "pattern": None,  # Custom logic
        "description": "Wall of text (>500 chars without paragraph break)",
        "priority": "P2",
        "auto_fixable": False,
    },
    "very_long_line": {
        "pattern": None,  # Custom logic
        "description": "Very long single line (>200 chars)",
        "priority": "P2",
        "auto_fixable": False,
    },
    "comma_list": {
        "pattern": re.compile(r"(?:[^,\n]{1,30},){5,}"),
        "description": "Comma-heavy list (may need bullet conversion)",
        "priority": "P2",
        "auto_fixable": False,
    },
    "semicolon_list": {
        "pattern": re.compile(r"(?:[^;]+;){2,}"),
        "description": "Semicolon-separated list",
        "priority": "P3",
        "auto_fixable": False,
    },
}

# Cards containing these are skipped (code/math/table blocks)
EXCLUSIONS = [
    re.compile(r"\\begin\{minted\}"),
    re.compile(r"\\begin\{align"),
    re.compile(r"\\begin\{tabular\}"),
    re.compile(r"\\begin\{equation\}"),
    re.compile(r"\\begin\{lstlisting\}"),
    re.compile(r"\\begin\{verbatim\}"),
    re.compile(r"^```", re.MULTILINE),
    re.compile(
        r"(?:SELECT|INSERT|UPDATE|DELETE)\s+.*\s+(?:FROM|INTO|SET|WHERE)",
        re.IGNORECASE | re.DOTALL,
    ),
]


# ── Detection helpers ────────────────────────────────────────────────────────


def should_exclude_card(text: str) -> bool:
    """Check if card should be excluded from audit (code/math/table blocks)."""
    for pattern in EXCLUSIONS:
        if pattern.search(text):
            return True
    return False


def check_wall_of_text(text: str, threshold: int = 500) -> bool:
    """Check if text is a wall of text (long without paragraph breaks)."""
    paragraphs = re.split(r"\n\s*\n", text)
    return any(len(para.strip()) > threshold for para in paragraphs)


def check_very_long_line(text: str, threshold: int = 200) -> bool:
    """Check if any single line exceeds threshold."""
    return any(len(line.strip()) > threshold for line in text.split("\n"))


def _is_math_bullet_false_positive(match: re.Match, text: str) -> bool:
    """Check if a run_on_bullets match is actually math subtraction."""
    match_text = match.group()
    dash_pos = match_text.find(" - ")
    if dash_pos < 0:
        return False
    abs_dash = match.start() + dash_pos
    if abs_dash > 0:
        char_before = text[abs_dash - 1]
        if char_before in "])|0123456789}":
            return True
    return False


def _is_inline_sections_false_positive(match: re.Match) -> bool:
    """Check if an inline_sections match is natural language, not a real header collision."""
    match_text = match.group()
    keywords = [
        "approach", "context", "analysis", "diagnosis", "solution", "framework",
        "justification", "recommendation", "summary", "example", "note", "warning",
        "key insight", "interview tip", "rationale", "given",
    ]
    lower_text = match_text.lower()
    for kw in keywords:
        kw_colon = kw + ":"
        idx = lower_text.rfind(kw_colon)
        if idx > 0:
            char_before = match_text[idx - 1]
            if char_before.islower() or char_before == " ":
                preceding = match_text[:idx].rstrip()
                if preceding and preceding[-1] not in ("*", "\n", "|"):
                    return True
    return False


# ── Core audit logic ─────────────────────────────────────────────────────────


def detect_issues(text: str) -> List[Dict[str, Any]]:
    """Detect all presentation issues in text."""
    if not text or not isinstance(text, str):
        return []

    issues = []
    for issue_type, config in PATTERNS.items():
        if config["pattern"] is not None:
            if issue_type in ("run_on_bullets", "inline_sections"):
                has_real_match = False
                for match in config["pattern"].finditer(text):
                    if issue_type == "run_on_bullets" and _is_math_bullet_false_positive(match, text):
                        continue
                    if issue_type == "inline_sections" and _is_inline_sections_false_positive(match):
                        continue
                    has_real_match = True
                    break
                if not has_real_match:
                    continue
            elif not config["pattern"].search(text):
                continue
            issues.append({
                "type": issue_type,
                "description": config["description"],
                "priority": config["priority"],
                "auto_fixable": config["auto_fixable"],
            })
        elif issue_type == "wall_of_text":
            if check_wall_of_text(text):
                issues.append({
                    "type": issue_type,
                    "description": config["description"],
                    "priority": config["priority"],
                    "auto_fixable": config["auto_fixable"],
                })
        elif issue_type == "very_long_line":
            if check_very_long_line(text):
                issues.append({
                    "type": issue_type,
                    "description": config["description"],
                    "priority": config["priority"],
                    "auto_fixable": config["auto_fixable"],
                })

    return issues


def audit_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Audit a single card for presentation issues."""
    card_id = card.get("id", "unknown")
    card_type = card.get("type", "unknown")
    front = card.get("front", "")
    back = card.get("back", "")

    if should_exclude_card(front) or should_exclude_card(back):
        return {"id": card_id, "type": card_type, "excluded": True, "issues": []}

    all_issues = []
    for issue in detect_issues(front):
        issue["side"] = "front"
        all_issues.append(issue)
    for issue in detect_issues(back):
        issue["side"] = "back"
        all_issues.append(issue)

    return {"id": card_id, "type": card_type, "excluded": False, "issues": all_issues}


def audit_file(file_path: Path) -> Dict[str, Any]:
    """Audit a single YAML card file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return {
            "file": str(file_path),
            "error": str(e),
            "cards": [],
            "summary": {"total": 0, "with_issues": 0, "excluded": 0},
        }

    if not data or "cards" not in data:
        return {
            "file": str(file_path),
            "error": None,
            "cards": [],
            "summary": {"total": 0, "with_issues": 0, "excluded": 0},
        }

    results = []
    total = with_issues = excluded = 0

    for card in data["cards"]:
        total += 1
        result = audit_card(card)
        if result["excluded"]:
            excluded += 1
        elif result["issues"]:
            with_issues += 1
            results.append(result)

    return {
        "file": str(file_path),
        "error": None,
        "cards": results,
        "summary": {
            "total": total,
            "with_issues": with_issues,
            "excluded": excluded,
            "issue_rate": round(with_issues / total * 100, 1) if total > 0 else 0,
        },
    }


# ── Guide-level discovery ────────────────────────────────────────────────────


def find_card_files_for_guide(guide: GuideInfo, repo_root: Path) -> List[Path]:
    """Find all card YAML files for a guide, excluding all_cards.yml."""
    cards_dir = guide.resolve_cards_dir(repo_root)
    if not cards_dir.exists():
        return []
    files = sorted(cards_dir.glob("*_cards.yml"))
    return [f for f in files if f.name != "all_cards.yml"]


def aggregate_results(file_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate results across all files."""
    total_cards = total_with_issues = total_excluded = 0
    issue_type_counts: Dict[str, int] = defaultdict(int)
    priority_counts: Dict[str, int] = defaultdict(int)
    guide_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "with_issues": 0})

    for result in file_results:
        summary = result["summary"]
        total_cards += summary["total"]
        total_with_issues += summary["with_issues"]
        total_excluded += summary["excluded"]

        # Extract guide slug from path (guide_slug/notes/notebook/cards/file.yml)
        file_path = Path(result["file"])
        parts = file_path.parts
        # Find the guide slug — the directory containing guide/ (new) or notes/ (old)
        guide_slug = "unknown"
        for i, part in enumerate(parts):
            if part in ("guide", "notes") and i > 0:
                guide_slug = parts[i - 1]
                break
        guide_stats[guide_slug]["total"] += summary["total"]
        guide_stats[guide_slug]["with_issues"] += summary["with_issues"]

        for card in result["cards"]:
            for issue in card["issues"]:
                issue_type_counts[issue["type"]] += 1
                priority_counts[issue["priority"]] += 1

    for slug, stats in guide_stats.items():
        stats["issue_rate"] = round(stats["with_issues"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0

    return {
        "total_cards": total_cards,
        "cards_with_issues": total_with_issues,
        "cards_excluded": total_excluded,
        "overall_issue_rate": round(total_with_issues / total_cards * 100, 1) if total_cards > 0 else 0,
        "issue_types": dict(issue_type_counts),
        "priorities": dict(priority_counts),
        "guide_stats": dict(guide_stats),
    }


def print_summary(aggregate: Dict[str, Any]) -> None:
    """Print human-readable summary."""
    print("\n" + "=" * 60)
    print("ANKI CARD PRESENTATION AUDIT — course_learning")
    print("=" * 60)

    print(f"\nTotal cards scanned: {aggregate['total_cards']}")
    print(f"Cards with issues:   {aggregate['cards_with_issues']} ({aggregate['overall_issue_rate']}%)")
    print(f"Cards excluded:      {aggregate['cards_excluded']} (code/math/table blocks)")

    print("\n" + "-" * 40)
    print("ISSUE TYPES:")
    print("-" * 40)
    for issue_type, count in sorted(aggregate["issue_types"].items(), key=lambda x: -x[1]):
        config = PATTERNS.get(issue_type, {})
        fixable = "+" if config.get("auto_fixable") else "o"
        print(f"  [{fixable}] {issue_type}: {count}")

    print("\n" + "-" * 40)
    print("BY PRIORITY:")
    print("-" * 40)
    for priority in ["P1", "P2", "P3"]:
        count = aggregate["priorities"].get(priority, 0)
        print(f"  {priority}: {count}")

    print("\n" + "-" * 40)
    print("BY GUIDE (sorted by issue rate):")
    print("-" * 40)
    sorted_guides = sorted(
        aggregate["guide_stats"].items(),
        key=lambda x: -x[1]["issue_rate"],
    )
    for slug, stats in sorted_guides:
        print(f"  {slug}: {stats['with_issues']}/{stats['total']} ({stats['issue_rate']}%)")

    print("\n" + "=" * 60)
    target = 15.0
    if aggregate["overall_issue_rate"] <= target:
        print(f"PASS: Issue rate {aggregate['overall_issue_rate']}% <= target {target}%")
    else:
        reduction = aggregate["overall_issue_rate"] - target
        print(f"FAIL: Issue rate {aggregate['overall_issue_rate']}% > target {target}%")
        print(f"      Need to reduce by {reduction:.1f} percentage points")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Anki card YAML files for presentation quality issues."
    )
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--summary-only", "-s", action="store_true", help="Summary stats only")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    repo_root = get_repo_root()

    # Determine which guides to audit
    if args.guide:
        guide = get_guide_by_slug(args.guide)
        if guide is None:
            print(f"Error: guide '{args.guide}' not found in guides.yml", file=sys.stderr)
            sys.exit(1)
        guides = [guide]
    else:
        guides = get_tier1_guides()

    # Find and audit all card files
    file_results: List[Dict[str, Any]] = []
    for guide in guides:
        files = find_card_files_for_guide(guide, repo_root)
        if not files:
            # Fallback to all_cards.yml
            all_cards = guide.resolve_cards_dir(repo_root) / "all_cards.yml"
            if all_cards.exists():
                files = [all_cards]
        for file_path in files:
            result = audit_file(file_path)
            file_results.append(result)

    if not file_results:
        print("No card files found.", file=sys.stderr)
        sys.exit(1)

    aggregate = aggregate_results(file_results)

    if args.json:
        output = {
            "aggregate": aggregate,
            "files": file_results if not args.summary_only else [],
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(aggregate)
        if not args.summary_only:
            print("DETAILED ISSUES (top 20 cards by issue count):")
            print("-" * 60)
            all_cards = []
            for result in file_results:
                for card in result["cards"]:
                    card["file"] = result["file"]
                    all_cards.append(card)
            all_cards.sort(key=lambda x: -len(x["issues"]))
            for card in all_cards[:20]:
                print(f"\n{card['id']} ({card['type']})")
                print(f"  File: {card['file']}")
                for issue in card["issues"]:
                    print(f"  - [{issue['priority']}] {issue['type']} ({issue['side']})")


if __name__ == "__main__":
    main()
