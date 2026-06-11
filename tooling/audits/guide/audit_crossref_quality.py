#!/usr/bin/env python3
"""
Audit cross-reference quality in course_learning LaTeX guides.

Validates \\crossrefmargin{} notes by checking:
1. Internal chapter refs (\\ref{ch:...}) — validated against labels in same guide
2. External guide refs — validated against guides.yml slugs/titles
3. Orphaned guides — guides with zero incoming cross-refs

Does NOT validate interview_prep_series volume refs (vol1, vol6, etc.)
since those are external to this repo.

Usage:
    python shared/audits/audit_crossref_quality.py                  # All Tier 1
    python shared/audits/audit_crossref_quality.py --guide dlai_advanced_rag
    python shared/audits/audit_crossref_quality.py --json
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

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_all_guides,
    get_guide_by_slug,
    resolve_guide_name,
)


# ── Patterns ─────────────────────────────────────────────────────────────────

LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(r"\\ref\{([^}]+)\}")

# Internal chapter/module references without \ref{}
INTERNAL_CH_RE = re.compile(
    r"(?:"
    r"\b(?:see\s+)?(?:Ch(?:apter)?|Module|Appendix|Section|Part)"
    r"(?:\.?\s*~?\s*\\?\s*)"  # Handle Ch.~5, Ch~3, Ch.\ 20, Ch 5
    r"(?:ref\{[^}]+\}|\d+(?:\s*[-–—]+\s*\d+)?|[A-Z]{1,4}\b)"
    r"|"
    r"\bC\d+\\?_?M\d+"  # Course module notation: C1M3, C1\_M2
    r"|"
    r"\bM\d+\s+Sec"  # Module section notation: M4 Sec.~4
    r"|"
    r"\bSee\s+(?:the\s+)?(?:next|previous|following|preceding)\b"
    r"|"
    r"\\pageref\{"  # Page references
    r")",
    re.IGNORECASE,
)

# External guide reference patterns (slug-like or title-like)
# Matches: "dlai_advanced_rag", "CI Python Ch 8", "PyTorch cert Ch 3"
GUIDE_SLUG_RE = re.compile(r"\b(dlai_\w+|manning_\w+|coursera_\w+)\b")
GUIDE_TITLE_RE = re.compile(
    r"\b(PyTorch|GRPO|Graph-Powered|NLP in Action|LLMs in Production|"
    r"AI-Powered Search|Knowledge Graphs|GraphRAG|Semantic Search|"
    r"Multimodal Search|Structured LLM|Document AI|Preprocessing|"
    r"Advanced RAG|JAX|RL Specialization|Agent Memory|Agentic AI|"
    r"Agentic KG|CrewAI|Finetuning RL|Transformer LLMs|"
    r"Long-Term Memory|MCP Anthropic|NeMo Agent|Pydantic|"
    r"Quantization in Depth|KG LLMs|LLMs? from Scratch|"
    r"Python Workout|Transformers in Action|"
    # DLAI courses
    r"Red Teaming|Quality.?Safety|Automated Testing|Evaluating.?Agents|"
    r"A2A Protocol|Agent Skills|E2B|Coding Agents|Function Calling|"
    r"RAGAS|Post.?Training|Finetuning|Attention.?Transformers|"
    r"OpenAI.?Function|Retrieval Optimization|RAG Course|"
    r"LangChain|LangGraph|MCP|"
    # Manning books
    r"Grokking (?:ML|Deep)|Deep Learning Vision|Docker in Action|"
    r"Designing APIs|Practices.?Python|RAG Seminal|"
    r"Rearchitecting LLMs|Grokking Deep RL|"
    # Additional book/tool references
    r"Moroney|GNNs in Action|NeMo Guardrails|Essential Math|"
    r"Leslie Smith|Serving LLMs|HuggingFace TRL)\b",
    re.IGNORECASE,
)

# Volume references (point to interview_prep_series — informational only)
VOL_REF_RE = re.compile(r"\bvol\d+\b|\bvol[\s_]\w+\b", re.IGNORECASE)

# Informational cross-refs: code file refs, complexity notes, tool comparisons,
# technique details — valid margin content but not guide-to-guide pointers
INFORMATIONAL_RE = re.compile(
    r"(?:"
    r"\\code\{"             # Internal file or API references
    r"|\$O\("               # Complexity notation: $O(n^2)$
    r"|\bvs\.?\s"           # Comparisons: "X vs Y", "X vs. Y"
    r"|\bint[48]\b"         # Quantization: int4, int8
    r"|\bpaper\b"           # Academic paper references
    r"|\b\d{4}\)"           # Year in parentheses: (2018)
    r"|\bONNX\b"            # ONNX runtime/format
    r"|\bMLOps\b"           # MLOps references
    r"|\bFlash Attention\b" # Specific techniques
    r"|\binterview map\b"   # Interview resource references
    r")",
    re.IGNORECASE,
)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class CrossRef:
    """A single cross-reference finding."""

    guide_slug: str
    file_path: str
    line_number: int
    text: str
    ref_type: str  # internal, external_guide, external_vol, informational, unresolved
    target: str  # resolved target (guide slug, label, or raw text)
    valid: bool = True


@dataclass
class GuideCrossRefMetrics:
    """Cross-reference metrics for a guide."""

    slug: str
    total_crossrefs: int = 0
    internal_refs: int = 0
    external_guide_refs: int = 0
    external_vol_refs: int = 0
    informational_refs: int = 0
    unresolved_refs: int = 0
    broken_internal: list[CrossRef] = field(default_factory=list)
    refs: list[CrossRef] = field(default_factory=list)


# ── Scanning ─────────────────────────────────────────────────────────────────


MACRO_LABEL_RE = re.compile(r"\\(?:lesson|module)header\{(\w+)\}")


def collect_labels(chapters_dir: Path) -> set[str]:
    """Collect all \\label{} definitions in a guide's chapters.

    Also detects labels generated by \\lessonheader{} and \\moduleheader{} macros,
    which expand to \\label{ch:<id>} at compile time.
    """
    labels: set[str] = set()
    for tex_file in chapters_dir.glob("*.tex"):
        try:
            content = tex_file.read_text(encoding="utf-8")
            labels.update(LABEL_RE.findall(content))
            # Detect macro-generated labels: \lessonheader{L1} -> \label{ch:L1}
            for m in MACRO_LABEL_RE.finditer(content):
                labels.add(f"ch:{m.group(1)}")
        except Exception:
            pass
    # Also check appendices
    appendices = chapters_dir.parent / "appendices"
    if appendices.exists():
        for tex_file in appendices.glob("*.tex"):
            try:
                content = tex_file.read_text(encoding="utf-8")
                labels.update(LABEL_RE.findall(content))
            except Exception:
                pass
    return labels


def classify_crossref(
    text: str,
    guide_slug: str,
    labels: set[str],
    all_slugs: set[str],
) -> tuple[str, str, bool]:
    """Classify a cross-reference and determine if it's valid.

    Returns: (ref_type, target, is_valid)
    """
    # Check for internal \ref{} references
    internal_refs = REF_RE.findall(text)
    if internal_refs:
        for ref in internal_refs:
            if ref not in labels:
                return "internal", ref, False
        return "internal", ",".join(internal_refs), True

    # Check for external guide references (by slug)
    slug_matches = GUIDE_SLUG_RE.findall(text)
    for slug in slug_matches:
        if slug != guide_slug:  # Don't count self-refs
            resolved = resolve_guide_name(slug)
            if resolved:
                return "external_guide", resolved, True
            return "external_guide", slug, slug in all_slugs

    # Check for external guide references (by title keyword)
    title_matches = GUIDE_TITLE_RE.findall(text)
    for title in title_matches:
        resolved = resolve_guide_name(title)
        if resolved and resolved != guide_slug:
            return "external_guide", resolved, True

    # Check for volume references (interview_prep_series)
    vol_matches = VOL_REF_RE.findall(text)
    if vol_matches:
        return "external_vol", vol_matches[0], True  # Can't validate external repo

    # Check for internal chapter/module references (e.g., "see Module 2", "Ch 3")
    if INTERNAL_CH_RE.search(text):
        return "internal", text[:60], True

    # Informational cross-refs: valid notes containing code refs, complexity
    # notation, tool comparisons, or technique details — not guide pointers
    if INFORMATIONAL_RE.search(text):
        return "informational", text[:60], True

    # Unresolved — cross-ref text doesn't match any known pattern
    return "unresolved", text[:60], True  # Not broken, just unclassified


def _extract_crossrefs_from_content(content: str) -> list[tuple[str, int]]:
    """Extract \\crossrefmargin{} arguments handling nested braces and multi-line.

    Returns list of (text, line_number) tuples.
    """
    results = []
    marker = "\\crossrefmargin{"
    start = 0
    while True:
        idx = content.find(marker, start)
        if idx < 0:
            break
        brace_start = idx + len(marker)
        depth = 1
        i = brace_start
        while i < len(content) and depth > 0:
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            text = content[brace_start : i - 1].strip()
            # Compute line number from position
            line_num = content[:idx].count("\n") + 1
            results.append((text, line_num))
        start = i
    return results


def audit_guide_crossrefs(
    guide: GuideInfo,
    repo_root: Path,
    all_slugs: set[str],
) -> GuideCrossRefMetrics | None:
    """Audit cross-references for a guide."""
    chapters_dir = guide.resolve_chapters_dir(repo_root)
    if not chapters_dir.exists():
        return None

    labels = collect_labels(chapters_dir)
    metrics = GuideCrossRefMetrics(slug=guide.slug)

    # Scan chapters + appendices
    for tex_dir in [chapters_dir, chapters_dir.parent / "appendices"]:
        if not tex_dir.exists():
            continue
        for tex_file in sorted(tex_dir.glob("*.tex")):
            try:
                content = tex_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for text, line_num in _extract_crossrefs_from_content(content):
                ref_type, target, valid = classify_crossref(
                    text, guide.slug, labels, all_slugs
                )

                ref = CrossRef(
                    guide_slug=guide.slug,
                    file_path=str(tex_file),
                    line_number=line_num,
                    text=text[:100],
                    ref_type=ref_type,
                    target=target,
                    valid=valid,
                )
                metrics.refs.append(ref)
                metrics.total_crossrefs += 1

                if ref_type == "internal":
                    metrics.internal_refs += 1
                    if not valid:
                        metrics.broken_internal.append(ref)
                elif ref_type == "external_guide":
                    metrics.external_guide_refs += 1
                elif ref_type == "external_vol":
                    metrics.external_vol_refs += 1
                elif ref_type == "informational":
                    metrics.informational_refs += 1
                else:
                    metrics.unresolved_refs += 1

    return metrics if metrics.total_crossrefs > 0 else None


# ── Reporting ────────────────────────────────────────────────────────────────


def print_report(
    all_metrics: list[GuideCrossRefMetrics],
    all_slugs: set[str],
    incoming: dict[str, set[str]],
) -> None:
    """Print human-readable cross-reference report."""
    total = sum(m.total_crossrefs for m in all_metrics)
    total_internal = sum(m.internal_refs for m in all_metrics)
    total_ext_guide = sum(m.external_guide_refs for m in all_metrics)
    total_ext_vol = sum(m.external_vol_refs for m in all_metrics)
    total_informational = sum(m.informational_refs for m in all_metrics)
    total_unresolved = sum(m.unresolved_refs for m in all_metrics)
    total_broken = sum(len(m.broken_internal) for m in all_metrics)

    print("\n" + "=" * 60)
    print("CROSS-REFERENCE QUALITY AUDIT — course_learning")
    print("=" * 60)
    print(f"\nGuides with cross-refs: {len(all_metrics)}")
    print(f"Total cross-refs:      {total}")
    print(f"  Internal (\\ref):     {total_internal}")
    print(f"  External (guide):    {total_ext_guide}")
    print(f"  External (vol):      {total_ext_vol}")
    print(f"  Informational:       {total_informational}")
    print(f"  Unclassified:        {total_unresolved}")
    print(f"  Broken internal:     {total_broken}")

    if total_broken > 0:
        print(f"\n{'=' * 60}")
        print("BROKEN INTERNAL REFS:")
        print("-" * 60)
        for m in all_metrics:
            for ref in m.broken_internal:
                fname = Path(ref.file_path).name
                print(f"  {m.slug}/{fname}:{ref.line_number}")
                print(f"    Missing label: {ref.target}")

    # Orphaned guides (no incoming cross-refs from other guides)
    guides_with_refs = {m.slug for m in all_metrics}
    all_tier1_slugs = {g.slug for g in get_tier1_guides()}
    orphaned = all_tier1_slugs - set(incoming.keys()) - {m.slug for m in all_metrics if m.total_crossrefs == 0}

    # Per-guide summary
    print(f"\n{'-' * 60}")
    print(f"{'Guide':<48} {'Out':>4} {'In':>4}")
    print("-" * 60)
    for slug in sorted(all_tier1_slugs):
        outgoing = next((m.total_crossrefs for m in all_metrics if m.slug == slug), 0)
        incoming_count = len(incoming.get(slug, set()))
        marker = " *" if slug in orphaned else ""
        print(f"  {slug:<46} {outgoing:>4} {incoming_count:>4}{marker}")

    orphan_slugs = all_tier1_slugs - set(incoming.keys())
    if orphan_slugs:
        print(f"\n* = no incoming cross-refs (orphaned guides: {len(orphan_slugs)})")

    print(f"\n{'=' * 60}")
    if total_broken == 0:
        print("PASS: No broken cross-references")
    else:
        print(f"FAIL: {total_broken} broken internal references")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit cross-reference quality")
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    repo_root = get_repo_root()
    all_slugs = {g.slug for g in get_all_guides()}

    if args.guide:
        guide = get_guide_by_slug(args.guide)
        if guide is None:
            print(f"Error: guide '{args.guide}' not found", file=sys.stderr)
            sys.exit(1)
        guides = [guide]
    else:
        guides = get_tier1_guides()

    all_metrics: list[GuideCrossRefMetrics] = []
    incoming: dict[str, set[str]] = defaultdict(set)  # target_slug -> {source_slugs}

    for guide in guides:
        result = audit_guide_crossrefs(guide, repo_root, all_slugs)
        if result:
            all_metrics.append(result)
            # Track incoming refs
            for ref in result.refs:
                if ref.ref_type == "external_guide" and ref.valid:
                    incoming[ref.target].add(guide.slug)

    if args.json:
        total = sum(m.total_crossrefs for m in all_metrics)
        output = {
            "summary": {
                "guides_with_crossrefs": len(all_metrics),
                "total_crossrefs": total,
                "broken_internal": sum(len(m.broken_internal) for m in all_metrics),
                "orphaned_guides": len({g.slug for g in get_tier1_guides()} - set(incoming.keys())),
            },
            "guides": [
                {
                    "slug": m.slug,
                    "total": m.total_crossrefs,
                    "internal": m.internal_refs,
                    "external_guide": m.external_guide_refs,
                    "external_vol": m.external_vol_refs,
                    "informational": m.informational_refs,
                    "unresolved": m.unresolved_refs,
                    "broken": [{"target": r.target, "file": Path(r.file_path).name, "line": r.line_number} for r in m.broken_internal],
                }
                for m in all_metrics
            ],
            "incoming": {slug: sorted(sources) for slug, sources in incoming.items()},
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(all_metrics, all_slugs, incoming)

    # Exit non-zero if broken refs
    total_broken = sum(len(m.broken_internal) for m in all_metrics)
    sys.exit(1 if total_broken > 0 else 0)


if __name__ == "__main__":
    main()
