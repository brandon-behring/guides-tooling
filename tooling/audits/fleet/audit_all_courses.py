#!/usr/bin/env python3
"""audit_all_courses.py -- Run the Bronze structural checklist + Silver gate across all courses.

Discovers courses by looking for guide_qa.yaml files.
Produces a markdown fleet audit report.

Bronze gate: the ``BRONZE_CHECKS`` structural checklist (10 checks as of gt#33;
    scoring out of ``BRONZE_TOTAL``; all GREEN = Bronze). Check 10, "Stub-free
    includes", reads ``guide/main.tex`` and RED-flags any ``\\input``/``\\include``
    target that is missing, unreadable, empty, or a TODO/TBD/FIXME/PLACEHOLDER
    body -- the class that shipped 87 ``TODO`` appendix chapters into delivered
    PDFs while every tier gate stayed green (gold-wave review 2026-08-27, A1).
Silver gate: PASS requires Bronze BRONZE_TOTAL/BRONZE_TOTAL AND all four content gates per
    docs/standards/00_universal/tier_model.md:29 ("Silver = Bronze plus..."):
      1. Source manifest (audit_source_manifest.py, <30% TODO density)
      2. Real Appendix D (>=5 interview questions + role/level mapping, or
         an explicit Out-of-Interview-Scope Waiver / Aggregator Waiver)
      3. Real interview_connections.md (four canonical sections)
      4. Non-stub dashboard (real qa-health metrics)
    Delegates the 4-gate content check to scripts/audit_silver.py
    so this script agrees with the authoritative Silver roster. A guide
    that fails Bronze (green<BRONZE_TOTAL) is reported as Silver FAIL regardless of
    content gates, because Silver builds on Bronze.

Usage:
    python scripts/audit_all_courses.py              # Full audit
    python scripts/audit_all_courses.py --summary     # Summary table only
    python scripts/audit_all_courses.py --tier silver # Only guides not at Silver PASS
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from tooling import discovery, layout, paths

REPORTS_DIR = paths.host_root() / "reports"
EXCLUDE_DIRS = {
    "shared", "scripts", "_archived", ".git", ".claude", "docs", "reports",
    "templates",
    # Non-guide artifacts (curriculum / reading-list documents, not course guides):
    "manning_curriculum",
}

# Silver audit helpers
from tooling._fail_loud import read_text_or_warn, warn_audit_error
from tooling.audits.fleet.audit_source_manifest import audit_guide as audit_silver_guide
from tooling.audits.fleet.audit_silver import audit_guide as audit_silver_honest_guide
from tooling.validation._latex import strip_latex_comments

SILVER_MAX_TODO_PCT = 30.0

# Standard Bloom's levels (gold standard)
STANDARD_LEVELS = {
    "define", "explain", "calculate", "compare", "analyze",
    "evaluate", "design", "apply", "debug", "trace",
}


def discover_courses() -> list[Path]:
    """Find all guide directories (recursive; handles topic-nested layouts).

    Delegates to the centralized recursive walk and drops known non-guide dirs
    (curriculum / reading-list folders) by basename.
    """
    return [g for g in discovery.iter_guide_dirs() if g.name not in EXCLUDE_DIRS]


def check_guide_qa(course: Path) -> tuple[str, str]:
    """Check 1: guide_qa.yaml exists and has required sections."""
    qa_file = course / "guide_qa.yaml"
    if not qa_file.exists():
        return "RED", "missing"
    content = qa_file.read_text()
    missing = []
    for section in ["guide:", "los:", "metrics:", "readiness_checks:"]:
        if section not in content:
            missing.append(section.rstrip(":"))
    if missing:
        return "YELLOW", f"missing sections: {', '.join(missing)}"
    return "GREEN", "present with all sections"


def check_validation_symlinks(course: Path) -> tuple[str, str]:
    """Check 2: the tooling submodule provides the validation modules.

    New-contract replacement for per-guide ``scripts/validation/`` symlinks:
    QA now runs as ``python -m tooling.validation.*`` via the included tooling
    Makefile, so guides no longer carry symlinks into a ``shared/`` tree. We
    instead verify the modules ship in the mounted ``tooling/`` package.
    (Falls back to per-guide symlinks so an un-migrated monorepo guide still
    scores.)
    """
    expected = ["check_refs.py", "check_duplicates.py", "extract_los.py", "check_latex_warnings.py"]
    pkg_validation = Path(paths.__file__).resolve().parent / "validation"
    missing = [n for n in expected if not (pkg_validation / n).exists()]
    if not missing:
        return "GREEN", "tooling provides validation (python -m tooling.validation.*)"
    # Legacy fallback: per-guide symlinks (pre-carve monorepo layout).
    val_dir = course / "scripts" / "validation"
    found = sum(1 for n in expected if (val_dir / n).is_symlink() or (val_dir / n).exists())
    if found == 4:
        return "GREEN", "4/4 legacy symlinks"
    return "RED", f"tooling missing: {', '.join(missing)}"


def check_makefile_qa(course: Path) -> tuple[str, str]:
    """Check 3: the guide Makefile wires in the tooling QA/card targets.

    New contract: the guide ``include``s the tooling Makefile, which supplies
    qa-refs/qa-los/qa-presentation/qa-health/qa-ready/cards/decks. Accept the
    include OR inline targets (so an un-migrated monorepo guide still scores).
    """
    makefile = layout.makefile(course)
    if not makefile.exists():
        return "RED", "Makefile missing"
    content = makefile.read_text()
    if "include $(TOOLING)" in content:
        return "GREEN", "includes tooling Makefile"
    targets = ["qa-health", "qa-refs", "qa-los", "qa-cards", "qa-presentation"]
    found = [t for t in targets if f"{t}:" in content]
    if len(found) == len(targets):
        return "GREEN", f"{len(found)}/{len(targets)} inline targets"
    if len(found) > 0:
        return "YELLOW", f"{len(found)}/{len(targets)} inline targets"
    return "RED", "no qa targets or tooling include"


def check_extensions_sty(course: Path) -> tuple[str, str]:
    """Check 4: *-extensions.sty or notebook-extensions.sty exists."""
    nb_dir = layout.guide_root(course)
    sty_files = list(nb_dir.glob("*-extensions.sty")) + list(nb_dir.glob("*extensions.sty"))
    # Deduplicate (glob patterns can overlap)
    sty_files = list({f.resolve(): f for f in sty_files}.values())
    if not sty_files:
        return "RED", "missing"
    content = sty_files[0].read_text()
    if "\\interviewmargin" in content and "\\formulamargin" in content:
        return "GREEN", f"present with macros ({sty_files[0].name})"
    return "YELLOW", f"present but missing some macros ({sty_files[0].name})"


def check_cards(course: Path) -> tuple[str, str]:
    """Check 5: cards/all_cards.yml exists."""
    cards = layout.cards_yaml(course)
    if not cards.exists():
        return "RED", "missing"
    if cards.stat().st_size < 100:
        return "YELLOW", "exists but very small"
    return "GREEN", "present"


def check_deck(course: Path) -> tuple[str, str]:
    """Check 6: decks/*.apkg exists."""
    decks_dir = layout.decks_dir(course)
    if not decks_dir.exists():
        return "RED", "missing"
    apkg_files = list(decks_dir.glob("*.apkg"))
    if not apkg_files:
        return "RED", "no .apkg files"
    return "GREEN", f"{len(apkg_files)} deck(s)"


def check_dashboard(course: Path) -> tuple[str, str]:
    """Check 7: docs/review/dashboard.md exists."""
    dashboard = layout.dashboard(course)
    if not dashboard.exists():
        return "RED", "missing"
    return "GREEN", "present"


def check_bloom_levels(course: Path) -> tuple[str, str]:
    """Check 8: Bloom's levels use standard set."""
    import yaml

    qa_file = course / "guide_qa.yaml"
    if not qa_file.exists():
        return "RED", "no guide_qa.yaml"
    try:
        with open(qa_file) as f:
            config = yaml.safe_load(f)
        levels = set(config.get("los", {}).get("valid_levels", []))
    except Exception as exc:  # noqa: BLE001 — a malformed guide_qa.yaml is a real
        # defect, not a shrug: fail the check loudly (RED row AND stderr record)
        warn_audit_error("audit_all_courses.check_bloom_levels", qa_file, exc)
        return "RED", f"guide_qa.yaml parse error: {type(exc).__name__}"
    count = len(levels)
    if count <= 12:
        return "GREEN", f"{count} levels"
    if count <= 20:
        extra = levels - STANDARD_LEVELS
        return "YELLOW", f"{count} levels (+{', '.join(sorted(extra))})"
    extra = levels - STANDARD_LEVELS
    return "RED", f"{count} levels (+{', '.join(sorted(extra))})"


def check_hardcoded_paths(course: Path) -> tuple[str, str]:
    """Check 9: No non-portable paths in the Makefile OR guide_qa.yaml check commands.

    Extended beyond the Makefile to also scan ``guide_qa.yaml`` (the import-era
    drift lived in its ``check_cmd``/``cmd`` strings, not the Makefile):
      * ``~/Claude/...`` absolute paths (sibling-repo dependency)
      * ``mdls`` page_count WITHOUT a ``pdfinfo`` primary (Spotlight-only, breaks
        on fresh PDFs); the canonical ``pdfinfo``→``mdls`` fallback is allowed
      * local ``scripts/validation/*.py`` (missing symlink; use
        ``python -m tooling.validation.*``)
    """
    problems: list[str] = []
    makefile = layout.makefile(course)
    if makefile.exists():
        content = makefile.read_text()
        if "~/Claude/" in content or os.path.expanduser("~") + "/Claude/" in content:
            m = re.findall(r"~/Claude/\S+", content)
            problems.append(f"Makefile {m[0] if m else '~/Claude'}")
    qa = course / "guide_qa.yaml"
    if qa.exists():
        qa_text = qa.read_text()
        if "~/Claude/" in qa_text:
            problems.append("guide_qa.yaml ~/Claude path")
        if "mdls" in qa_text and "pdfinfo" not in qa_text:
            problems.append("guide_qa.yaml mdls page_count (no pdfinfo)")
        if re.search(r"scripts/validation/\w+\.py", qa_text):
            problems.append("guide_qa.yaml scripts/validation path")
    if problems:
        return "RED", "; ".join(problems[:3])
    return "GREEN", "clean"


# Check 10 -- stub-free includes (gt#33 row 3 / gold-wave review 2026-08-27 A1).
INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
# Lines that are document *structure*, not body: a file consisting only of these
# (plus blank lines / comments) has no content. \begin{learningoutcomes}, \los{},
# \section prose etc. all count as content, so an LOS-only chapter is NOT a stub.
_STRUCTURAL_LINE_RE = re.compile(
    r"^\s*\\(?:chapter|section|subsection|subsubsection|label)\*?\s*[\[{]"
)
# The body's first content line announces a placeholder.
_STUB_BODY_RE = re.compile(r"^\s*(?:TODO|TBD|FIXME|PLACEHOLDER)\b", re.IGNORECASE)
_MAX_LISTED_PROBLEMS = 3


def classify_include_body(text: str) -> str | None:
    """Classify the body of an ``\\input``-ed file: ``"empty"``, ``"stub"``, or ``None``.

    Comments are stripped first (``strip_latex_comments``), then blank lines and
    structural lines (``\\chapter`` / ``\\section`` / ``\\label`` ...) are dropped. No
    line left => ``"empty"``; first remaining line starting with TODO / TBD / FIXME /
    PLACEHOLDER => ``"stub"``; anything else is real content (``None``).

    >>> classify_include_body("\\\\chapter{Quick Reference}\\n\\\\label{app:qr}\\nTODO: add tables\\n")
    'stub'
    >>> classify_include_body("\\\\chapter{X}\\n\\\\begin{learningoutcomes}\\n\\\\end{learningoutcomes}\\n")
    """
    lines = [ln for ln in strip_latex_comments(text).splitlines() if ln.strip()]
    content = [ln for ln in lines if not _STRUCTURAL_LINE_RE.match(ln)]
    if not content:
        return "empty"
    if _STUB_BODY_RE.match(content[0]):
        return "stub"
    return None


def check_main_includes(course: Path) -> tuple[str, str]:
    """Check 10: every ``\\input``/``\\include`` in ``guide/main.tex`` resolves to real content.

    Targets are resolved relative to ``guide/`` (where LaTeX runs); ``.tex`` is
    appended when absent. Commented-out includes (the gm#93 ``% \\input{...}``
    un-input form) are ignored. RED lists the first ``_MAX_LISTED_PROBLEMS``
    offenders as ``missing: X`` / ``unreadable: X`` / ``empty: X`` / ``TODO body: X``.
    """
    main = layout.guide_root(course) / "main.tex"
    if not main.exists():
        return "RED", "guide/main.tex missing"
    text = read_text_or_warn("audit_all_courses.check_main_includes", main)
    if text is None:
        return "RED", "guide/main.tex unreadable"
    problems: list[str] = []
    resolved = 0
    for target in INCLUDE_RE.findall(strip_latex_comments(text)):
        rel = target.strip()
        if not rel.endswith(".tex"):
            rel += ".tex"
        resolved += 1
        path = main.parent / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
            continue
        body = read_text_or_warn("audit_all_courses.check_main_includes", path)
        if body is None:
            problems.append(f"unreadable: {rel}")
            continue
        kind = classify_include_body(body)
        if kind == "empty":
            problems.append(f"empty: {rel}")
        elif kind == "stub":
            problems.append(f"TODO body: {rel}")
    if problems:
        shown = "; ".join(problems[:_MAX_LISTED_PROBLEMS])
        extra = f" (+{len(problems) - _MAX_LISTED_PROBLEMS} more)" if len(problems) > _MAX_LISTED_PROBLEMS else ""
        return "RED", f"{len(problems)} include(s): {shown}{extra}"
    return "GREEN", f"{resolved} includes resolved, stub-free"


# The Bronze checklist, in report order. BRONZE_TOTAL is the single denominator
# every score / docstring / summary derives from (gt#33: adding check 10 must not
# leave a stale literal behind).
BRONZE_CHECKS: list[tuple[str, "callable"]] = [
    ("guide_qa.yaml", check_guide_qa),
    ("Validation tooling", check_validation_symlinks),
    ("Makefile QA targets", check_makefile_qa),
    ("notebook-extensions.sty", check_extensions_sty),
    ("Cards extracted", check_cards),
    ("Anki deck", check_deck),
    ("Dashboard", check_dashboard),
    ("Bloom's levels", check_bloom_levels),
    ("No hardcoded paths", check_hardcoded_paths),
    ("Stub-free includes", check_main_includes),
]
BRONZE_TOTAL = len(BRONZE_CHECKS)


def check_silver(course: Path, bronze_green: int) -> tuple[str, str]:
    """Silver gate: Bronze BRONZE_TOTAL/BRONZE_TOTAL precondition + four content gates.

    Per docs/standards/00_universal/tier_model.md:29, "Silver = Bronze plus...".
    This function delegates the four content gates (manifest, App-D, IC.md,
    dashboard) to scripts/audit_silver.py so the fleet-level auditor
    agrees with the authoritative Silver roster.

    Parameters
    ----------
    course : Path
        Absolute path to the guide workspace (contains guide_qa.yaml).
    bronze_green : int
        Number of Bronze checks at GREEN (out of BRONZE_TOTAL). Silver requires all.

    Returns
    -------
    tuple[str, str]
        (status, detail) where status is one of:
        - "PASS": Bronze all-GREEN AND all four Silver content gates pass
        - "FAIL": Bronze below all-GREEN OR one-or-more Silver content gates fail
        - "MISSING": manifest is missing (special case of FAIL, kept for
                     backwards-compatible report filtering)
    """
    full = f"{BRONZE_TOTAL}/{BRONZE_TOTAL}"
    if bronze_green < BRONZE_TOTAL:
        return "FAIL", f"bronze {bronze_green}/{BRONZE_TOTAL} (Silver requires {full})"
    # Bronze all-GREEN -- check the four content gates via the authoritative auditor.
    honest = audit_silver_honest_guide(course)
    gates = honest["gates"]
    if honest["silver_pass"]:
        return "PASS", f"bronze {full} + all four content gates"
    # At least one content gate failed; surface the first-failing reason.
    if not gates["Manifest"]["pass"]:
        if gates["Manifest"]["reason"] == "manifest_missing":
            return "MISSING", "no source_manifest.md"
        return "FAIL", f"manifest: {gates['Manifest']['reason']}"
    failing = [name for name in ("App-D", "IC.md", "Dashboard") if not gates[name]["pass"]]
    reasons = [f"{name}: {gates[name]['reason']}" for name in failing]
    summary = "; ".join(reasons[:2])
    if len(reasons) > 2:
        summary += f" (+{len(reasons) - 2} more)"
    return "FAIL", summary


def audit_course(course: Path) -> dict:
    """Run the Bronze checklist (``BRONZE_CHECKS``) + Silver gate on one course.

    Parameters
    ----------
    course : Path
        Absolute path to the guide workspace (contains guide_qa.yaml).

    Returns
    -------
    dict
        Keys: "course" (slug), "checks" (list of Bronze check results),
        "green" / "yellow" / "red" (Bronze status counts out of BRONZE_TOTAL),
        "silver" (dict with "status" in {PASS, FAIL, MISSING} and "detail").
    """
    results = []
    for name, fn in BRONZE_CHECKS:
        status, detail = fn(course)
        results.append({"name": name, "status": status, "detail": detail})
    green = sum(1 for r in results if r["status"] == "GREEN")
    silver_status, silver_detail = check_silver(course, green)
    return {
        "course": course.name,
        "checks": results,
        "green": green,
        "yellow": sum(1 for r in results if r["status"] == "YELLOW"),
        "red": sum(1 for r in results if r["status"] == "RED"),
        "silver": {"status": silver_status, "detail": silver_detail},
    }


def format_report(audits: list[dict]) -> str:
    """Generate markdown fleet audit report with Bronze + Silver columns."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# QA Fleet Audit Report",
        f"",
        f"Generated: {now}",
        f"Courses audited: {len(audits)}",
        f"",
        "## Summary Table",
        "",
        f"Bronze score = {BRONZE_TOTAL}-point structural checklist "
        f"(G/Y/R counts + N/{BRONZE_TOTAL} score).",
        f"Silver = Bronze {BRONZE_TOTAL}/{BRONZE_TOTAL} + four content gates "
        "(manifest, App-D, IC.md, dashboard); delegates to scripts/audit_silver.py.",
        "",
        "| Course | G | Y | R | Bronze | Silver |",
        "|--------|---|---|---|--------|--------|",
    ]

    fully_compliant = 0
    silver_pass = silver_fail = silver_missing = 0
    for a in sorted(audits, key=lambda x: (-x["green"], x["silver"]["status"] != "PASS", x["course"])):
        score = f"{a['green']}/{BRONZE_TOTAL}"
        silver = a["silver"]["status"]
        lines.append(
            f"| {a['course']} | {a['green']} | {a['yellow']} | {a['red']} | {score} | {silver} |"
        )
        if a["green"] == BRONZE_TOTAL:
            fully_compliant += 1
        if silver == "PASS":
            silver_pass += 1
        elif silver == "FAIL":
            silver_fail += 1
        else:
            silver_missing += 1

    lines.extend([
        "",
        f"## Fleet Health",
        f"",
        f"### Bronze ({BRONZE_TOTAL}-point structural checklist)",
        f"",
        f"- **Fully compliant ({BRONZE_TOTAL}/{BRONZE_TOTAL})**: {fully_compliant}/{len(audits)}",
        f"- **Partial (4-{BRONZE_TOTAL - 1}/{BRONZE_TOTAL})**: "
        f"{sum(1 for a in audits if 4 <= a['green'] < BRONZE_TOTAL)}/{len(audits)}",
        f"- **Minimal (0-3/{BRONZE_TOTAL})**: {sum(1 for a in audits if a['green'] < 4)}/{len(audits)}",
        f"",
        f"### Silver (Bronze {BRONZE_TOTAL}/{BRONZE_TOTAL} + four content gates)",
        f"",
        f"- **PASS**: {silver_pass}/{len(audits)}",
        f"- **FAIL**: {silver_fail}/{len(audits)}",
        f"- **MISSING**: {silver_missing}/{len(audits)}",
        "",
    ])

    # Component-level breakdown
    check_names = [c["name"] for c in audits[0]["checks"]] if audits else []
    lines.extend(["## Component Coverage", "", "| Component | GREEN | % |", "|-----------|-------|---|"])
    for i, name in enumerate(check_names):
        green_count = sum(1 for a in audits if a["checks"][i]["status"] == "GREEN")
        pct = f"{green_count / len(audits) * 100:.0f}%" if audits else "0%"
        lines.append(f"| {name} | {green_count}/{len(audits)} | {pct} |")

    # RED items detail (Bronze)
    lines.extend(["", "## RED Items (Action Required)", ""])
    for a in sorted(audits, key=lambda x: x["course"]):
        reds = [c for c in a["checks"] if c["status"] == "RED"]
        if reds:
            lines.append(f"### {a['course']}")
            for r in reds:
                lines.append(f"- **{r['name']}**: {r['detail']}")
            lines.append("")

    # Silver FAIL detail (separate from Bronze RED)
    silver_fails = [a for a in audits if a["silver"]["status"] == "FAIL"]
    if silver_fails:
        lines.extend(["", "## Silver FAIL Items (Manifest Review Required)", ""])
        for a in sorted(silver_fails, key=lambda x: x["course"]):
            lines.append(f"### {a['course']}")
            lines.append(f"- **source_manifest.md**: {a['silver']['detail']}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point. See module docstring for full Bronze/Silver semantics."""
    parser = argparse.ArgumentParser(description="Audit QA infrastructure across all courses")
    parser.add_argument("--summary", action="store_true", help="Summary table only")
    parser.add_argument(
        "--tier",
        choices=["bronze", "silver", "all"],
        default="all",
        help=(
            "Filter output: 'bronze' hides Silver-only failures; "
            "'silver' shows only guides failing the Silver gate; 'all' shows everything."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=f"exit non-zero if any guide is below Bronze {BRONZE_TOTAL}/{BRONZE_TOTAL} "
             "(CI gate; ignores Silver)",
    )
    args = parser.parse_args()

    courses = discover_courses()
    if not courses:
        print("No courses found with guide_qa.yaml")
        return

    print(f"Auditing {len(courses)} courses...")
    audits = [audit_course(c) for c in courses]

    report = format_report(audits)

    # Save report
    REPORTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    report_path = REPORTS_DIR / f"qa_fleet_audit_{date_str}.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")

    # Print summary
    fully_compliant = sum(1 for a in audits if a["green"] == BRONZE_TOTAL)
    silver_pass = sum(1 for a in audits if a["silver"]["status"] == "PASS")
    print(
        f"\nFleet: Bronze {fully_compliant}/{len(audits)} ({BRONZE_TOTAL}/{BRONZE_TOTAL}); "
        f"Silver {silver_pass}/{len(audits)} (PASS)"
    )

    if args.tier == "silver":
        # Show only guides NOT at Silver PASS
        not_pass = [a for a in audits if a["silver"]["status"] != "PASS"]
        print(f"\n{len(not_pass)} guides not at Silver PASS:")
        for a in sorted(not_pass, key=lambda x: (x["silver"]["status"], x["course"])):
            print(f"  {a['silver']['status']:<8} {a['course']}: {a['silver']['detail']}")
        return

    if args.summary:
        for line in report.split("\n"):
            if line.startswith("|") or line.startswith("##"):
                print(line)
    else:
        print(report)

    if args.strict:
        failing = [a["course"] for a in audits if a["green"] < BRONZE_TOTAL]
        if failing:
            print(
                f"\nSTRICT: {len(failing)} guide(s) below Bronze {BRONZE_TOTAL}/{BRONZE_TOTAL}: "
                f"{', '.join(sorted(failing))}",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
