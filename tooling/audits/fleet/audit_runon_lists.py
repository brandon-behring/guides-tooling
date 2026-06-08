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

# Inline numbered/lettered enumerations: "(1)~" / "(2) " etc. Three-or-more in
# one paragraph (with no \item) is a run-on list. The conversion policy converts
# 3+ inline items to a real list and deliberately leaves 2-item enumerations as
# prose (a "(1) X (2) Y" sentence contrast), so the audit threshold matches: 3+.
NUM = re.compile(r"\([1-9]\)[~ ]")
LET = re.compile(r"\([a-e]\)[~ ]")
# Inline section-header labels: \textbf{Case for:} \textbf{Critique:} — two in
# one paragraph (with no \item) is the "inline section headers" anti-pattern.
HDR = re.compile(r"\\textbf\{[^}]*:\s*\}")
# ...but the styled boxes have their OWN field labels (a keyconcept's Core
# Insight / Why It Matters / When It Breaks, a worked Answer/Approach, a gotcha's
# Symptom/Cause/Fix). Those are the box's structure, not an inline run-on, so
# they are subtracted from the HDR count before the threshold test.
STRUCT_HDR = re.compile(
    r"\\textbf\{\s*(?:Core Insight|Why It Matters|When It Breaks|Decision Rule"
    r"|Symptom|Cause|Root causes?|Fix|Diagnosis|Diagnostic|Input|Output|Target"
    r"|Answer|Approach|Key Insight)\s*:\s*\}"
)

# Structured / prompt environments where inline enumerations and label runs are
# legitimate, not run-on-list debt: problem/vignette/solution/redflag prompts; a
# `debugbox` gotcha card (Symptom/Cause/Fix labels, each line-led); a `drill`
# prompt; an `interviewcontext` spoken-answer script. Excluded so the advisory
# count stays focused on real chapter-prose list-formatting debt.
EXCLUDE_ENV = re.compile(
    r"\\begin\{(problembox|problem|vignette|solution|redflag|debugbox|drill"
    r"|interviewcontext)\}.*?\\end\{\1\}",
    re.DOTALL,
)
# The same structured cards are sometimes authored as a styled tcolorbox
# (`\begin{tcolorbox}[debugbox, ...]` / `[conceptbox, ...]`) rather than a named
# environment — exclude those spans too.
EXCLUDE_TCB = re.compile(
    r"\\begin\{tcolorbox\}\[[^]]*?(?:debugbox|conceptbox)[^]]*\]"
    r".*?\\end\{tcolorbox\}",
    re.DOTALL,
)


def scan_text(text: str) -> int:
    text = EXCLUDE_TCB.sub(" ", EXCLUDE_ENV.sub(" ", text))
    flagged = 0
    for para in re.split(r"\n\s*\n", text):
        if "\\item" in para:
            continue  # a real list (or list body) — well-formed, skip
        if "\\term[" in para:
            continue  # a glossary/term definition — a compact dictionary entry,
            # not a chapter run-on paragraph (its inline enumeration stays prose)
        if len(NUM.findall(para)) >= 3 or len(LET.findall(para)) >= 3:
            flagged += 1
        elif len(HDR.findall(para)) - len(STRUCT_HDR.findall(para)) >= 2:
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
        "Flags inline run-on lists (3+ `(1)…(2)…(3)…`, `(a)…(b)…(c)…`) and inline",
        "section-header pairs (`\\textbf{X:} … \\textbf{Y:}`) that should be `itemize`/",
        "`enumerate`/`description` per `tooling/standards/card_standards.md`. **Advisory",
        "only** — it does not gate Bronze/Silver. Skipped (legitimate, not debt):",
        "paragraphs with `\\item` (real lists), `\\term[...]` glossary definitions, and",
        "`problem`/`vignette`/`solution`/`redflag`/`debugbox`/`drill`/`interviewcontext`",
        "environments (structured cards & prompts where inline enumeration is intended).",
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
