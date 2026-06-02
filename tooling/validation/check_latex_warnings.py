#!/usr/bin/env python3
r"""
Check LaTeX log for presentation-quality warnings.

Validates:
- Overfull \hbox warnings >= 50pt (visually impactful overflows)
- tcolorbox overflow warnings
- Undefined citations and references

Skips (counted but not gated):
- Overfull <= 3pt (invisible to human eye, ~0.04in)
- Marginpar moved (Tufte-inherent margin note shifting)
- Underfull \hbox (Tufte-inherent empty hbox in margin environments)

Usage:
    python check_latex_warnings.py pytorch_notebook_guide.log
    python check_latex_warnings.py build.log --json --threshold-red 3
"""

import argparse
import json
import re
import sys
from typing import NamedTuple


class WarningResult(NamedTuple):
    """A warning found in the LaTeX log."""
    file: str
    line: int
    source: str
    category: str
    detail: str


# ── Patterns ───────────────────────────────────────────────────────────────
OVERFULL_RE = re.compile(r"Overfull \\hbox.*?(\d+\.?\d*)pt too wide")
TCOLORBOX_RE = re.compile(r"upper box part has become overfull")
UNDEF_CITATION_RE = re.compile(r"Citation.*undefined", re.IGNORECASE)
UNDEF_REF_RE = re.compile(r"Reference.*undefined", re.IGNORECASE)
MARGINPAR_RE = re.compile(r"Marginpar.*moved")
UNDERFULL_RE = re.compile(r"Underfull \\hbox")
AUTHORED_SOURCE_RE = re.compile(
    r"(?:\./)?(?:chapters|appendices|shared)/[^()\s]+\.(?:tex|sty)|"
    r"(?:\./)?notebook-extensions\.sty"
)
GENERATED_SOURCE_RE = re.compile(r"(?:\./)?([^()\s]+\.(ind|toc))")


def normalize_source(raw_source: str) -> str:
    """Normalize authored and generated LaTeX inputs into stable source labels."""
    source = raw_source.removeprefix("./")
    if source.endswith(".ind"):
        return "generated:index"
    if source.endswith(".toc"):
        return "generated:toc"
    return source


def parse_log(logfile: str) -> dict[str, list[WarningResult]]:
    """Parse LaTeX log and categorize warnings.

    Returns dict mapping category name to list of WarningResult.
    """
    results: dict[str, list[WarningResult]] = {
        "overfull_50pt": [],
        "overfull_10_49pt": [],
        "overfull_le3pt": [],
        "tcolorbox": [],
        "undef_citations": [],
        "undef_references": [],
        "marginpar": [],
        "underfull": [],
    }

    current_source = logfile
    with open(logfile, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            generated_sources = GENERATED_SOURCE_RE.findall(line)
            if generated_sources:
                current_source = normalize_source(generated_sources[-1][0])

            authored_sources = AUTHORED_SOURCE_RE.findall(line)
            if authored_sources:
                current_source = normalize_source(authored_sources[-1])

            m = OVERFULL_RE.search(line)
            if m:
                pt = float(m.group(1))
                if pt >= 50:
                    results["overfull_50pt"].append(
                        WarningResult(logfile, line_num, current_source, "overfull_50pt", line.strip())
                    )
                elif pt >= 10:
                    results["overfull_10_49pt"].append(
                        WarningResult(logfile, line_num, current_source, "overfull_10_49pt", line.strip())
                    )
                elif pt <= 3:
                    results["overfull_le3pt"].append(
                        WarningResult(logfile, line_num, current_source, "overfull_le3pt", line.strip())
                    )
                # 3 < pt < 10 falls into 10-49 bucket implicitly? No — gap.
                # Actually 3 < pt < 10 is minor, track with 10-49 for simplicity.
                else:
                    results["overfull_10_49pt"].append(
                        WarningResult(logfile, line_num, current_source, "overfull_10_49pt", line.strip())
                    )
                continue

            if TCOLORBOX_RE.search(line):
                results["tcolorbox"].append(
                    WarningResult(logfile, line_num, current_source, "tcolorbox", line.strip())
                )
                continue

            if UNDEF_CITATION_RE.search(line):
                results["undef_citations"].append(
                    WarningResult(logfile, line_num, current_source, "undef_citations", line.strip())
                )
                continue

            if UNDEF_REF_RE.search(line):
                results["undef_references"].append(
                    WarningResult(logfile, line_num, current_source, "undef_references", line.strip())
                )
                continue

            if MARGINPAR_RE.search(line):
                results["marginpar"].append(
                    WarningResult(logfile, line_num, current_source, "marginpar", line.strip())
                )
                continue

            if UNDERFULL_RE.search(line):
                results["underfull"].append(
                    WarningResult(logfile, line_num, current_source, "underfull", line.strip())
                )

    return results


def check_gates(results: dict[str, list[WarningResult]], threshold_red: int) -> bool:
    """Return True if all gates pass, False if any RED threshold exceeded."""
    if len(results["overfull_50pt"]) > threshold_red:
        return False
    if len(results["undef_citations"]) > 0:
        return False
    if len(results["undef_references"]) > 0:
        return False
    return True


def print_summary(results: dict[str, list[WarningResult]], threshold_red: int) -> None:
    """Print human-readable summary table."""
    divider = "\u2550" * 60
    n50 = len(results["overfull_50pt"])
    n10 = len(results["overfull_10_49pt"])
    ntcb = len(results["tcolorbox"])
    ncit = len(results["undef_citations"])
    nref = len(results["undef_references"])
    nle3 = len(results["overfull_le3pt"])
    nmar = len(results["marginpar"])
    nund = len(results["underfull"])

    ok = "\u2705"
    fail = "\u274c"

    print(f"\nLaTeX Presentation Check\n{divider}")
    print(f"  Overfull >=50pt:      {n50:>3}  (threshold: {threshold_red})   {ok if n50 <= threshold_red else fail}")
    print(f"  Overfull 10-49pt:     {n10:>3}  (info)")
    print(f"  tcolorbox overflow:   {ntcb:>3}  (info)")
    print(f"  Undefined citations:  {ncit:>3}  (threshold: 0)   {ok if ncit == 0 else fail}")
    print(f"  Undefined references: {nref:>3}  (threshold: 0)   {ok if nref == 0 else fail}")
    print(f"  [skipped: {nle3} <=3pt, {nmar} marginpar, {nund} underfull]")
    print()

    if check_gates(results, threshold_red):
        print(f"  {ok} Presentation check passed!")
    else:
        print(f"  {fail} Presentation check FAILED!")


def print_verbose(results: dict[str, list[WarningResult]]) -> None:
    """Print individual warning locations for gated categories."""
    for cat in ("overfull_50pt", "undef_citations", "undef_references"):
        warnings = results[cat]
        if warnings:
            print(f"\n  {cat} ({len(warnings)}):")
            for w in warnings:
                print(f"    {w.source}:L{w.line}: {w.detail[:120]}")


def summarize_by_source(results: dict[str, list[WarningResult]]) -> dict[str, dict[str, int]]:
    """Aggregate warning counts by current LaTeX source file."""
    summary: dict[str, dict[str, int]] = {}
    for category, warnings in results.items():
        for warning in warnings:
            source_counts = summary.setdefault(warning.source, {})
            source_counts[category] = source_counts.get(category, 0) + 1
    return summary


def print_by_source(results: dict[str, list[WarningResult]]) -> None:
    """Print a compact per-source warning summary."""
    summary = summarize_by_source(results)
    if not summary:
        return

    def weight(counts: dict[str, int]) -> tuple[int, int, int, int, int]:
        return (
            counts.get("overfull_50pt", 0) + counts.get("undef_citations", 0) + counts.get("undef_references", 0),
            counts.get("overfull_10_49pt", 0),
            counts.get("tcolorbox", 0),
            counts.get("overfull_le3pt", 0),
            counts.get("underfull", 0),
        )

    print("\nPer-source summary")
    print("Source | >=50pt | 10-49pt | tcolorbox | <=3pt | underfull")
    print("-" * 72)
    for source, counts in sorted(summary.items(), key=lambda item: weight(item[1]), reverse=True):
        print(
            f"{source} | "
            f"{counts.get('overfull_50pt', 0):>6} | "
            f"{counts.get('overfull_10_49pt', 0):>7} | "
            f"{counts.get('tcolorbox', 0):>9} | "
            f"{counts.get('overfull_le3pt', 0):>5} | "
            f"{counts.get('underfull', 0):>9}"
        )


def print_json(results: dict[str, list[WarningResult]]) -> None:
    """Print machine-readable JSON output."""
    data = {
        "overfull_50pt": len(results["overfull_50pt"]),
        "overfull_10_49pt": len(results["overfull_10_49pt"]),
        "tcolorbox": len(results["tcolorbox"]),
        "undef_citations": len(results["undef_citations"]),
        "undef_references": len(results["undef_references"]),
        "skipped_le3pt": len(results["overfull_le3pt"]),
        "skipped_marginpar": len(results["marginpar"]),
        "skipped_underfull": len(results["underfull"]),
    }
    print(json.dumps(data))


def print_json_by_source(results: dict[str, list[WarningResult]]) -> None:
    """Print machine-readable JSON output including by-source attribution."""
    data = {
        "totals": {
            "overfull_50pt": len(results["overfull_50pt"]),
            "overfull_10_49pt": len(results["overfull_10_49pt"]),
            "tcolorbox": len(results["tcolorbox"]),
            "undef_citations": len(results["undef_citations"]),
            "undef_references": len(results["undef_references"]),
            "skipped_le3pt": len(results["overfull_le3pt"]),
            "skipped_marginpar": len(results["marginpar"]),
            "skipped_underfull": len(results["underfull"]),
        },
        "by_source": summarize_by_source(results),
    }
    print(json.dumps(data))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check LaTeX log for presentation-quality warnings"
    )
    parser.add_argument("logfile", help="Path to LaTeX .log file")
    parser.add_argument(
        "--threshold-red", type=int, default=5,
        help="Fail if overfull >=50pt count exceeds N (default: 5)"
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--by-file", action="store_true", help="Report warning attribution by source file")
    parser.add_argument("--verbose", action="store_true", help="Show individual warning locations")

    args = parser.parse_args()

    results = parse_log(args.logfile)

    if args.json:
        if args.by_file:
            print_json_by_source(results)
        else:
            print_json(results)
    else:
        print_summary(results, args.threshold_red)
        if args.by_file:
            print_by_source(results)
        if args.verbose:
            print_verbose(results)

    return 0 if check_gates(results, args.threshold_red) else 1


if __name__ == "__main__":
    sys.exit(main())
