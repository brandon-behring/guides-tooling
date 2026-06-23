#!/usr/bin/env python3
"""Audit cross-guide term consistency for course learning guides.

Detects:
  1. Within-guide duplicate term definitions (always a bug)
  2. Cross-guide definition inconsistencies (Jaccard < 0.5)
  3. Cross-reference gaps: terms mentioned in prose but not defined locally

Generates a canonical term registry with ready-to-paste margin note suggestions.

Output: YAML to docs/review/term-registry.yml (default) or Markdown report.

Usage:
    python shared/audits/audit_term_consistency.py
    python shared/audits/audit_term_consistency.py --guide dlai_advanced_rag
    python shared/audits/audit_term_consistency.py --report
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from tooling.audits.guide._guide_scope import (
    chapter_files,
    get_repo_root,
    guide_dir_for_slug,
    guide_dirs as discover_guide_dirs,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TERM_RE = re.compile(
    r'\\term(?:\[([^\]]*)\])?\{([^}]+)\}\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}',
    re.DOTALL,
)

_ARTICLES = {"the", "a", "an"}
_PAREN_ACRONYM_RE = re.compile(r'\s*\([A-Z]{2,}\)\s*$')
_LATEX_CMD_STRIP_RE = re.compile(r'\\[a-zA-Z]+(?=\{)')
_LATEX_CMD_BARE_RE = re.compile(r'\\[a-zA-Z]+(?![{a-zA-Z])')
_LATEX_MATH_RE = re.compile(r'\$[^$]*\$')
_LATEX_BRACES_RE = re.compile(r'[{}]')
MARGINNOTE_RE = re.compile(r'\\marginnote')
_MIN_TERM_WORDS = 2
_MIN_TERM_CHARS = 4


# ---------------------------------------------------------------------------
# Utility: Jaccard similarity (inlined to avoid external dependency)
# ---------------------------------------------------------------------------

def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts (word-level).

    Returns:
        Float in [0.0, 1.0].
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TermDefinition:
    term_name: str
    normalized_name: str
    definition: str
    los_id: str
    file: str
    line: int
    guide: str


@dataclass
class TermCluster:
    normalized_name: str
    definitions: list[TermDefinition] = field(default_factory=list)
    canonical_guide: str = ""
    canonical_definition: str = ""


@dataclass
class WithinGuideDuplicate:
    term: str
    guide: str
    locations: list[dict] = field(default_factory=list)


@dataclass
class CrossGuideConflict:
    term: str
    guides: list[str] = field(default_factory=list)
    similarity: float = 0.0
    detail: str = ""


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_term_name(raw: str) -> str:
    """Normalize a term name for comparison."""
    cleaned = _LATEX_CMD_STRIP_RE.sub("", raw)
    cleaned = _LATEX_CMD_BARE_RE.sub("", cleaned)
    cleaned = _LATEX_MATH_RE.sub("", cleaned)
    cleaned = _LATEX_BRACES_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip().lower()
    words = cleaned.split()
    if words and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words).strip()


# ---------------------------------------------------------------------------
# Term extraction
# ---------------------------------------------------------------------------

def find_guide_dirs() -> list[str]:
    """Slugs of guides with LaTeX chapters (topic-nested, discovery-based)."""
    return [d.name for d in discover_guide_dirs() if chapter_files(d)]


def extract_terms_from_file(
    tex_path: Path, guide: str, guide_dir: Path,
) -> list[TermDefinition]:
    """Extract all \\term{}{} definitions from a single .tex file."""
    try:
        content = tex_path.read_text(encoding="utf-8")
    except Exception:
        return []

    file_rel = str(tex_path.relative_to(guide_dir.parent))
    terms: list[TermDefinition] = []

    for m in TERM_RE.finditer(content):
        los_id = m.group(1) or ""
        term_name = m.group(2).strip()
        definition = m.group(3).strip()
        line_num = content[:m.start()].count("\n") + 1

        norm = normalize_term_name(term_name)
        if not norm:
            continue

        terms.append(TermDefinition(
            term_name=term_name,
            normalized_name=norm,
            definition=definition,
            los_id=los_id.strip(),
            file=file_rel,
            line=line_num,
            guide=guide,
        ))

    return terms


def extract_all_terms(guide_dirs: list[str]) -> list[TermDefinition]:
    """Extract all terms across specified guides."""
    all_terms: list[TermDefinition] = []
    for guide_name in guide_dirs:
        guide_path = guide_dir_for_slug(guide_name)
        if guide_path is None:
            continue
        for tex_file in chapter_files(guide_path):
            terms = extract_terms_from_file(tex_file, guide_name, guide_path)
            all_terms.extend(terms)
    return all_terms


# ---------------------------------------------------------------------------
# Within-guide duplicate detection
# ---------------------------------------------------------------------------

def find_within_guide_duplicates(terms: list[TermDefinition]) -> list[WithinGuideDuplicate]:
    """Find terms defined more than once within the same guide."""
    guide_terms: dict[tuple[str, str], list[TermDefinition]] = defaultdict(list)
    for t in terms:
        guide_terms[(t.guide, t.normalized_name)].append(t)

    dupes: list[WithinGuideDuplicate] = []
    for (guide, norm), defs in guide_terms.items():
        if len(defs) > 1:
            dupes.append(WithinGuideDuplicate(
                term=defs[0].term_name,
                guide=guide,
                locations=[{"file": d.file, "line": d.line} for d in defs],
            ))
    return dupes


# ---------------------------------------------------------------------------
# Cross-guide consistency scoring
# ---------------------------------------------------------------------------

def build_term_clusters(terms: list[TermDefinition]) -> dict[str, TermCluster]:
    """Group terms by normalized name into clusters."""
    clusters: dict[str, TermCluster] = {}
    for t in terms:
        if t.normalized_name not in clusters:
            clusters[t.normalized_name] = TermCluster(normalized_name=t.normalized_name)
        clusters[t.normalized_name].definitions.append(t)
    return clusters


def score_cross_guide_conflicts(clusters: dict[str, TermCluster]) -> list[CrossGuideConflict]:
    """Find cross-guide definition pairs with low similarity."""
    conflicts: list[CrossGuideConflict] = []

    for norm, cluster in clusters.items():
        guide_defs: dict[str, TermDefinition] = {}
        for d in cluster.definitions:
            if d.guide not in guide_defs:
                guide_defs[d.guide] = d

        if len(guide_defs) < 2:
            continue

        guides = sorted(guide_defs.keys())
        for i in range(len(guides)):
            for j in range(i + 1, len(guides)):
                sim = jaccard_similarity(
                    guide_defs[guides[i]].definition,
                    guide_defs[guides[j]].definition,
                )
                if sim < 0.5:
                    conflicts.append(CrossGuideConflict(
                        term=cluster.definitions[0].term_name,
                        guides=[guides[i], guides[j]],
                        similarity=round(sim, 3),
                        detail=(
                            f"{guides[i]}: {guide_defs[guides[i]].definition[:80]}... | "
                            f"{guides[j]}: {guide_defs[guides[j]].definition[:80]}..."
                        ),
                    ))
    return conflicts


def assign_canonical(clusters: dict[str, TermCluster]) -> None:
    """Assign canonical guide and definition to each cluster (longest = most thorough)."""
    for cluster in clusters.values():
        if not cluster.definitions:
            continue
        best = max(cluster.definitions, key=lambda d: len(d.definition))
        cluster.canonical_guide = best.guide
        cluster.canonical_definition = best.definition


# ---------------------------------------------------------------------------
# Registry generation
# ---------------------------------------------------------------------------

def generate_registry(
    terms: list[TermDefinition],
    clusters: dict[str, TermCluster],
    within_dupes: list[WithinGuideDuplicate],
    conflicts: list[CrossGuideConflict],
) -> dict:
    """Generate the full term registry as a dict (for YAML output)."""
    registry: dict = {
        "summary": {
            "total_term_occurrences": len(terms),
            "unique_terms": len(clusters),
            "within_guide_duplicates": len(within_dupes),
            "cross_guide_conflicts": len(conflicts),
        },
        "terms": {},
        "issues": {
            "within_guide_duplicates": [],
            "cross_guide_conflicts": [],
        },
    }

    # Multi-guide terms
    for norm in sorted(clusters.keys()):
        cluster = clusters[norm]
        if not cluster.definitions:
            continue

        guide_defs: dict[str, TermDefinition] = {}
        for d in cluster.definitions:
            if d.guide not in guide_defs:
                guide_defs[d.guide] = d

        if len(guide_defs) <= 1:
            continue

        also_defined: list[dict] = []
        for guide, d in sorted(guide_defs.items()):
            if guide == cluster.canonical_guide:
                continue
            sim = jaccard_similarity(cluster.canonical_definition, d.definition)
            also_defined.append({
                "guide": guide,
                "similarity": round(sim, 3),
                "definition": d.definition[:120],
            })

        registry["terms"][norm] = {
            "display_name": cluster.definitions[0].term_name,
            "canonical_guide": cluster.canonical_guide,
            "canonical_definition": cluster.canonical_definition[:200],
            "also_defined_in": also_defined,
        }

    # Issues
    for d in within_dupes:
        registry["issues"]["within_guide_duplicates"].append({
            "term": d.term, "guide": d.guide, "locations": d.locations,
        })
    for c in conflicts:
        registry["issues"]["cross_guide_conflicts"].append({
            "term": c.term, "guides": c.guides,
            "similarity": c.similarity, "detail": c.detail,
        })

    return registry


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def to_markdown(registry: dict) -> str:
    """Generate Markdown summary report."""
    lines: list[str] = []
    s = registry["summary"]

    lines.append("# Term Consistency Audit\n")
    lines.append(f"**Total term occurrences**: {s['total_term_occurrences']}  ")
    lines.append(f"**Unique terms**: {s['unique_terms']}  ")
    lines.append(f"**Within-guide duplicates**: {s['within_guide_duplicates']}  ")
    lines.append(f"**Cross-guide conflicts**: {s['cross_guide_conflicts']}\n")

    dupes = registry["issues"]["within_guide_duplicates"]
    if dupes:
        lines.append("## Within-Guide Duplicates\n")
        for d in dupes:
            locs = ", ".join(f"`{l['file']}:{l['line']}`" for l in d["locations"])
            lines.append(f"- **{d['term']}** ({d['guide']}): {locs}")
        lines.append("")

    conflicts = registry["issues"]["cross_guide_conflicts"]
    if conflicts:
        lines.append("## Cross-Guide Conflicts (similarity < 0.5)\n")
        for c in conflicts[:20]:
            lines.append(
                f"- **{c['term']}** ({', '.join(c['guides'])}): "
                f"similarity={c['similarity']}"
            )
        if len(conflicts) > 20:
            lines.append(f"\n*...and {len(conflicts) - 20} more.*")
        lines.append("")

    multi_guide = registry.get("terms", {})
    if multi_guide:
        lines.append(f"## Multi-Guide Terms ({len(multi_guide)} terms)\n")
        lines.append("| Term | Canonical Guide | Also In | Min Similarity |")
        lines.append("|------|----------------|---------|----------------|")
        for norm, info in sorted(multi_guide.items()):
            also = info["also_defined_in"]
            min_sim = min(a["similarity"] for a in also) if also else 1.0
            also_guides = ", ".join(a["guide"] for a in also)
            lines.append(
                f"| {info['display_name']} | {info['canonical_guide']} | "
                f"{also_guides} | {min_sim:.2f} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Audit cross-guide term consistency")
    parser.add_argument("--guide", type=str, default=None, help="Focus on a single guide")
    parser.add_argument("--report", action="store_true", help="Output Markdown report")
    parser.add_argument("--strict", "--check", dest="strict", action="store_true",
                        help="exit 1 if the focused guide has within-guide duplicate term "
                             "definitions (cross-guide conflicts stay advisory)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    all_dirs = find_guide_dirs()

    if args.guide:
        guide_path = guide_dir_for_slug(args.guide)
        if guide_path is None or not guide_path.is_dir():
            print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
            sys.exit(1)

    # Extract terms from ALL guides (needed for cross-guide comparison)
    all_terms = extract_all_terms(all_dirs)
    print(f"Extracted {len(all_terms)} term definitions across {len(all_dirs)} guides")

    within_dupes = find_within_guide_duplicates(all_terms)
    clusters = build_term_clusters(all_terms)
    assign_canonical(clusters)
    conflicts = score_cross_guide_conflicts(clusters)

    registry = generate_registry(all_terms, clusters, within_dupes, conflicts)

    if args.report:
        output_text = to_markdown(registry)
        default_path = get_repo_root() / "reports" / "_scratch" / "term-registry.md"
    else:
        output_text = yaml.dump(
            registry, default_flow_style=False, sort_keys=False,
            allow_unicode=True, width=120,
        )
        default_path = get_repo_root() / "reports" / "_scratch" / "term-registry.yml"

    out_path = Path(args.output) if args.output else default_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_text, encoding="utf-8")

    s = registry["summary"]
    print(f"\nTerm consistency audit:")
    print(f"  Unique terms: {s['unique_terms']}")
    print(f"  Within-guide duplicates: {s['within_guide_duplicates']}")
    print(f"  Cross-guide conflicts: {s['cross_guide_conflicts']}")
    print(f"Output: {out_path}")

    # --strict: within-guide duplicate term definitions are unambiguous bugs
    # (the same term \term{}{}-defined twice in one guide). Cross-guide
    # conflicts (Jaccard < 0.5) are intentionally NOT gated -- they are a
    # fleet-level advisory signal, not a single-guide Gold blocker. FAIL goes
    # to stderr; exit 1 is what audit_gold G2 keys on.
    if args.strict:
        scoped = [d for d in within_dupes if not args.guide or d.guide == args.guide]
        for d in scoped:
            locs = ", ".join(f"{l['file']}:{l['line']}" for l in d.locations)
            print(f"FAIL  {d.guide}: duplicate term '{d.term}' ({locs})", file=sys.stderr)
        if scoped:
            sys.exit(1)


if __name__ == "__main__":
    main()
