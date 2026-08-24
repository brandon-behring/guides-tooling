#!/usr/bin/env python3
"""
Audit content freshness across course_learning LaTeX guides.

Detects deprecated model references, stale API names, and outdated framework
versions. Uses deprecated-only rules (not "old but valid" educational content).

Adapted from interview_prep_series for course_learning guide layout.
Uses guide_scope.py for guide discovery.

Usage:
    python shared/audits/audit_content_freshness.py                  # All Tier 1
    python shared/audits/audit_content_freshness.py --guide dlai_advanced_rag
    python shared/audits/audit_content_freshness.py --json
    python shared/audits/audit_content_freshness.py --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

# ── Guide discovery ──────────────────────────────────────────────────────────

from tooling._fail_loud import warn_audit_error
from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_repo_root,
    get_tier1_guides,
    get_guide_by_slug,
)

# ── Velocity classification ──────────────────────────────────────────────────
# HIGH: LLM APIs, agents, MCP — content stales in months
# MEDIUM: RAG, search, fine-tuning — stales in ~6 months
# LOW: fundamentals (PyTorch, NLP, graph ML, RL) — stales in ~12 months

# Velocity is read per-guide from the ``gold.velocity`` key in guide_qa.yaml
# (fast | medium | slow — the Gold G7 SLA), else a topic-shelf default. This
# audit's vocabulary is HIGH/MEDIUM/LOW: fast→HIGH, medium→MEDIUM, slow→LOW.
_FAST_SHELVES = {
    "ai-agents", "ai-engineering-and-llm-apps", "llms-and-transformers",
    "rag-and-search", "evaluation-alignment-safety",
}
_SLOW_SHELVES = {
    "ml-and-data-foundations", "reinforcement-learning",
    "software-engineering-and-python",
}
# Everything else defaults to medium.

# Staleness windows per the Gold G7 SLA (fast / medium / slow), in months.
HIGH_VELOCITY_MONTHS = 6
MEDIUM_VELOCITY_MONTHS = 12
LOW_VELOCITY_MONTHS = 18


# ── Staleness rules ──────────────────────────────────────────────────────────
# Deprecated-only: only flags models/APIs that are genuinely retired or removed.
# Does NOT flag old-but-valid educational content (e.g., GPT-2 for teaching attention).


@dataclass
class StalenessRule:
    """A regex-based rule for detecting stale content."""

    pattern: str
    category: str
    severity: str  # HIGH, MEDIUM, LOW
    description: str
    compiled: re.Pattern = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.compiled = re.compile(self.pattern, re.IGNORECASE)


RULES: list[StalenessRule] = [
    # --- Deprecated models: HIGH severity ---
    StalenessRule(
        pattern=r"text-davinci-003",
        category="Deprecated Model",
        severity="HIGH",
        description="text-davinci-003 removed from OpenAI API",
    ),
    StalenessRule(
        pattern=r"gpt-3\.5-turbo\b",
        category="Deprecated Model",
        severity="HIGH",
        description="gpt-3.5-turbo superseded by gpt-4o-mini",
    ),
    StalenessRule(
        pattern=r"gpt-4-turbo\b",
        category="Deprecated Model",
        severity="HIGH",
        description="gpt-4-turbo superseded by gpt-4o",
    ),
    StalenessRule(
        pattern=r"text-embedding-ada-002",
        category="Deprecated Model",
        severity="HIGH",
        description="text-embedding-ada-002 replaced by text-embedding-3-large",
    ),
    StalenessRule(
        pattern=r"claude-3-(?:sonnet|haiku|opus)\b",
        category="Deprecated Model",
        severity="HIGH",
        description="Claude 3 family replaced by Claude 4.x",
    ),
    StalenessRule(
        pattern=r"claude[\s-]3[\s.-]5[\s-]?(?:sonnet|haiku|opus)",
        category="Deprecated Model",
        severity="HIGH",
        description="Claude 3.5 family replaced by Claude 4.x",
    ),
    StalenessRule(
        pattern=r"claude-3-5-sonnet-\d{8}",
        category="Deprecated Model",
        severity="HIGH",
        description="Claude 3.5 Sonnet snapshot IDs are obsolete",
    ),
    StalenessRule(
        pattern=r"[Gg]emini[\s-]1\.5",
        category="Deprecated Model",
        severity="HIGH",
        description="Gemini 1.5 superseded by Gemini 2.x",
    ),
    StalenessRule(
        pattern=r"[Ll]lama[\s-]2\b",
        category="Deprecated Model",
        severity="HIGH",
        description="Llama 2 superseded by Llama 3.x",
    ),
    # --- Deprecated APIs: HIGH severity ---
    StalenessRule(
        pattern=r"openai\.ChatCompletion\.create",
        category="Deprecated API",
        severity="HIGH",
        description="openai.ChatCompletion.create replaced by client.chat.completions.create (v1.0+)",
    ),
    StalenessRule(
        pattern=r"openai\.Embedding\.create",
        category="Deprecated API",
        severity="HIGH",
        description="openai.Embedding.create replaced by client.embeddings.create (v1.0+)",
    ),
    # --- Old framework versions: MEDIUM severity ---
    StalenessRule(
        pattern=r"langchain[<>=]=?\s*0\.[012]\.",
        category="Old Framework",
        severity="MEDIUM",
        description="LangChain pre-0.3 is outdated",
    ),
    StalenessRule(
        pattern=r"llama.index[<>=]=?\s*0\.[0-9]\.",
        category="Old Framework",
        severity="MEDIUM",
        description="LlamaIndex pre-0.10 has breaking API changes",
    ),
    # --- Stale pricing: MEDIUM severity ---
    StalenessRule(
        pattern=r"claude.*?haiku.*?\$?0\.25.*?\$?1\.25",
        category="Stale Pricing",
        severity="MEDIUM",
        description="Claude Haiku pricing ($0.25/$1.25) is outdated — Haiku 4 is $0.80/$4",
    ),
]


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class Finding:
    """A single stale content finding."""

    file_path: str
    line_number: int
    line_text: str
    category: str
    severity: str
    description: str


@dataclass
class GuideFreshness:
    """Freshness metrics for a guide."""

    slug: str
    velocity: str = "LOW"
    chapter_count: int = 0
    total_findings: int = 0
    high_findings: int = 0
    medium_findings: int = 0
    findings: list[Finding] = field(default_factory=list)


# ── Core logic ───────────────────────────────────────────────────────────────


def get_velocity(guide) -> str:
    """Velocity for a guide: the ``gold.velocity`` key in its guide_qa.yaml
    (fast|medium|slow), else a topic-shelf default. Mapped to this audit's
    HIGH/MEDIUM/LOW vocabulary (fast→HIGH, medium→MEDIUM, slow→LOW)."""
    gd = guide.guide_dir()
    vel = None
    if gd is not None:
        qa = gd / "guide_qa.yaml"
        if qa.exists():
            try:
                data = yaml.safe_load(qa.read_text(encoding="utf-8")) or {}
                vel = (data.get("gold") or {}).get("velocity")
            except Exception as exc:  # noqa: BLE001 — fall back to the shelf
                # default, but visibly
                warn_audit_error("audit_content_freshness.velocity", qa, exc)
                vel = None
        shelf = gd.parent.name
        shelf_default = "fast" if shelf in _FAST_SHELVES else "slow" if shelf in _SLOW_SHELVES else "medium"
        if str(vel).lower() not in {"fast", "medium", "slow"}:
            vel = shelf_default  # missing or unrecognized gold.velocity → shelf default
    return {"fast": "HIGH", "medium": "MEDIUM", "slow": "LOW"}.get(str(vel).lower(), "MEDIUM")


def scan_file(tex_path: Path, guide_slug: str) -> list[Finding]:
    """Scan a single .tex file for stale content."""
    findings: list[Finding] = []
    try:
        content = tex_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — an unread file must not read as "fresh"
        warn_audit_error("audit_content_freshness.scan_file", tex_path, exc)
        return findings
    lines = content.split("\n")

    for rule in RULES:
        for line_num, line_text in enumerate(lines, start=1):
            stripped = line_text.lstrip()
            if stripped.startswith("%"):
                continue
            # Skip warning margin notes that intentionally name deprecated models
            if r"\warningmargin{" in line_text:
                continue
            # Skip lines annotated as accepted deprecations
            if "% freshness-ok" in line_text:
                continue
            if rule.compiled.search(line_text):
                findings.append(Finding(
                    file_path=str(tex_path),
                    line_number=line_num,
                    line_text=line_text.strip()[:120],
                    category=rule.category,
                    severity=rule.severity,
                    description=rule.description,
                ))

    return findings


def audit_guide_freshness(guide: GuideInfo, repo_root: Path) -> Optional[GuideFreshness]:
    """Audit freshness of a single guide."""
    chapters_dir = guide.resolve_chapters_dir(repo_root)
    if not chapters_dir.exists():
        return None

    metrics = GuideFreshness(slug=guide.slug, velocity=get_velocity(guide))

    # Scan chapters/ and appendices/
    notebook_dir = chapters_dir.parent  # <slug>/guide/
    for tex_dir in [chapters_dir, notebook_dir / "appendices"]:
        if not tex_dir.exists():
            continue
        for tex_file in sorted(tex_dir.glob("*.tex")):
            if tex_file.stem.startswith("_"):
                continue
            metrics.chapter_count += 1
            file_findings = scan_file(tex_file, guide.slug)
            metrics.findings.extend(file_findings)

    metrics.total_findings = len(metrics.findings)
    metrics.high_findings = sum(1 for f in metrics.findings if f.severity == "HIGH")
    metrics.medium_findings = sum(1 for f in metrics.findings if f.severity == "MEDIUM")

    return metrics


# ── Reporting ────────────────────────────────────────────────────────────────


def print_report(all_metrics: list[GuideFreshness]) -> None:
    """Print human-readable freshness report."""
    total_findings = sum(m.total_findings for m in all_metrics)
    total_high = sum(m.high_findings for m in all_metrics)
    total_medium = sum(m.medium_findings for m in all_metrics)
    affected = sum(1 for m in all_metrics if m.total_findings > 0)

    print("\n" + "=" * 60)
    print("CONTENT FRESHNESS AUDIT — course_learning")
    print("=" * 60)
    print(f"\nGuides scanned:       {len(all_metrics)}")
    print(f"Guides with findings: {affected}")
    print(f"Total findings:       {total_findings}")
    print(f"  HIGH severity:      {total_high}")
    print(f"  MEDIUM severity:    {total_medium}")

    if any(m.total_findings > 0 for m in all_metrics):
        print("\n" + "-" * 60)
        print(f"{'Guide':<50} {'Vel':>4} {'HIGH':>5} {'MED':>5}")
        print("-" * 60)
        for m in sorted(all_metrics, key=lambda x: -x.high_findings):
            if m.total_findings > 0:
                print(f"  {m.slug:<48} {m.velocity:>4} {m.high_findings:>5} {m.medium_findings:>5}")

    # Detail HIGH findings
    high_findings = [(m.slug, f) for m in all_metrics for f in m.findings if f.severity == "HIGH"]
    if high_findings:
        print(f"\n{'=' * 60}")
        print(f"HIGH SEVERITY FINDINGS ({len(high_findings)}):")
        print("-" * 60)
        for slug, f in high_findings:
            fname = Path(f.file_path).name
            print(f"  {slug}/{fname}:{f.line_number}")
            print(f"    {f.category}: {f.description}")
            if f.line_text:
                print(f"    > {f.line_text[:100]}")

    print(f"\n{'=' * 60}")
    if total_high == 0 and total_medium == 0:
        print("PASS: No deprecated or stale content found")
    elif total_high == 0:
        print(f"WARN: {total_medium} MEDIUM findings (no HIGH)")
    else:
        print(f"FAIL: {total_high} HIGH severity findings need attention")
    print("=" * 60 + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit content freshness across course_learning guides"
    )
    parser.add_argument("--guide", "-g", help="Audit specific guide by slug")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if HIGH findings")
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

    all_metrics: list[GuideFreshness] = []
    for guide in guides:
        result = audit_guide_freshness(guide, repo_root)
        if result:
            all_metrics.append(result)

    if not all_metrics:
        print("No guides found.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        total_findings = sum(m.total_findings for m in all_metrics)
        total_high = sum(m.high_findings for m in all_metrics)
        output = {
            "generated": datetime.now().isoformat(),
            "summary": {
                "guides_scanned": len(all_metrics),
                "total_findings": total_findings,
                "high_findings": total_high,
                "medium_findings": sum(m.medium_findings for m in all_metrics),
            },
            "guides": [
                {
                    "slug": m.slug,
                    "velocity": m.velocity,
                    "chapters": m.chapter_count,
                    "findings": m.total_findings,
                    "high": m.high_findings,
                    "medium": m.medium_findings,
                    "details": [
                        {
                            "file": Path(f.file_path).name,
                            "line": f.line_number,
                            "category": f.category,
                            "severity": f.severity,
                            "description": f.description,
                            "text": f.line_text,
                        }
                        for f in m.findings
                    ],
                }
                for m in all_metrics
                if m.total_findings > 0
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(all_metrics)

    if args.strict:
        total_high = sum(m.high_findings for m in all_metrics)
        if total_high > 0:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
