#!/usr/bin/env python3
"""
Audit retrieval coverage: % of LOS tested by at least one problem or checkpoint.

Research basis: Roediger & Karpicke (2006) — the metric that predicts actual
learning transfer is whether each learning objective has at least one retrieval
opportunity (problem, checkpoint question, or drill).

A LOS with no retrieval opportunity means the learner encounters the concept
only through reading — which produces ~50% less long-term retention vs
retrieval practice.

Usage:
    python shared/audits/audit_retrieval_coverage.py                  # All Tier 1
    python shared/audits/audit_retrieval_coverage.py --guide dlai_advanced_rag
    python shared/audits/audit_retrieval_coverage.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_guide_by_slug,
)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class GuideRetrievalMetrics:
    """Retrieval coverage metrics for a guide."""

    slug: str
    los_prefix: Optional[str]
    los_defined: list[str] = field(default_factory=list)  # LOS IDs defined in chapters
    los_tested: set = field(default_factory=set)           # LOS IDs with retrieval opportunity
    problem_count: int = 0
    checkpoint_count: int = 0
    coverage_pct: float = 0.0
    untested_los: list[str] = field(default_factory=list)
    status: str = ""  # GREEN/YELLOW/RED


# ── Extraction ───────────────────────────────────────────────────────────────

# LOS definition: \los{PREFIX-N.M}{level}{statement}
LOS_DEF_RE = re.compile(r"\\los\{([^}]+)\}")

# Problem with LOS ref: \begin{problem}[Title][LOS-ID] or \begin{problem}[LOS-ID]
PROBLEM_LOS_RE = re.compile(
    r"\\begin\{problem\}(?:\[[^\]]*\])?\[([^\]]+)\]"
)

# Checkpoint questions (count only — LOS linkage is implicit via chapter)
# Supports both \begin{tcolorbox}[checkpointbox,...] and \begin{checkpointbox}
CHECKPOINT_RE = re.compile(
    r"(?:"
    r"\\begin\{tcolorbox\}\[checkpointbox.*?\](.*?)\\end\{tcolorbox\}"
    r"|"
    r"\\begin\{checkpointbox\}(.*?)\\end\{checkpointbox\}"
    r")",
    re.DOTALL,
)
CHECKPOINT_ITEM_RE = re.compile(r"\\item\s+")

# Checkpoint items with explicit LOS linkage:
#   \item[LOS-ID] Question text
CHECKPOINT_LOS_RE = re.compile(r"\\item\[([A-Z][A-Z0-9]*-[\d.]+)\]")

# Also detect LOS refs in \hfill\textit{(LOS-ID, LOS-ID2)} format
CHECKPOINT_HFILL_LOS_RE = re.compile(r"\\hfill\\textit\{[^}]*?([A-Z][A-Z0-9]*-[\d.]+)")

# Card YAML LOS references
CARD_LOS_RE = re.compile(r"los_id:\s*['\"]?([A-Z][A-Z0-9]*-[\d.]+)")


def extract_los_from_tex(content: str) -> list[str]:
    """Extract all LOS IDs defined in a chapter."""
    return LOS_DEF_RE.findall(content)


# Problem/vignette LOS references in LaTeX
PROBLEM_LOS_RE = re.compile(
    r"\\begin\{(?:problem|vignette)\}(?:\[[^\]]*\])*?\[([A-Z][A-Z0-9]*-[\d.]+(?:\s*,\s*[A-Z][A-Z0-9]*-[\d.]+)*)\]"
)


def extract_problem_los_from_tex(content: str) -> list[str]:
    """Extract LOS IDs from problem and vignette environments in LaTeX.

    Handles single and multi-LOS: [Title][LOS-ID] and [Title][LOS-A, LOS-B].
    """
    los_ids: list[str] = []
    for match in PROBLEM_LOS_RE.finditer(content):
        for lid in re.split(r"[,;]\s*", match.group(1)):
            lid = lid.strip()
            if lid:
                los_ids.append(lid)
    return los_ids


def count_checkpoint_items(content: str) -> int:
    """Count checkpoint question items in a chapter."""
    total = 0
    for match in CHECKPOINT_RE.finditer(content):
        body = match.group(1) or match.group(2) or ""
        total += len(CHECKPOINT_ITEM_RE.findall(body))
    return total


def extract_checkpoint_los_from_tex(content: str) -> list[str]:
    """Extract LOS IDs explicitly linked in checkpoint items.

    Supports two formats:
        \\item[LOS-ID] Question text
        \\item Question text \\hfill\\textit{(LOS-ID, LOS-ID2)}
    """
    los_ids: list[str] = []
    for match in CHECKPOINT_RE.finditer(content):
        body = match.group(1) or match.group(2) or ""
        # Format 1: \item[LOS-ID]
        los_ids.extend(CHECKPOINT_LOS_RE.findall(body))
        # Format 2: \hfill\textit{(LOS-ID...)}
        for hfill_match in re.finditer(
            r"\\hfill\\textit\{[^}]*\}", body
        ):
            hfill_text = hfill_match.group(0)
            los_ids.extend(re.findall(r"[A-Z][A-Z0-9]*-[\d.]+", hfill_text))
    return los_ids


def extract_tested_los_from_cards(cards_dir: Path) -> set[str]:
    """Extract LOS IDs that have cards (problems, drills, etc.)."""
    tested = set()
    if not cards_dir.exists():
        return tested

    for cards_file in cards_dir.glob("*_cards.yml"):
        try:
            with open(cards_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            cards = data.get("cards", []) if isinstance(data, dict) else []
            for card in cards:
                los_id = card.get("los_id")
                card_type = card.get("type", "")
                # Only count retrieval-oriented card types
                if los_id and card_type in ("problem", "drill", "vignette", "checkpoint"):
                    # Handle multi-LOS cards: "GRPO-3.5, GRPO-2.5"
                    for lid in re.split(r"[,;]\s*", los_id.strip()):
                        lid = lid.strip()
                        if lid:
                            tested.add(lid)
        except Exception:
            continue

    return tested


# ── Guide-level audit ────────────────────────────────────────────────────────


def audit_guide_retrieval(guide: GuideInfo, repo_root: Path) -> Optional[GuideRetrievalMetrics]:
    """Audit retrieval coverage for a guide."""
    chapters_dir = guide.resolve_chapters_dir(repo_root)
    cards_dir = guide.resolve_cards_dir(repo_root)

    if not chapters_dir.exists():
        return None

    metrics = GuideRetrievalMetrics(slug=guide.slug, los_prefix=guide.los_prefix)

    # Scan all chapters
    all_los_defined: list[str] = []
    all_los_tested: set[str] = set()

    for tex_file in sorted(chapters_dir.glob("*.tex")):
        if tex_file.stem.startswith("_"):
            continue
        try:
            content = tex_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # LOS defined
        los_ids = extract_los_from_tex(content)
        all_los_defined.extend(los_ids)

        # Problems with LOS refs
        problem_los = extract_problem_los_from_tex(content)
        all_los_tested.update(problem_los)

        # Checkpoints: count items + extract explicit LOS linkage
        metrics.checkpoint_count += count_checkpoint_items(content)
        checkpoint_los = extract_checkpoint_los_from_tex(content)
        all_los_tested.update(checkpoint_los)

        # Count problems
        metrics.problem_count += len(re.findall(r"\\begin\{problem\}", content))

    # Also check card YAML for LOS-linked retrieval cards
    card_los = extract_tested_los_from_cards(cards_dir)
    all_los_tested.update(card_los)

    # Deduplicate and compute
    # Use set for defined LOS (some may be defined with same ID in different chapters)
    unique_los = list(dict.fromkeys(all_los_defined))  # preserve order, dedupe
    metrics.los_defined = unique_los
    metrics.los_tested = all_los_tested

    if unique_los:
        tested_count = sum(1 for los in unique_los if los in all_los_tested)
        metrics.coverage_pct = round(tested_count / len(unique_los) * 100, 1)
        metrics.untested_los = [los for los in unique_los if los not in all_los_tested]
    else:
        metrics.coverage_pct = 0.0

    # Status
    if metrics.coverage_pct >= 80:
        metrics.status = "GREEN"
    elif metrics.coverage_pct >= 50:
        metrics.status = "YELLOW"
    else:
        metrics.status = "RED"

    return metrics


# ── Reporting ────────────────────────────────────────────────────────────────


def print_report(all_metrics: list[GuideRetrievalMetrics]) -> None:
    """Print human-readable retrieval coverage report."""
    total_los = sum(len(m.los_defined) for m in all_metrics)
    total_tested = sum(len([l for l in m.los_defined if l in m.los_tested]) for m in all_metrics)
    total_untested = sum(len(m.untested_los) for m in all_metrics)
    overall_pct = round(total_tested / total_los * 100, 1) if total_los else 0

    print("\n" + "=" * 60)
    print("RETRIEVAL COVERAGE AUDIT — course_learning")
    print("=" * 60)
    print(f"\nGuides:          {len(all_metrics)}")
    print(f"LOS defined:     {total_los}")
    print(f"LOS tested:      {total_tested} ({overall_pct}%)")
    print(f"LOS untested:    {total_untested}")

    print("\n" + "-" * 60)
    print(f"{'Guide':<50} {'LOS':>4} {'Tested':>6} {'Cov%':>5} {'Status':>7}")
    print("-" * 60)

    for m in sorted(all_metrics, key=lambda x: x.coverage_pct):
        tested = len([l for l in m.los_defined if l in m.los_tested])
        status_icon = {"GREEN": "OK", "YELLOW": "WARN", "RED": "FAIL"}.get(m.status, "?")
        print(f"  {m.slug:<48} {len(m.los_defined):>4} {tested:>6} {m.coverage_pct:>5.1f} {status_icon:>7}")

    # Top untested LOS
    all_untested = []
    for m in all_metrics:
        for los in m.untested_los:
            all_untested.append((m.slug, los))

    if all_untested and len(all_untested) <= 50:
        print(f"\n{'=' * 60}")
        print(f"UNTESTED LOS ({len(all_untested)} total):")
        print("-" * 60)
        for slug, los in all_untested[:30]:
            print(f"  {slug}: {los}")
        if len(all_untested) > 30:
            print(f"  ... and {len(all_untested) - 30} more")

    print(f"\n{'=' * 60}")
    target = 80.0
    if overall_pct >= target:
        print(f"PASS: Overall retrieval coverage {overall_pct}% >= target {target}%")
    else:
        gap = target - overall_pct
        print(f"FAIL: Overall retrieval coverage {overall_pct}% < target {target}%")
        print(f"      Need {gap:.1f} percentage points improvement")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit retrieval coverage: % of LOS with at least one retrieval opportunity"
    )
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if <80%% coverage")
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

    all_metrics: list[GuideRetrievalMetrics] = []
    for guide in guides:
        result = audit_guide_retrieval(guide, repo_root)
        if result and result.los_defined:
            all_metrics.append(result)

    if not all_metrics:
        print("No guides with LOS found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        total_los = sum(len(m.los_defined) for m in all_metrics)
        total_tested = sum(len([l for l in m.los_defined if l in m.los_tested]) for m in all_metrics)
        output = {
            "summary": {
                "guides": len(all_metrics),
                "total_los": total_los,
                "total_tested": total_tested,
                "overall_coverage_pct": round(total_tested / total_los * 100, 1) if total_los else 0,
            },
            "guides": [
                {
                    "slug": m.slug,
                    "los_defined": len(m.los_defined),
                    "los_tested": len([l for l in m.los_defined if l in m.los_tested]),
                    "coverage_pct": m.coverage_pct,
                    "status": m.status,
                    "problems": m.problem_count,
                    "checkpoints": m.checkpoint_count,
                    "untested_los": m.untested_los,
                }
                for m in all_metrics
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(all_metrics)

    if args.strict:
        total_los = sum(len(m.los_defined) for m in all_metrics)
        total_tested = sum(len([l for l in m.los_defined if l in m.los_tested]) for m in all_metrics)
        overall = (total_tested / total_los * 100) if total_los else 0
        if overall < 80:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
