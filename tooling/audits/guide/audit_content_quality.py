#!/usr/bin/env python3
"""
Hub-portable content quality audit for LaTeX guides.

Reads guides.yml for guide discovery, counts LaTeX environments per chapter,
and produces traffic-light output per guide. Designed for the course_learning
repo but works with any repo that has a guides.yml registry.

Uses the same quality thresholds as interview_prep_series but is an independent
implementation — interview_prep_series scripts remain untouched.

Usage:
    python audit_content_quality.py                          # All Tier 1 guides
    python audit_content_quality.py --all                    # All guides
    python audit_content_quality.py --guide dlai_advanced_rag  # Single guide
    python audit_content_quality.py --json                   # JSON output
    python audit_content_quality.py --strict                 # Exit 1 if RED found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from tooling._fail_loud import warn_audit_error
from tooling.audits.guide._guide_scope import get_repo_root, guide_dir_for_slug


# ── Quality profiles ─────────────────────────────────────────────────────────

PROFILES: dict[str, dict[str, int | float]] = {
    "default": {
        "margin_min": 8,
        "margin_max": 14,
        "kc_min": 2,
        "kc_max": 4,
        "problems_min_per_guide": 15,
        "vignettes_min_per_guide": 3,
    },
    "aws_cert": {
        "margin_min": 4,
        "margin_max": 14,
        "kc_min": 2,
        "kc_max": 5,
        "problems_min_per_guide": 15,
        "vignettes_min_per_guide": 3,
    },
}


# ── Margin note patterns ────────────────────────────────────────────────────
# course_learning guides use convenience macros, not raw \marginnote

MARGIN_PATTERNS: list[str] = [
    r"\\marginnote",
    r"\\interviewmargin\{",
    r"\\patternmargin\{",
    r"\\warningmargin\{",
    r"\\crossrefmargin\{",
    r"\\practicemargin\{",
    r"\\formulamargin\{",
    r"\\exammargin\{",
]


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class ChapterMetrics:
    """Quality metrics for a single chapter."""

    guide: str
    chapter: str
    file_path: str
    line_count: int = 0
    term_count: int = 0
    problem_count: int = 0
    vignette_count: int = 0
    redflag_count: int = 0
    interview_count: int = 0
    keyconcept_count: int = 0
    margin_note_count: int = 0
    minted_count: int = 0
    verbatim_count: int = 0
    los_count: int = 0
    solution_count: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class GuideMetrics:
    """Aggregated metrics for a guide."""

    slug: str
    tier: int = 1
    profile: str = "default"
    chapter_count: int = 0
    total_lines: int = 0
    total_terms: int = 0
    total_problems: int = 0
    total_vignettes: int = 0
    total_redflags: int = 0
    total_interviews: int = 0
    total_margin_notes: int = 0
    total_keyconcepts: int = 0
    total_minted: int = 0
    total_verbatim: int = 0
    total_los: int = 0
    total_solutions: int = 0
    chapters: list[ChapterMetrics] = field(default_factory=list)

    # Status
    margin_status: str = ""
    kc_status: str = ""
    problem_status: str = ""
    vignette_status: str = ""
    overall_status: str = ""

    def compute_status(self) -> None:
        """Compute traffic-light status for each dimension."""
        prof = PROFILES.get(self.profile, PROFILES["default"])

        if self.chapter_count == 0:
            self.margin_status = self.kc_status = "RED"
            self.problem_status = self.vignette_status = "RED"
            self.overall_status = "RED"
            return

        avg_margin = self.total_margin_notes / self.chapter_count
        avg_kc = self.total_keyconcepts / self.chapter_count

        # Margins
        if avg_margin >= prof["margin_min"]:
            self.margin_status = "GREEN"
        elif avg_margin >= prof["margin_min"] * 0.5:
            self.margin_status = "YELLOW"
        else:
            self.margin_status = "RED"

        # Keyconcepts
        if avg_kc >= prof["kc_min"]:
            self.kc_status = "GREEN"
        elif avg_kc >= 1.0:
            self.kc_status = "YELLOW"
        else:
            self.kc_status = "RED"

        # Problems
        if self.total_problems >= prof["problems_min_per_guide"]:
            self.problem_status = "GREEN"
        elif self.total_problems >= prof["problems_min_per_guide"] * 0.5:
            self.problem_status = "YELLOW"
        else:
            self.problem_status = "RED"

        # Vignettes
        if self.total_vignettes >= prof["vignettes_min_per_guide"]:
            self.vignette_status = "GREEN"
        elif self.total_vignettes >= 1:
            self.vignette_status = "YELLOW"
        else:
            self.vignette_status = "RED"

        # Overall: worst of all dimensions
        statuses = [self.margin_status, self.kc_status,
                     self.problem_status, self.vignette_status]
        if "RED" in statuses:
            self.overall_status = "RED"
        elif "YELLOW" in statuses:
            self.overall_status = "YELLOW"
        else:
            self.overall_status = "GREEN"


# ── Extraction ───────────────────────────────────────────────────────────────


def resolve_includes(content: str, base_dir: Path) -> str:
    """Resolve \\input{} includes and return expanded content."""
    expanded = content
    input_pattern = re.compile(r"\\input\{([^}]+)\}")
    includes = input_pattern.findall(content)

    for inc_path in includes:
        for candidate in [base_dir / f"{inc_path}.tex", base_dir / inc_path]:
            if candidate.exists():
                try:
                    included = candidate.read_text(encoding="utf-8")
                    included = resolve_includes(included, base_dir)
                    expanded += f"\n% === Included from {inc_path} ===\n"
                    expanded += included
                except Exception as exc:  # noqa: BLE001 — the include's content is
                    # silently absent from metrics otherwise
                    warn_audit_error("audit_content_quality.includes", candidate, exc)
                break

    return expanded


def extract_chapter_metrics(tex_path: Path, guide_slug: str) -> ChapterMetrics:
    """Extract quality metrics from a chapter .tex file."""
    metrics = ChapterMetrics(
        guide=guide_slug,
        chapter=tex_path.stem,
        file_path=str(tex_path),
    )

    try:
        raw = tex_path.read_text(encoding="utf-8")
        notebook_dir = tex_path.parent.parent
        content = resolve_includes(raw, notebook_dir)

        metrics.line_count = len(content.split("\n"))
        # Terms: both \term{ and \term[ variants
        metrics.term_count = len(re.findall(r"\\term[\[\{]", content))
        metrics.problem_count = len(re.findall(r"\\begin\{problem\}", content))
        metrics.vignette_count = len(re.findall(r"\\begin\{vignette\}", content))
        metrics.redflag_count = len(re.findall(r"\\begin\{redflag\}", content))
        metrics.interview_count = len(re.findall(r"\\begin\{interviewcontext\}", content))
        metrics.keyconcept_count = len(re.findall(r"\\begin\{keyconcept\}", content))

        # Margin notes: all convenience macros + raw
        metrics.margin_note_count = sum(
            len(re.findall(pat, content)) for pat in MARGIN_PATTERNS
        )

        metrics.minted_count = len(re.findall(r"\\begin\{minted\}", content))
        metrics.verbatim_count = len(re.findall(r"\\begin\{verbatim\}", content))
        metrics.los_count = len(re.findall(r"\\los\{", content))
        metrics.solution_count = len(re.findall(r"\\begin\{solution\}", content))

    except Exception as e:
        metrics.issues.append(f"Error reading file: {e}")

    return metrics


# ── Guide scanning ───────────────────────────────────────────────────────────


def load_guides_yml(repo_root: Path) -> list[dict[str, Any]]:
    """Load guide metadata from guides.yml."""
    guides_path = repo_root / "guides.yml"
    if not guides_path.exists():
        print(f"Error: {guides_path} not found", file=sys.stderr)
        sys.exit(1)

    data = yaml.safe_load(guides_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "guides" in data:
        return data["guides"]
    if isinstance(data, list):
        return data
    return []


def audit_guide(
    repo_root: Path, guide_meta: dict[str, Any]
) -> Optional[GuideMetrics]:
    """Audit all chapters in a guide."""
    slug = guide_meta["slug"]
    gd = guide_dir_for_slug(slug)
    if gd is None:
        return None
    chapters_dir = gd / "guide" / "chapters"

    if not chapters_dir.exists():
        return None

    profile = guide_meta.get("profile", "default")
    tier = guide_meta.get("tier", 1)

    metrics = GuideMetrics(slug=slug, tier=tier, profile=profile)

    for tex_file in sorted(chapters_dir.glob("*.tex")):
        if tex_file.stem.startswith("_") or tex_file.stem == "00_how_to_use":
            continue

        ch = extract_chapter_metrics(tex_file, slug)
        metrics.chapters.append(ch)
        metrics.chapter_count += 1
        metrics.total_lines += ch.line_count
        metrics.total_terms += ch.term_count
        metrics.total_problems += ch.problem_count
        metrics.total_vignettes += ch.vignette_count
        metrics.total_redflags += ch.redflag_count
        metrics.total_interviews += ch.interview_count
        metrics.total_margin_notes += ch.margin_note_count
        metrics.total_keyconcepts += ch.keyconcept_count
        metrics.total_minted += ch.minted_count
        metrics.total_verbatim += ch.verbatim_count
        metrics.total_los += ch.los_count
        metrics.total_solutions += ch.solution_count

    if metrics.chapter_count == 0:
        return None

    metrics.compute_status()
    return metrics


# ── Output ───────────────────────────────────────────────────────────────────

STATUS_ICON = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}


def print_dashboard(guides: list[GuideMetrics]) -> None:
    """Print a compact traffic-light dashboard."""
    total_ch = sum(g.chapter_count for g in guides)
    total_m = sum(g.total_margin_notes for g in guides)
    total_kc = sum(g.total_keyconcepts for g in guides)

    print(f"\n{'=' * 70}")
    print(f"CONTENT QUALITY AUDIT — {len(guides)} guides, {total_ch} chapters")
    print(f"{'=' * 70}")
    print(f"  Margins:     {total_m} ({total_m / total_ch:.1f}/ch)")
    print(f"  Keyconcepts: {total_kc} ({total_kc / total_ch:.1f}/ch)")
    print(f"  Problems:    {sum(g.total_problems for g in guides)}")
    print(f"  Vignettes:   {sum(g.total_vignettes for g in guides)}")
    print()

    # Table header
    hdr = f"{'Guide':<50} {'Ch':>3} {'Mgn/ch':>7} {'KC/ch':>6} {'Prob':>5} {'Vig':>4}  M  K  P  V"
    print(hdr)
    print("-" * len(hdr))

    for g in guides:
        avg_m = f"{g.total_margin_notes / g.chapter_count:.1f}" if g.chapter_count else "0"
        avg_k = f"{g.total_keyconcepts / g.chapter_count:.1f}" if g.chapter_count else "0"
        mi = STATUS_ICON.get(g.margin_status, "?")
        ki = STATUS_ICON.get(g.kc_status, "?")
        pi = STATUS_ICON.get(g.problem_status, "?")
        vi = STATUS_ICON.get(g.vignette_status, "?")
        print(
            f"{g.slug:<50} {g.chapter_count:>3} {avg_m:>7} {avg_k:>6} "
            f"{g.total_problems:>5} {g.total_vignettes:>4}  {mi} {ki} {pi} {vi}"
        )

    # Summary
    green_count = sum(1 for g in guides if g.overall_status == "GREEN")
    yellow_count = sum(1 for g in guides if g.overall_status == "YELLOW")
    red_count = sum(1 for g in guides if g.overall_status == "RED")
    print(f"\nOverall: {green_count} GREEN, {yellow_count} YELLOW, {red_count} RED")


def to_json(guides: list[GuideMetrics]) -> dict:
    """Serialize to JSON-compatible dict."""
    total_ch = sum(g.chapter_count for g in guides)
    return {
        "generated": datetime.now().isoformat(),
        "guide_count": len(guides),
        "summary": {
            "total_chapters": total_ch,
            "total_lines": sum(g.total_lines for g in guides),
            "total_terms": sum(g.total_terms for g in guides),
            "total_margins": sum(g.total_margin_notes for g in guides),
            "total_keyconcepts": sum(g.total_keyconcepts for g in guides),
            "total_problems": sum(g.total_problems for g in guides),
            "total_vignettes": sum(g.total_vignettes for g in guides),
            "total_los": sum(g.total_los for g in guides),
            "avg_margins_per_ch": round(
                sum(g.total_margin_notes for g in guides) / total_ch, 1
            ) if total_ch else 0,
            "avg_kcs_per_ch": round(
                sum(g.total_keyconcepts for g in guides) / total_ch, 1
            ) if total_ch else 0,
        },
        "guides": [
            {
                "slug": g.slug,
                "tier": g.tier,
                "chapter_count": g.chapter_count,
                "total_lines": g.total_lines,
                "total_terms": g.total_terms,
                "total_problems": g.total_problems,
                "total_vignettes": g.total_vignettes,
                "total_margin_notes": g.total_margin_notes,
                "total_keyconcepts": g.total_keyconcepts,
                "total_los": g.total_los,
                "avg_margins_per_ch": round(
                    g.total_margin_notes / g.chapter_count, 1
                ) if g.chapter_count else 0,
                "avg_kcs_per_ch": round(
                    g.total_keyconcepts / g.chapter_count, 1
                ) if g.chapter_count else 0,
                "status": {
                    "margins": g.margin_status,
                    "keyconcepts": g.kc_status,
                    "problems": g.problem_status,
                    "vignettes": g.vignette_status,
                    "overall": g.overall_status,
                },
            }
            for g in guides
        ],
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Content quality audit for LaTeX guides"
    )
    parser.add_argument("--all", action="store_true", help="Audit all guides (not just Tier 1)")
    parser.add_argument("--guide", type=str, help="Audit a single guide by slug")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any RED status")
    parser.add_argument(
        "--repo-root", type=str, default=None,
        help="Override repo root (default: look for guides.yml in cwd or parents)"
    )
    args = parser.parse_args()

    # Find repo root
    if args.repo_root:
        repo_root = Path(args.repo_root)
    else:
        repo_root = get_repo_root()

    all_guides = load_guides_yml(repo_root)

    # Filter. Default scans the whole fleet — under the all-Manning tier model a
    # per-guide audit isn't restricted to tier 1; the Gold runner (T2) is what
    # filters to Silver-PASS guides. --all is kept as an explicit synonym.
    if args.guide:
        all_guides = [g for g in all_guides if g["slug"] == args.guide]

    # Audit
    results: list[GuideMetrics] = []
    for meta in all_guides:
        r = audit_guide(repo_root, meta)
        if r:
            results.append(r)

    if not results:
        print("No guides found to audit.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(to_json(results), indent=2))
    else:
        print_dashboard(results)

    if args.strict:
        red_count = sum(1 for g in results if g.overall_status == "RED")
        if red_count > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
