#!/usr/bin/env python3
r"""Audit chapter content for generator residue: cloned margins and absent retrieval.

``audit_margin_quality`` tests only two of ``content_design.md``'s seven margin
conditions mechanically -- **category-tagged** and **density** -- plus a list of
seven banned phrases (``GENERIC_PATTERNS``). It has **no non-redundancy check at
all**, so a guide whose every margin note is pasted verbatim into all of its
chapters scores clean. Measured 2026-08-26, that is not hypothetical::

    manning_graph_algorithms_data_science   60/60  = 100% duplicated  (FAIL)
    manning_gnn_in_action                   40/40  = 100%             (FAIL)
    manning_algorithms_data_structures      55/61  =  90%             (GOLD)
    manning_grokking_bayes                  35/42  =  83%             (GOLD)

Two of the four are **live Gold**. ``manning_algorithms_data_structures`` pastes a
Bloom-filter false-positive-rate ``\formulamargin`` into the margin of all eleven
chapters, including *external-memory sorting* and *approximate quantiles* -- a note
that is not merely redundant but wrong for the chapter it sits in.

The second signal is coarser and catches the same generator from the other side: a
chapter set with **zero** ``\begin{problem}`` and **zero** ``\begin{vignette}``
anywhere. Fifteen guides are in that state; they typically carry one generated
sentence of narrative per chapter (e.g. *"This chapter covers the key concepts of
graph attention networks, building on the graph foundations established in earlier
chapters."*, repeated across all 8 chapters of ``manning_gnn_in_action``). Such a
guide can still pass Bronze 9/9, Silver, and -- once E/F and a G5 doc are authored
over the top of it -- Gold, because no gate reads the chapter bodies for substance.

**Advisory by default** (warning-first rollout, as ``audit_checkpoint_originality``
did): the non-``--strict`` output never starts with ``FAIL``, so registering this in
``audit_gold``'s ``GUIDE_AUDITS`` flagless cannot change any guide's tier. Flip to
``--strict`` only after the remediation sweep, or currently-Gold guides demote while
others are being promoted.

Usage::

    python -m tooling.audits.guide.audit_content_substance --guide <slug> [--json]
    python -m tooling.audits.guide.audit_content_substance --fleet
    python -m tooling.audits.guide.audit_content_substance --guide <slug> --strict
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tooling.audits.guide._guide_scope import (
    chapter_files,
    guide_dir_for_slug,
    guide_dirs,
)

# A margin payload repeated verbatim in >= MIN_CLONES places is generator residue,
# not authorship. 2 is deliberate: the same note in two chapters already breaks
# content_design.md condition 2 (adds info NOT in the adjacent paragraph) for
# whichever chapter it fits less well.
MIN_CLONES = 2

# Share of a guide's margin INSTANCES that may be verbatim repeats before the guide
# is flagged. 0.30 sits well above the hand-authored fleet (measured: the guides
# with genuine per-chapter margins score 0%) and well below the generator cohort
# (62-100%).
MAX_DUP_RATE = 0.30

# content_design.md / quality_targets.md put problems at 15+ per guide and vignettes
# at 3+ where applicable. This audit only asserts the far weaker claim that a study
# guide has SOME retrieval practice: zero of both is a shell.
MIN_RETRIEVAL_ARTIFACTS = 1

MARGIN_RE = re.compile(
    r"\\(?:interview|pattern|formula|warning|practice|crossref|exam)margin\{(.+?)\}\s*$",
    re.M,
)
PROBLEM_RE = re.compile(r"\\begin\{problem\}")
VIGNETTE_RE = re.compile(r"\\begin\{vignette\}")


@dataclass
class Clone:
    text: str
    count: int
    files: list[str] = field(default_factory=list)


@dataclass
class Substance:
    slug: str
    chapters: int
    margins: int
    duplicated: int
    dup_rate: float
    clones: list[Clone]
    problems: int
    vignettes: int

    @property
    def retrieval_artifacts(self) -> int:
        return self.problems + self.vignettes

    @property
    def margins_flagged(self) -> bool:
        return self.margins > 0 and self.dup_rate > MAX_DUP_RATE

    @property
    def retrieval_flagged(self) -> bool:
        return self.chapters > 0 and self.retrieval_artifacts < MIN_RETRIEVAL_ARTIFACTS

    @property
    def flagged(self) -> bool:
        return self.margins_flagged or self.retrieval_flagged


def measure(guide_dir: Path) -> Substance:
    """Measure one guide's chapter bodies. Never raises on unreadable files."""
    chapters = chapter_files(guide_dir)
    payloads: dict[str, list[str]] = defaultdict(list)
    total_margins = problems = vignettes = 0

    for ch in chapters:
        try:
            text = ch.read_text(errors="replace")
        except OSError:
            continue
        problems += len(PROBLEM_RE.findall(text))
        vignettes += len(VIGNETTE_RE.findall(text))
        for payload in MARGIN_RE.findall(text):
            key = " ".join(payload.split())
            payloads[key].append(ch.name)
            total_margins += 1

    clones = [
        Clone(text=k, count=len(v), files=sorted(set(v)))
        for k, v in payloads.items()
        if len(v) >= MIN_CLONES
    ]
    clones.sort(key=lambda c: -c.count)
    duplicated = sum(c.count for c in clones)
    rate = duplicated / total_margins if total_margins else 0.0

    return Substance(
        slug=guide_dir.name,
        chapters=len(chapters),
        margins=total_margins,
        duplicated=duplicated,
        dup_rate=rate,
        clones=clones,
        problems=problems,
        vignettes=vignettes,
    )


def fleet_table() -> str:
    rows = sorted(
        (measure(g) for g in guide_dirs()),
        key=lambda s: (-s.dup_rate, s.retrieval_artifacts),
    )
    flagged = [s for s in rows if s.flagged]
    out = [
        "| Guide | Ch | Margins | Cloned | Dup% | Problems | Vignettes | Flags |",
        "|---|--:|--:|--:|--:|--:|--:|---|",
    ]
    for s in rows:
        if not s.flagged:
            continue
        flags = []
        if s.margins_flagged:
            flags.append("cloned-margins")
        if s.retrieval_flagged:
            flags.append("no-retrieval")
        out.append(
            f"| `{s.slug}` | {s.chapters} | {s.margins} | {s.duplicated} | "
            f"{s.dup_rate * 100:.0f}% | {s.problems} | {s.vignettes} | {', '.join(flags)} |"
        )
    n_clone = sum(1 for s in flagged if s.margins_flagged)
    n_retr = sum(1 for s in flagged if s.retrieval_flagged)
    out.append("")
    out.append(
        f"**{len(flagged)} of {len(rows)} guide(s) flagged** — "
        f"{n_clone} over the {MAX_DUP_RATE:.0%} margin-clone rate, "
        f"{n_retr} with no problems and no vignettes."
    )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit chapter content for cloned margins and absent retrieval practice")
    ap.add_argument("--guide", help="guide slug to audit (e.g. manning_<slug>)")
    ap.add_argument("--fleet", action="store_true",
                    help="rank the whole fleet worst-first as a markdown table")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --guide)")
    ap.add_argument("--strict", "--check", dest="strict", action="store_true",
                    help="exit 1 if the guide is flagged (NOT yet wired into audit_gold G2)")
    args = ap.parse_args()

    if args.fleet:
        print(fleet_table())
        return

    if not args.guide:
        ap.error("one of --guide or --fleet is required")

    guide_dir = guide_dir_for_slug(args.guide)
    if guide_dir is None or not guide_dir.is_dir():
        # Message shape matches audit_gold.NOT_FOUND_RE.
        print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
        sys.exit(2)

    s = measure(guide_dir)

    if args.json:
        print(json.dumps({
            "slug": s.slug,
            "chapters": s.chapters,
            "margins": s.margins,
            "duplicated": s.duplicated,
            "dup_rate": round(s.dup_rate, 3),
            "problems": s.problems,
            "vignettes": s.vignettes,
            "margins_flagged": s.margins_flagged,
            "retrieval_flagged": s.retrieval_flagged,
            "clones": [vars(c) for c in s.clones],
        }, indent=2))
    elif s.flagged:
        # Advisory: must NOT start with "FAIL" (audit_gold.FAIL_RE) so a flagless
        # G2 registration cannot gate on it during the warning-first rollout.
        if s.margins_flagged:
            print(f"{s.slug}: {s.duplicated}/{s.margins} margin note(s) are verbatim "
                  f"repeats ({s.dup_rate * 100:.0f}%)")
            for c in s.clones[:5]:
                print(f"  x{c.count} across {len(c.files)} file(s): {c.text[:90]}")
        if s.retrieval_flagged:
            print(f"{s.slug}: no retrieval practice in {s.chapters} chapter(s) — "
                  f"{s.problems} problem(s), {s.vignettes} vignette(s)")
    else:
        print(f"PASS  {s.slug}: {s.dup_rate * 100:.0f}% cloned margins, "
              f"{s.problems} problems, {s.vignettes} vignettes")

    if args.strict and s.flagged:
        if s.margins_flagged:
            print(f"FAIL  {s.slug}: margin clone rate {s.dup_rate * 100:.0f}% "
                  f"> {MAX_DUP_RATE:.0%}", file=sys.stderr)
        if s.retrieval_flagged:
            print(f"FAIL  {s.slug}: 0 problems and 0 vignettes across "
                  f"{s.chapters} chapters", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
