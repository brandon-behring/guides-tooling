#!/usr/bin/env python3
"""
Audit card quality across course_learning guides.

Adapted from interview_prep_series for course_learning guide layout.
Uses guide_scope.py for guide discovery (reads guides.yml).

Computes quality metrics per card:
- Back field length (thin: <50 chars, moderate: 50-200, rich: 200+)
- LaTeX environment detection (broken: raw \\begin{} in backs)
- ID collision detection (duplicate card IDs)
- Type distribution per guide
- LOS traceability (% of cards with los_id)

Usage:
    python shared/audits/audit_card_quality.py                  # All Tier 1
    python shared/audits/audit_card_quality.py --guide dlai_advanced_rag
    python shared/audits/audit_card_quality.py --json
    python shared/audits/audit_card_quality.py --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_guide_by_slug,
    guide_dir_for_slug,
)

# ── Quality thresholds ───────────────────────────────────────────────────────

THIN_THRESHOLD = 50   # chars — cards below this are useless for review
MODERATE_THRESHOLD = 200  # chars — moderate richness
THIN_CARD_MAX_PERCENT = 5  # strict mode gate
TERM_RATIO_MAX = 0.60  # term cards should be <60% of total (Wozniak variety)

# ── LaTeX pattern detection ──────────────────────────────────────────────────

# Truly broken (not handled by Anki converter)
BROKEN_LATEX_PATTERNS = [
    r"\\begin\{figure\}",
    r"\\begin\{tikzpicture\}",
    r"\\includegraphics",
    r"\\cite\{",
    r"\\ref\{",
]

# Informational: will be converted (not broken)
LATEX_USAGE_PATTERNS = [
    r"\\begin\{equation\}",
    r"\\begin\{align\}",
    r"\\begin\{itemize\}",
    r"\\begin\{enumerate\}",
    r"\\begin\{tabular\}",
    r"\\begin\{minted\}",
    r"\\begin\{verbatim\}",
]


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class CardMetrics:
    """Quality metrics for a single card."""

    id: str
    guide: str
    card_type: str
    source: str
    back_length: int
    front_length: int = 0
    is_thin: bool = False
    has_broken_latex: bool = False
    broken_latex_patterns: list[str] = field(default_factory=list)
    has_los: bool = False
    los_id: str = ""


@dataclass
class GuideCardMetrics:
    """Aggregated card metrics for a guide."""

    slug: str
    total_cards: int = 0
    thin_count: int = 0
    moderate_count: int = 0
    rich_count: int = 0
    broken_latex_count: int = 0
    los_count: int = 0
    no_los_count: int = 0
    type_distribution: dict = field(default_factory=dict)
    avg_front_length: float = 0.0
    avg_back_length: float = 0.0
    term_ratio: float = 0.0
    thin_cards: list[CardMetrics] = field(default_factory=list)
    broken_cards: list[CardMetrics] = field(default_factory=list)


# ── Analysis functions ───────────────────────────────────────────────────────


def detect_broken_latex(text: str) -> list[str]:
    """Detect truly broken LaTeX patterns in text."""
    found = []
    for pattern in BROKEN_LATEX_PATTERNS:
        if re.search(pattern, text):
            found.append(pattern)
    return found


def analyze_card(card: dict, guide_slug: str) -> CardMetrics:
    """Analyze a single card for quality metrics."""
    card_id = card.get("id", "MISSING_ID")
    card_type = card.get("type", "unknown")
    source = card.get("source", "unknown")
    front = card.get("front", "")
    back = card.get("back", "")
    los_id = card.get("los_id", None)

    back_length = len(back)
    front_length = len(front)
    # LOS metadata cards excluded from thin detection
    is_thin = back_length < THIN_THRESHOLD and card_type != "los"
    broken = detect_broken_latex(back)
    has_los = los_id is not None and str(los_id).strip() != ""

    return CardMetrics(
        id=card_id,
        guide=guide_slug,
        card_type=card_type,
        source=source,
        back_length=back_length,
        front_length=front_length,
        is_thin=is_thin,
        has_broken_latex=len(broken) > 0,
        broken_latex_patterns=broken,
        has_los=has_los,
        los_id=str(los_id).strip() if los_id else "",
    )


def audit_guide_cards(guide: GuideInfo, repo_root: Path) -> Optional[GuideCardMetrics]:
    """Audit all cards in a guide."""
    cards_dir = guide.resolve_cards_dir(repo_root)
    if not cards_dir.exists():
        return None

    # Find card files (prefer per-chapter, fallback to all_cards.yml)
    chapter_files = [f for f in sorted(cards_dir.glob("*_cards.yml")) if f.name != "all_cards.yml"]
    if not chapter_files:
        all_cards = cards_dir / "all_cards.yml"
        if all_cards.exists():
            chapter_files = [all_cards]
    if not chapter_files:
        return None

    metrics = GuideCardMetrics(slug=guide.slug)
    type_counts: dict[str, int] = defaultdict(int)
    total_front = 0
    total_back = 0

    for cards_file in chapter_files:
        try:
            with open(cards_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        cards = data.get("cards", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        for card in cards:
            card_metrics = analyze_card(card, guide.slug)
            metrics.total_cards += 1
            total_front += card_metrics.front_length
            total_back += card_metrics.back_length

            if card_metrics.is_thin:
                metrics.thin_count += 1
                if len(metrics.thin_cards) < 30:
                    metrics.thin_cards.append(card_metrics)
            elif card_metrics.back_length < MODERATE_THRESHOLD:
                metrics.moderate_count += 1
            else:
                metrics.rich_count += 1

            if card_metrics.has_broken_latex:
                metrics.broken_latex_count += 1
                if len(metrics.broken_cards) < 30:
                    metrics.broken_cards.append(card_metrics)

            if card_metrics.has_los:
                metrics.los_count += 1
            else:
                metrics.no_los_count += 1

            type_counts[card_metrics.card_type] += 1

    if metrics.total_cards == 0:
        return None

    metrics.type_distribution = dict(type_counts)
    metrics.avg_front_length = round(total_front / metrics.total_cards, 1)
    metrics.avg_back_length = round(total_back / metrics.total_cards, 1)
    term_count = type_counts.get("term", 0)
    metrics.term_ratio = round(term_count / metrics.total_cards, 3)

    return metrics


def find_id_collisions(all_metrics: list[GuideCardMetrics], repo_root: Path) -> list[tuple[str, list[str]]]:
    """Find duplicate card IDs across all guides."""
    id_to_guides: dict[str, list[str]] = defaultdict(list)

    for gm in all_metrics:
        gd = guide_dir_for_slug(gm.slug)
        if gd is None:
            continue
        cards_dir = gd / "guide" / "cards"
        if not cards_dir.exists():
            continue
        for cards_file in sorted(cards_dir.glob("*_cards.yml")):
            if cards_file.name == "all_cards.yml":
                continue
            try:
                with open(cards_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                cards = data.get("cards", []) if isinstance(data, dict) else []
                for card in cards:
                    cid = card.get("id", "")
                    if cid:
                        id_to_guides[cid].append(gm.slug)
            except Exception:
                continue

    return [(cid, guides) for cid, guides in id_to_guides.items() if len(guides) > 1]


# ── Reporting ────────────────────────────────────────────────────────────────


def print_summary(guide_metrics: list[GuideCardMetrics], collisions: list) -> None:
    """Print human-readable summary."""
    total_cards = sum(g.total_cards for g in guide_metrics)
    total_thin = sum(g.thin_count for g in guide_metrics)
    total_broken = sum(g.broken_latex_count for g in guide_metrics)
    total_with_los = sum(g.los_count for g in guide_metrics)

    thin_pct = round(total_thin / total_cards * 100, 1) if total_cards else 0
    los_pct = round(total_with_los / total_cards * 100, 1) if total_cards else 0

    print("\n" + "=" * 60)
    print("CARD QUALITY AUDIT — course_learning")
    print("=" * 60)
    print(f"\nGuides audited:   {len(guide_metrics)}")
    print(f"Total cards:      {total_cards:,}")
    print(f"LOS coverage:     {total_with_los} ({los_pct}%)")
    print(f"Thin (<{THIN_THRESHOLD} chars):  {total_thin} ({thin_pct}%)")
    print(f"Broken LaTeX:     {total_broken}")
    print(f"ID collisions:    {len(collisions)}")

    # Type distribution
    type_totals: dict[str, int] = defaultdict(int)
    for g in guide_metrics:
        for t, c in g.type_distribution.items():
            type_totals[t] += c

    print("\n" + "-" * 40)
    print("CARD TYPE DISTRIBUTION:")
    print("-" * 40)
    for ctype, count in sorted(type_totals.items(), key=lambda x: -x[1]):
        pct = round(count / total_cards * 100, 1) if total_cards else 0
        print(f"  {ctype}: {count} ({pct}%)")

    # Per-guide summary
    print("\n" + "-" * 40)
    print("PER-GUIDE SUMMARY:")
    print("-" * 40)
    for g in sorted(guide_metrics, key=lambda x: -x.total_cards):
        los_pct_g = round(g.los_count / g.total_cards * 100) if g.total_cards else 0
        thin_flag = " [THIN]" if g.thin_count > g.total_cards * 0.1 else ""
        term_flag = " [HIGH-TERM]" if g.term_ratio > TERM_RATIO_MAX else ""
        print(
            f"  {g.slug}: {g.total_cards} cards, "
            f"LOS {los_pct_g}%, "
            f"avg-back {g.avg_back_length:.0f}ch, "
            f"term-ratio {g.term_ratio:.0%}"
            f"{thin_flag}{term_flag}"
        )

    # Card quality score (composite)
    front_ok = all(10 <= g.avg_front_length <= 250 for g in guide_metrics)
    back_ok = all(50 <= g.avg_back_length <= 1000 for g in guide_metrics)
    los_ok = los_pct >= 80
    thin_ok = thin_pct <= 5
    term_ok = all(g.term_ratio <= TERM_RATIO_MAX for g in guide_metrics)

    score = sum([front_ok, back_ok, los_ok, thin_ok, term_ok])
    print(f"\n{'=' * 60}")
    print(f"CARD QUALITY SCORE: {score}/5")
    print(f"  Front length:  {'PASS' if front_ok else 'FAIL'} (target: 10-250 chars avg)")
    print(f"  Back length:   {'PASS' if back_ok else 'FAIL'} (target: 50-1000 chars avg)")
    print(f"  LOS coverage:  {'PASS' if los_ok else 'FAIL'} (target: >=80%)")
    print(f"  Thin cards:    {'PASS' if thin_ok else 'FAIL'} (target: <=5%)")
    print(f"  Term ratio:    {'PASS' if term_ok else 'FAIL'} (target: <={TERM_RATIO_MAX:.0%})")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit card quality across course_learning guides")
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if quality issues found")
    args = parser.parse_args()

    repo_root = get_repo_root()

    if args.guide:
        guide = get_guide_by_slug(args.guide)
        if guide is None:
            print(f"Error: guide '{args.guide}' not found in guides.yml", file=sys.stderr)
            sys.exit(1)
        guides = [guide]
    else:
        guides = get_tier1_guides()

    # Audit each guide
    all_metrics: list[GuideCardMetrics] = []
    for guide in guides:
        result = audit_guide_cards(guide, repo_root)
        if result:
            all_metrics.append(result)

    if not all_metrics:
        print("No card files found.", file=sys.stderr)
        sys.exit(1)

    # Find collisions
    collisions = find_id_collisions(all_metrics, repo_root)

    if args.json:
        total_cards = sum(g.total_cards for g in all_metrics)
        total_thin = sum(g.thin_count for g in all_metrics)
        total_with_los = sum(g.los_count for g in all_metrics)
        output = {
            "generated": datetime.now().isoformat(),
            "summary": {
                "guides": len(all_metrics),
                "total_cards": total_cards,
                "los_count": total_with_los,
                "los_percent": round(total_with_los / total_cards * 100, 1) if total_cards else 0,
                "thin_count": total_thin,
                "thin_percent": round(total_thin / total_cards * 100, 1) if total_cards else 0,
                "broken_latex": sum(g.broken_latex_count for g in all_metrics),
                "collisions": len(collisions),
            },
            "guides": [
                {
                    "slug": g.slug,
                    "total_cards": g.total_cards,
                    "thin_count": g.thin_count,
                    "broken_latex": g.broken_latex_count,
                    "los_count": g.los_count,
                    "avg_front_length": g.avg_front_length,
                    "avg_back_length": g.avg_back_length,
                    "term_ratio": g.term_ratio,
                    "type_distribution": g.type_distribution,
                }
                for g in all_metrics
            ],
            "collisions": [{"id": cid, "guides": gs} for cid, gs in collisions],
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(all_metrics, collisions)

    # Strict mode
    if args.strict:
        total_cards = sum(g.total_cards for g in all_metrics)
        total_thin = sum(g.thin_count for g in all_metrics)
        thin_pct = (total_thin / total_cards * 100) if total_cards else 0
        total_broken = sum(g.broken_latex_count for g in all_metrics)

        if thin_pct > THIN_CARD_MAX_PERCENT or total_broken > 0 or collisions:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
