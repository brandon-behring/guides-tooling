#!/usr/bin/env python3
"""Audit source provenance manifests against the schema.

Validates that a guide's `docs/review/source_manifest.md`:
  1. Exists.
  2. Has parseable YAML front-matter with required fields.
  3. Has all required body sections.
  4. Carries family-specific blocks where required (MEAP for Manning meap;
     Specialization for Coursera; Family-Not-Listed for other).
  5. References a canonical_source_path that actually exists on disk.
  6. Has a TODO density below the Silver-tier threshold (default 30%) — a
     scaffold-only manifest with most fields TODO is not a real manifest.

Per docs/standards/00_universal/tier_model.md, the source manifest is a
Silver-tier requirement; this script is the gate.

Usage:
    scripts/audit_source_manifest.py --guide manning_rlhf_book
    scripts/audit_source_manifest.py --all
    scripts/audit_source_manifest.py --all --max-todo-pct 20

Exit code: 0 if all guides pass; 1 if any fail.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from tooling import discovery, layout, paths

TEMPLATE = paths.standards_dir() / "templates" / "source_manifest.md.template"

REQUIRED_FRONTMATTER = {
    "guide_slug",
    "family",
    "canonical_source_path",
    "extraction_pipeline",
    "extraction_dates",
    "extraction_tool_versions",
}
REQUIRED_SECTIONS = {
    "Source Metadata",
    "Source Material Inventory",
    "TOC and Coverage",
    "Known Source Issues",
    "Companion Code Status",
    "Family-Specific Fields",
    "Remediation Notes",
}
VALID_FAMILIES = {"manning", "dlai", "deeplearning_ai", "coursera", "other"}

# Critical-field check (audit memo item 4). The TODO-density gate at
# line 158 normalizes by total fillable fields, so a manifest with a
# TODO `canonical_source_path` plus 30+ filled table cells passes the
# 30% threshold (e.g., dlai_ragas_docs). A short-circuit critical-field
# check fails the manifest immediately when any of these are TODO,
# regardless of overall density:
#   - canonical_source_path (front-matter)
#   - Title (body label `- **Title**:`)
#   - URL (body label `- **URL**:`)
#   - Either Source chapter count OR Page count (source)
CRITICAL_BODY_LABELS: dict[str, re.Pattern[str]] = {
    "Title": re.compile(r"^- \*\*Title\*\*:\s*(.+)$", re.MULTILINE),
    "URL": re.compile(r"^- \*\*URL\*\*:\s*(.+)$", re.MULTILINE),
}
CRITICAL_BODY_EITHER: dict[str, list[re.Pattern[str]]] = {
    "Source chapter count|Page count": [
        re.compile(r"^- \*\*Source chapter count\*\*:\s*(.+)$", re.MULTILINE),
        re.compile(r"^- \*\*Page count \(source\)\*\*:\s*(.+)$", re.MULTILINE),
    ],
}
TODO_VALUE_RE = re.compile(r"\bTODO\b", re.IGNORECASE)


def check_critical_fields(front: dict, body: str) -> list[str]:
    """Return list of critical-field failures (empty list = pass).

    Per audit memo item 4: the manifest's `canonical_source_path`,
    `Title`, `URL`, and one of `Source chapter count` / `Page count`
    must all be non-TODO non-empty values. The TODO-density gate
    treats critical fields as fungible with cosmetic ones; this gate
    short-circuits that fungibility.
    """
    failures: list[str] = []
    canonical = str(front.get("canonical_source_path", "")).strip()
    if not canonical or TODO_VALUE_RE.search(canonical):
        failures.append(
            f"canonical_source_path is TODO/missing (critical): {canonical!r}"
        )
    for label, pat in CRITICAL_BODY_LABELS.items():
        m = pat.search(body)
        if m is None:
            failures.append(f"missing '{label}' body label (critical)")
        elif TODO_VALUE_RE.search(m.group(1).strip()):
            failures.append(f"'{label}' value is TODO (critical)")
    for or_label, pats in CRITICAL_BODY_EITHER.items():
        any_real = False
        for p in pats:
            m = p.search(body)
            if m and not TODO_VALUE_RE.search(m.group(1).strip()):
                any_real = True
                break
        if not any_real:
            failures.append(f"both options under '{or_label}' missing or TODO (critical)")
    return failures


def family_of(slug: str) -> str:
    """Identify family by directory prefix."""
    if slug.startswith("manning_"):
        return "manning"
    if slug.startswith("deeplearning_ai_"):
        return "deeplearning_ai"
    if slug.startswith("dlai_"):
        return "dlai"
    if slug.startswith("coursera_"):
        return "coursera"
    return "other"


def parse_manifest(path: Path) -> tuple[dict, str]:
    """Split the manifest into YAML front-matter and Markdown body."""
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError("missing YAML front-matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("malformed YAML front-matter (no closing ---)")
    front = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5:]
    return front, body


def section_headers(body: str) -> set[str]:
    """Return set of `## SectionName` headers found in body."""
    return set(re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE))


def todo_density(text: str) -> tuple[int, int, float]:
    """Count TODO occurrences and estimate fillable-field count."""
    todo = len(re.findall(r"\bTODO\b", text))
    # Approximate fillable fields: list items plus table cells minus headers
    fillable_lines = len(re.findall(r"^- \*\*", text, re.MULTILINE))
    fillable_cells = sum(
        max(0, line.count("|") - 2)
        for line in text.splitlines()
        if line.startswith("|") and not re.match(r"^\|[\s\-|]+\|$", line)
    )
    fillable = max(1, fillable_lines + fillable_cells)
    pct = 100.0 * todo / fillable
    return todo, fillable, pct


def audit_guide(guide_dir: Path, max_todo_pct: float) -> list[str]:
    """Return list of failure reasons (empty list = pass)."""
    failures: list[str] = []
    manifest = layout.source_manifest(guide_dir)
    if not manifest.exists():
        return ["manifest missing"]

    try:
        front, body = parse_manifest(manifest)
    except (ValueError, yaml.YAMLError) as e:
        return [f"parse error: {e}"]

    # 0. Critical fields (per audit memo item 4). Short-circuits — if
    # any critical field is TODO, the manifest fails regardless of
    # overall TODO density. Runs BEFORE other checks so callers see the
    # critical failure, not a downstream noise failure.
    critical_failures = check_critical_fields(front, body)
    if critical_failures:
        return critical_failures

    # 1. Required front-matter fields
    missing_fm = REQUIRED_FRONTMATTER - set(front.keys())
    if missing_fm:
        failures.append(f"missing front-matter: {sorted(missing_fm)}")

    # 2. Family validity + slug consistency
    family = front.get("family")
    if family not in VALID_FAMILIES:
        failures.append(f"invalid family: {family!r}")
    expected_family = family_of(guide_dir.name)
    if family and family != expected_family:
        failures.append(f"family mismatch: front-matter={family} dir={expected_family}")

    declared_slug = front.get("guide_slug")
    if declared_slug != guide_dir.name:
        failures.append(f"slug mismatch: {declared_slug!r} vs {guide_dir.name!r}")

    # 3. Required body sections
    headers = section_headers(body)
    missing_sec = REQUIRED_SECTIONS - headers
    if missing_sec:
        failures.append(f"missing sections: {sorted(missing_sec)}")

    # 4. Family-specific blocks
    if family == "manning":
        # MEAP block required only when pub_status=meap (we don't know without re-reading
        # body; require the section if "meap" appears anywhere in body)
        if "meap" in body.lower() and "MEAP Status" not in headers:
            failures.append("Manning meap guide missing 'MEAP Status' section")
    if family == "coursera" and "Specialization Metadata" not in headers:
        failures.append("Coursera guide missing 'Specialization Metadata' section")
    if family == "other" and "Family-Not-Listed Exception" not in headers:
        failures.append("Other-family guide missing 'Family-Not-Listed Exception' section")

    # 5. canonical_source_path exists on disk
    canonical = front.get("canonical_source_path", "")
    if isinstance(canonical, str) and "TODO" not in canonical:
        # Path may be relative to guide_dir or paths.host_root() (e.g.
        # scripts/course_structures/...). Under the R-layout role-based layout
        # the raw source moves into source/ (top-level chapters/, transcripts/)
        # and the guide's own tree into guide/ (notes/notebook/ -> guide/), so
        # accept those remapped locations too.
        candidates = [
            guide_dir / canonical,
            paths.host_root() / canonical,
            guide_dir / "source" / canonical,
            guide_dir / canonical.replace("notes/notebook", "guide", 1),
        ]
        if not any(c.exists() for c in candidates):
            failures.append(f"canonical_source_path does not exist: {canonical}")

    # 6. TODO density below threshold
    todo, fillable, pct = todo_density(body)
    if pct > max_todo_pct:
        failures.append(f"too many TODOs: {todo}/{fillable} fields = {pct:.0f}% > {max_todo_pct}%")

    return failures


def discover_guides() -> list[Path]:
    """Discover all guide workspaces by guide_qa.yaml presence."""
    return discovery.iter_guide_dirs()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--guide", help="Workspace slug (e.g., manning_rlhf_book)")
    parser.add_argument("--all", action="store_true", help="Audit every guide")
    parser.add_argument("--max-todo-pct", type=float, default=30.0,
                        help="Max TODO density (%%) before manifest is a stub (default: 30)")
    parser.add_argument("--missing-ok", action="store_true",
                        help="Treat missing manifests as PASS (Silver-tier aspirational)")
    args = parser.parse_args()

    if not args.guide and not args.all:
        parser.error("--guide <slug> or --all is required")

    if args.all:
        guides = discover_guides()
    else:
        target = paths.host_root() / args.guide
        if not target.is_dir():
            print(f"Workspace not found: {target}", file=sys.stderr)
            return 1
        guides = [target]

    pass_count = fail_count = missing_count = 0
    for guide in guides:
        failures = audit_guide(guide, args.max_todo_pct)
        if not failures:
            pass_count += 1
            print(f"  PASS    {guide.name}")
        elif failures == ["manifest missing"] and args.missing_ok:
            missing_count += 1
            print(f"  MISSING {guide.name}")
        else:
            fail_count += 1
            print(f"  FAIL    {guide.name}")
            for f in failures:
                print(f"          - {f}")

    print(f"\nResults: {pass_count} PASS, {fail_count} FAIL, {missing_count} MISSING")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
