#!/usr/bin/env python3
"""Advisory fleet audit: flag run-on lists that should be proper LaTeX lists.

`tooling/standards/card_standards.md` (Formatting anti-patterns) forbids run-on
numbered lists, run-on bullets, and inline section headers — parallel items
crammed into a paragraph as ``(1)~... (2)~... (3)~...`` or
``\\textbf{Case for:} ... \\textbf{Critique:} ...`` instead of an ``itemize`` /
``enumerate`` / ``description`` environment. These read as dense paragraphs in
the PDF and extract as blob card backs.

This scans every guide's chapter + appendix .tex and reports, per guide, how
many paragraphs look like inline run-on lists. It is **advisory only** (always
exits 0) — it surfaces the debt fleet-wide so it can be prioritized; it never
gates Bronze/Silver. A paragraph that already contains ``\\item`` (i.e. a real
list, or a list body) is skipped to avoid flagging well-formed content.

Usage:
    PYTHONPATH=tooling python3 -m tooling.audits.fleet.audit_runon_lists
"""
from __future__ import annotations

import datetime as _dt
import re
import sys

from tooling import discovery, paths

# Inline numbered/lettered enumerations: "(1)~" / "(2) " etc. Two-or-more in one
# paragraph (with no \item) is a run-on list.
NUM = re.compile(r"\([1-9]\)[~ ]")
LET = re.compile(r"\([a-e]\)[~ ]")
# Inline section-header labels: \textbf{Case for:} \textbf{Critique:} — two in
# one paragraph (with no \item) is the "inline section headers" anti-pattern.
HDR = re.compile(r"\\textbf\{[^}]*:\s*\}")

# Exercise/prompt environments where inline enumerations are legitimate (a
# problem statement listing steps, a vignette's sub-questions) — exclude them
# to keep the advisory count focused on real list-formatting debt.
EXCLUDE_ENV = re.compile(
    r"\\begin\{(problembox|problem|vignette|solution|redflag)\}.*?\\end\{\1\}",
    re.DOTALL,
)


def scan_text(text: str) -> int:
    text = EXCLUDE_ENV.sub(" ", text)
    flagged = 0
    for para in re.split(r"\n\s*\n", text):
        if "\\item" in para:
            continue  # a real list (or list body) — well-formed, skip
        if len(NUM.findall(para)) >= 2 or len(LET.findall(para)) >= 2:
            flagged += 1
        elif len(HDR.findall(para)) >= 2:
            flagged += 1
    return flagged


def guide_tex_files(guide_dir):
    files = []
    for sub in ("chapters", "appendices"):
        files += sorted((guide_dir / "guide" / sub).glob("*.tex"))
    return files


def main() -> int:
    rows: list[tuple[str, int]] = []
    for g in discovery.iter_guide_dirs():
        total = 0
        for f in guide_tex_files(g):
            try:
                total += scan_text(f.read_text(errors="replace"))
            except OSError:
                continue
        rows.append((g.name, total))
    rows.sort(key=lambda r: (-r[1], r[0]))

    grand = sum(n for _, n in rows)
    offenders = [r for r in rows if r[1] > 0]
    today = _dt.date.today().isoformat()

    lines = [
        f"# Run-on List Audit (advisory) — {today}",
        "",
        "Flags inline run-on lists (`(1)…(2)…`, `(a)…(b)…`) and inline section-header",
        "pairs (`\\textbf{X:} … \\textbf{Y:}`) that should be `itemize`/`enumerate`/",
        "`description` per `tooling/standards/card_standards.md`. **Advisory only** — it",
        "does not gate Bronze/Silver. Paragraphs already using `\\item` are skipped.",
        "",
        f"**Total flagged paragraphs: {grand} across {len(offenders)}/{len(rows)} guides.**",
        "",
        "| Guide | Flagged |",
        "|-------|--------:|",
    ]
    lines += [f"| {name} | {n} |" for name, n in offenders]
    report = paths.host_root() / "reports" / f"runon_lists_{today.replace('-', '')}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")

    print(f"Run-on list audit (advisory): {grand} flagged across "
          f"{len(offenders)}/{len(rows)} guides. Report: {report}")
    for name, n in offenders[:20]:
        print(f"  {n:>4}  {name}")
    return 0  # advisory: never fail


if __name__ == "__main__":
    sys.exit(main())
