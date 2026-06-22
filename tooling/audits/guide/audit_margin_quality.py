#!/usr/bin/env python3
"""
Hub-portable margin quality audit for LaTeX guides.

Validates margin notes for:
- Category usage (standard vs non-standard)
- Generic content detection ("important concept", "be careful", etc.)
- Density per chapter (too sparse, too dense)
- Word count (max ~25 words)

Designed for course_learning convenience macros (interviewmargin,
patternmargin, etc.) and raw marginnote[Category] from
interview_prep_series.

Usage:
    python audit_margin_quality.py                           # All Tier 1 guides
    python audit_margin_quality.py --guide dlai_advanced_rag # Single guide
    python audit_margin_quality.py --json                    # JSON output
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

from tooling.audits.guide._guide_scope import get_repo_root, guide_dir_for_slug


# ── Standard categories ──────────────────────────────────────────────────────

STANDARD_CATEGORIES: dict[str, str] = {
    "Interview": "interviewmargin",
    "Pattern": "patternmargin",
    "Formula": "formulamargin",
    "Warning": "warningmargin",
    "Practice": "practicemargin",
    "Cross-Ref": "crossrefmargin",
    # These are interview_prep_series only:
    "SOA": None,
    "IC5 Signal": None,
    "Exam": "exammargin",
}

# Convenience macro → category mapping
MACRO_TO_CATEGORY: dict[str, str] = {
    "interviewmargin": "Interview",
    "patternmargin": "Pattern",
    "formulamargin": "Formula",
    "warningmargin": "Warning",
    "practicemargin": "Practice",
    "crossrefmargin": "Cross-Ref",
    "exammargin": "Exam",
}

# ── Generic content patterns (anti-patterns) ────────────────────────────────

GENERIC_PATTERNS: list[tuple[str, str]] = [
    (r"\bimportant concept\b", "bare meta-commentary"),
    (r"\bbe careful\b", "bare meta-commentary"),
    (r"\bcommonly asked\b", "vague company signal"),
    (r"\bimportant topic\b", "bare meta-commentary"),
    (r"\bpractice this\b", "bare meta-commentary"),
    (r"\bsee vol \d+\b", "vague cross-ref (missing chapter)"),
    (r"\bsimilar to\b.*\bmethods\b", "vague analogy"),
]

# ── Content-free templated/scaffold margins ──────────────────────────────────
# A distinct class from GENERIC_PATTERNS: a margin whose ENTIRE text is a
# scaffold template that merely restates the chapter title ("Common mistake in
# <title>.") with no actual mistake / pattern / technique. Patterns are anchored
# to the whole note and exclude a ``:`` (which would introduce real content), so
# a genuine "Common mistake in X: <specific failure>" is NOT flagged. Gated
# independently of density via ``--strict-templates`` (see main).
TEMPLATE_SIGNATURES: list[tuple[str, str]] = [
    (r"(?i)^\s*common mistake in [^:]{1,90}\.?\s*$",
     "templated scaffold: names the section, not the mistake"),
    (r"(?i)^\s*key pattern from [^:]{1,90}\.?\s*$",
     "templated scaffold: names the section, not the pattern"),
    (r"(?i)^\s*implement a small example applying [^:]{1,90}\.?\s*$",
     "templated scaffold: generic practice stub (no time/technique)"),
    (r"(?i)^\s*see related [^:]{1,60}chapters?[^:]{0,40}\.?\s*$",
     "templated scaffold: vague cross-reference"),
]
_TEMPLATE_RES = [(re.compile(p), label) for p, label in TEMPLATE_SIGNATURES]


def templated_margin_label(text: str) -> Optional[str]:
    """Return the scaffold-template label if ``text`` is a content-free template."""
    for rx, label in _TEMPLATE_RES:
        if rx.match(text):
            return label
    return None

# ── Density thresholds ───────────────────────────────────────────────────────
# B12: Chapter-type-aware density targets (Stull & Mayer 2007)
# Code-heavy chapters (>5 minted blocks) need fewer margin notes to avoid
# split-attention with code. Theory chapters keep higher targets.

DENSITY_MIN_THEORY = 8
DENSITY_MAX_THEORY = 14
DENSITY_MIN_CODE = 5     # Relaxed for code-heavy chapters
DENSITY_MAX_CODE = 10
MINTED_THRESHOLD = 5     # Chapters with >5 minted blocks = "code-heavy"
MAX_WORDS = 30  # Slightly relaxed from 25 to avoid false positives

# Legacy aliases for backward compatibility
DENSITY_MIN = DENSITY_MIN_THEORY
DENSITY_MAX = DENSITY_MAX_THEORY


# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class MarginNote:
    """A single margin note extracted from a .tex file."""

    category: str
    text: str
    line_number: int
    file_path: str
    word_count: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class ChapterMarginMetrics:
    """Margin metrics for a single chapter."""

    guide: str
    chapter: str
    file_path: str
    total_notes: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    generic_count: int = 0
    over_length_count: int = 0
    split_attention_count: int = 0
    minted_count: int = 0  # B12: code block count for chapter-type detection
    chapter_type: str = "theory"  # "theory" or "code-heavy"
    notes: list[MarginNote] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class GuideMarginMetrics:
    """Aggregated margin metrics for a guide."""

    slug: str
    total_notes: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    generic_count: int = 0
    over_length_count: int = 0
    split_attention_count: int = 0
    non_standard_count: int = 0
    chapter_count: int = 0
    code_heavy_chapters: int = 0
    theory_chapters: int = 0
    chapters: list[ChapterMarginMetrics] = field(default_factory=list)
    density_status: str = ""
    quality_status: str = ""

    def compute_status(self) -> None:
        """Compute traffic-light status with chapter-type-aware density."""
        if self.chapter_count == 0:
            self.density_status = self.quality_status = "RED"
            return

        # B12: Chapter-type-aware density evaluation
        # Instead of one avg across all chapters, evaluate each chapter
        # against its type-appropriate threshold
        chapters_below_min = 0
        for ch in self.chapters:
            min_threshold = DENSITY_MIN_CODE if ch.chapter_type == "code-heavy" else DENSITY_MIN_THEORY
            if ch.total_notes < min_threshold:
                chapters_below_min += 1

        below_rate = chapters_below_min / self.chapter_count if self.chapter_count else 1
        if below_rate <= 0.15:
            self.density_status = "GREEN"
        elif below_rate <= 0.40:
            self.density_status = "YELLOW"
        else:
            self.density_status = "RED"

        # Quality: generic + over-length + split-attention as fraction of total
        if self.total_notes == 0:
            self.quality_status = "RED"
            return

        issue_rate = (self.generic_count + self.over_length_count + self.split_attention_count) / self.total_notes
        if issue_rate <= 0.05:
            self.quality_status = "GREEN"
        elif issue_rate <= 0.15:
            self.quality_status = "YELLOW"
        else:
            self.quality_status = "RED"


# ── Extraction ───────────────────────────────────────────────────────────────

# Raw \marginnote[Category]{text}
RAW_MARGIN_RE = re.compile(
    r"\\marginnote\[([^\]]+)\]\{([^}]+)\}", re.DOTALL
)

# Convenience macros: \interviewmargin{text}
CONVENIENCE_MARGIN_RE = re.compile(
    r"\\(interviewmargin|patternmargin|formulamargin|warningmargin|"
    r"practicemargin|crossrefmargin|exammargin)\{([^}]+)\}",
    re.DOTALL,
)


def extract_margins_from_chapter(
    tex_path: Path, guide_slug: str
) -> ChapterMarginMetrics:
    """Extract and analyze margin notes from a chapter."""
    metrics = ChapterMarginMetrics(
        guide=guide_slug,
        chapter=tex_path.stem,
        file_path=str(tex_path),
    )

    try:
        content = tex_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Find all raw \marginnote entries
        for match in RAW_MARGIN_RE.finditer(content):
            category = match.group(1).strip()
            text = match.group(2).strip()
            line_num = content[:match.start()].count("\n") + 1

            note = MarginNote(
                category=category,
                text=text,
                line_number=line_num,
                file_path=str(tex_path),
                word_count=len(text.split()),
            )
            _check_note_quality(note)
            metrics.notes.append(note)

        # Find all convenience macro entries
        for match in CONVENIENCE_MARGIN_RE.finditer(content):
            macro_name = match.group(1)
            text = match.group(2).strip()
            category = MACRO_TO_CATEGORY.get(macro_name, macro_name)
            line_num = content[:match.start()].count("\n") + 1

            note = MarginNote(
                category=category,
                text=text,
                line_number=line_num,
                file_path=str(tex_path),
                word_count=len(text.split()),
            )
            _check_note_quality(note)
            metrics.notes.append(note)

        # B12: Count code blocks for chapter-type classification
        # Include minted, pycode, sqlcode, latexcode, verbatim (all code-rendering envs)
        code_envs = re.findall(
            r"\\begin\{(?:minted|pycode|sqlcode|latexcode|verbatim)\}", content
        )
        metrics.minted_count = len(code_envs)
        metrics.chapter_type = "code-heavy" if metrics.minted_count > MINTED_THRESHOLD else "theory"

        # Aggregate
        metrics.total_notes = len(metrics.notes)
        for note in metrics.notes:
            metrics.by_category[note.category] = (
                metrics.by_category.get(note.category, 0) + 1
            )
            if any("generic" in i for i in note.issues):
                metrics.generic_count += 1
            if any("over-length" in i for i in note.issues):
                metrics.over_length_count += 1
            if any("split-attention" in i for i in note.issues):
                metrics.split_attention_count += 1

    except Exception as e:
        metrics.issues.append(f"Error: {e}")

    return metrics


def _check_note_quality(note: MarginNote) -> None:
    """Check a margin note for quality issues.

    Includes split-attention detection (Mayer 2009, Sweller 1991):
    - Q&A margin notes (contain both question and answer = should be inline)
    - Formula notes explaining adjacent equations (should be contiguous)
    """
    text_lower = note.text.lower()

    # Generic content
    for pattern, issue_type in GENERIC_PATTERNS:
        if re.search(pattern, text_lower):
            note.issues.append(f"generic: {issue_type}")

    # Over-length
    if note.word_count > MAX_WORDS:
        note.issues.append(f"over-length: {note.word_count} words (max {MAX_WORDS})")

    # Non-standard category
    if note.category not in STANDARD_CATEGORIES:
        note.issues.append(f"non-standard category: {note.category}")

    # B10: Split-attention detection
    # Q&A in margin: only flag if total note exceeds MAX_WORDS AND answer is substantial
    # Concise Q&A notes (<=30 words) are appropriate for interview prep margins
    if "?" in note.text and note.word_count > MAX_WORDS:
        q_idx = note.text.index("?")
        answer_part = note.text[q_idx + 1:].strip()
        if len(answer_part.split()) > 12:
            note.issues.append("split-attention: Q&A in margin (move to inline box)")

    # Formula note that just restates an equation (begins with $ and is very short)
    # Longer formula notes (15+ words) that start with $ typically provide context
    # beyond the equation and are legitimate quick-reference margins
    if note.category == "Formula" and note.text.strip().startswith("$") and note.word_count < 15:
        note.issues.append("split-attention: formula note starts with equation (may duplicate adjacent math)")


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


def audit_guide_margins(
    repo_root: Path, guide_meta: dict[str, Any]
) -> Optional[GuideMarginMetrics]:
    """Audit margin quality for a guide."""
    slug = guide_meta["slug"]
    gd = guide_dir_for_slug(slug)
    if gd is None:
        return None
    chapters_dir = gd / "guide" / "chapters"

    if not chapters_dir.exists():
        return None

    metrics = GuideMarginMetrics(slug=slug)

    for tex_file in sorted(chapters_dir.glob("*.tex")):
        if tex_file.stem.startswith("_") or tex_file.stem == "00_how_to_use":
            continue

        ch = extract_margins_from_chapter(tex_file, slug)
        metrics.chapters.append(ch)
        metrics.chapter_count += 1
        metrics.total_notes += ch.total_notes
        metrics.generic_count += ch.generic_count
        metrics.over_length_count += ch.over_length_count
        metrics.split_attention_count += ch.split_attention_count
        if ch.chapter_type == "code-heavy":
            metrics.code_heavy_chapters += 1
        else:
            metrics.theory_chapters += 1
        for cat, cnt in ch.by_category.items():
            metrics.by_category[cat] = metrics.by_category.get(cat, 0) + cnt

    if metrics.chapter_count == 0:
        return None

    # Count non-standard
    metrics.non_standard_count = sum(
        cnt for cat, cnt in metrics.by_category.items()
        if cat not in STANDARD_CATEGORIES
    )

    metrics.compute_status()
    return metrics


# ── Output ───────────────────────────────────────────────────────────────────

STATUS_ICON = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}


def print_dashboard(guides: list[GuideMarginMetrics]) -> None:
    """Print margin quality dashboard."""
    total = sum(g.total_notes for g in guides)
    total_ch = sum(g.chapter_count for g in guides)
    total_generic = sum(g.generic_count for g in guides)

    print(f"\n{'=' * 70}")
    print(f"MARGIN QUALITY AUDIT — {len(guides)} guides, {total} notes")
    print(f"{'=' * 70}")
    print(f"  Avg/ch:    {total / total_ch:.1f}" if total_ch else "")
    print(f"  Generic:   {total_generic} ({total_generic / total * 100:.1f}%)" if total else "")
    print()

    # Category breakdown
    all_cats: dict[str, int] = {}
    for g in guides:
        for cat, cnt in g.by_category.items():
            all_cats[cat] = all_cats.get(cat, 0) + cnt

    print("Category distribution:")
    for cat, cnt in sorted(all_cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:<15} {cnt:>5}")
    print()

    # Per-guide table
    hdr = f"{'Guide':<50} {'Notes':>5} {'Avg/ch':>7} {'Generic':>8} {'Long':>5}  D  Q"
    print(hdr)
    print("-" * len(hdr))

    for g in guides:
        avg = f"{g.total_notes / g.chapter_count:.1f}" if g.chapter_count else "0"
        di = STATUS_ICON.get(g.density_status, "?")
        qi = STATUS_ICON.get(g.quality_status, "?")
        print(
            f"{g.slug:<50} {g.total_notes:>5} {avg:>7} "
            f"{g.generic_count:>8} {g.over_length_count:>5}  {di} {qi}"
        )


def to_json(guides: list[GuideMarginMetrics]) -> dict:
    """Serialize to JSON."""
    return {
        "generated": datetime.now().isoformat(),
        "guide_count": len(guides),
        "total_notes": sum(g.total_notes for g in guides),
        "total_generic": sum(g.generic_count for g in guides),
        "total_over_length": sum(g.over_length_count for g in guides),
        "total_split_attention": sum(g.split_attention_count for g in guides),
        "total_code_heavy_chapters": sum(g.code_heavy_chapters for g in guides),
        "total_theory_chapters": sum(g.theory_chapters for g in guides),
        "guides": [
            {
                "slug": g.slug,
                "total_notes": g.total_notes,
                "chapter_count": g.chapter_count,
                "code_heavy_chapters": g.code_heavy_chapters,
                "theory_chapters": g.theory_chapters,
                "by_category": g.by_category,
                "generic_count": g.generic_count,
                "over_length_count": g.over_length_count,
                "split_attention_count": g.split_attention_count,
                "density_status": g.density_status,
                "quality_status": g.quality_status,
            }
            for g in guides
        ],
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Margin quality audit for LaTeX guides")
    parser.add_argument("--all", action="store_true", help="Audit all guides")
    parser.add_argument("--guide", type=str, help="Single guide slug")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--strict", "--check", dest="strict", action="store_true",
                        help="exit 1 if any audited guide is margin density/quality RED")
    parser.add_argument("--strict-templates", dest="strict_templates", action="store_true",
                        help="exit 1 if any audited guide has content-free templated/scaffold "
                             "margins (independent of density; this is the gated subset)")
    parser.add_argument("--repo-root", type=str, default=None)
    args = parser.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root)
    else:
        repo_root = get_repo_root()

    all_guides = load_guides_yml(repo_root)

    # Default scans the whole fleet (see audit_content_quality); the Gold runner
    # (T2) filters to Silver-PASS. --all kept as an explicit synonym.
    if args.guide:
        all_guides = [g for g in all_guides if g["slug"] == args.guide]

    results: list[GuideMarginMetrics] = []
    for meta in all_guides:
        r = audit_guide_margins(repo_root, meta)
        if r:
            results.append(r)

    if not results:
        print("No guides found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(to_json(results), indent=2))
    else:
        print_dashboard(results)

    # --strict: a RED density (too sparse) or RED quality (too many generic /
    # over-length / split-attention notes) is a Gold-blocking failure. Gated
    # behind --strict so the default advisory run (and audit_gold's current
    # advisory invocation) is unaffected. FAIL goes to stderr to keep --json
    # stdout parseable; exit 1 is what audit_gold G2 keys on.
    if args.strict:
        red = [g for g in results if g.density_status == "RED" or g.quality_status == "RED"]
        for g in red:
            flags = [s for s, st in (("density", g.density_status), ("quality", g.quality_status)) if st == "RED"]
            print(f"FAIL  {g.slug}: margin {'+'.join(flags)} RED", file=sys.stderr)
        if red:
            sys.exit(1)

    # --strict-templates: a content-free scaffold margin ("Common mistake in
    # <title>.") is a visible craft defect. Gated SEPARATELY from --strict so the
    # templated-margin subset can be a hard G2 gate while full margin density/
    # quality gating (T2b) stays deferred. FAIL → stderr; exit 1 keys G2.
    if args.strict_templates:
        flagged = False
        for g in results:
            for ch in g.chapters:
                for note in ch.notes:
                    label = templated_margin_label(note.text)
                    if label:
                        flagged = True
                        print(f"FAIL  {g.slug}: templated margin ({Path(note.file_path).name}:"
                              f"{note.line_number}) — {label}", file=sys.stderr)
        if flagged:
            sys.exit(1)


if __name__ == "__main__":
    main()
