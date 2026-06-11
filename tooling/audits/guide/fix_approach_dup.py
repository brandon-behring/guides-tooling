#!/usr/bin/env python3
"""Remove duplicate "Approach: \\textbf{X}" copy-paste artifact lines.

Pattern: line N is ``\\textbf{Approach:} \\textbf{X} ...``, line N+1 is
identical content to line N after stripping the ``\\textbf{Approach:}``
prefix. The duplicate was likely introduced during chapter authoring
copy-paste; it produces no visible LaTeX rendering issue but bloats
the chapter source and feeds into card extraction as redundant prose.

Found in 19 guides during the 2026-04-30 polish sweep. This fixer
mirrors the inline script proven on dlai_evaluating_ai_agents (which
removed 12 duplicate lines across 5 chapters).

Usage::

    python3 shared/audits/fix_approach_dup.py --guide <slug>
    python3 shared/audits/fix_approach_dup.py --guide <slug> --apply
    python3 shared/audits/fix_approach_dup.py --all
    python3 shared/audits/fix_approach_dup.py --all --apply

Safety:
- Byte-identical removal only (after stripping the Approach prefix);
  semantic restatements with even slight wording differences will not
  trigger.
- ``.bak`` written for every modified file before --apply.
- Default mode prints a unified diff for review.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

from tooling.audits.guide._guide_scope import (  # noqa: E402
    chapter_files,
    guide_dir_for_slug,
    guide_dirs,
)


def find_duplicate_approach_lines(content: str) -> list[int]:
    """Return 0-based line indices of duplicate-Approach lines to remove.

    A line at index ``i`` is removed when:
    1. line[i-1] contains ``\\textbf{Approach:}``
    2. line[i] is non-empty
    3. line[i] equals (line[i-1] with the ``\\textbf{Approach:} `` prefix
       stripped), modulo trailing whitespace.
    """
    lines = content.splitlines()
    to_remove: list[int] = []

    for i in range(1, len(lines)):
        prev = lines[i - 1]
        cur = lines[i]
        if "Approach:" not in prev or not cur.strip():
            continue
        # Strip leading "\textbf{Approach:} " from the previous line
        prev_stripped = re.sub(r"^\\textbf\{Approach:\}\s*", "", prev)
        if cur == prev_stripped.rstrip() or cur == prev_stripped:
            to_remove.append(i)

    return to_remove


def fix_file(path: Path, apply: bool) -> tuple[int, str]:
    """Process a single ``.tex`` file. Returns (changes, diff_or_empty)."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=False)
    indices = find_duplicate_approach_lines(original)
    if not indices:
        return 0, ""

    new_lines = [line for i, line in enumerate(lines) if i not in set(indices)]
    new_content = "\n".join(new_lines) + "\n"

    if apply:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(original, encoding="utf-8")
        path.write_text(new_content, encoding="utf-8")

    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(keepends=False),
            new_content.splitlines(keepends=False),
            fromfile=str(path),
            tofile=str(path) + " (after fix)",
            lineterm="",
        )
    )
    return len(indices), diff


def find_chapters(guide: str | None) -> list[Path]:
    """Resolve chapter ``.tex`` files for one guide, or all guides."""
    if guide:
        gd = guide_dir_for_slug(guide)
        return chapter_files(gd) if gd else []
    chapters: list[Path] = []
    for d in guide_dirs():
        if not d.is_dir() or d.name.startswith("."):
            continue
        chapters.extend(chapter_files(d))
    return chapters


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate 'Approach: \\textbf{X}' lines."
    )
    parser.add_argument("--guide", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.guide and not args.all:
        parser.error("Specify --guide <slug> or --all")

    chapters = find_chapters(args.guide if not args.all else None)
    if not chapters:
        print("No chapter .tex files found.", file=sys.stderr)
        sys.exit(1)

    total = 0
    files_changed = 0
    by_guide: dict[str, int] = {}

    for chapter in chapters:
        changes, diff = fix_file(chapter, apply=args.apply)
        if changes == 0:
            continue
        total += changes
        files_changed += 1
        guide_slug = chapter.parents[2].name
        by_guide[guide_slug] = by_guide.get(guide_slug, 0) + changes
        if not args.apply and diff:
            print(diff)
        print(f"  {chapter}: {changes} duplicate(s) removed", file=sys.stderr)

    action = "applied" if args.apply else "previewed"
    print(
        f"\n{total} duplicate(s) {action} across {files_changed} file(s).",
        file=sys.stderr,
    )
    if by_guide:
        print("Per-guide breakdown:", file=sys.stderr)
        for guide_slug, n in sorted(by_guide.items(), key=lambda kv: -kv[1]):
            print(f"  {guide_slug}: {n}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
