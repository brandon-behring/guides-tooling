#!/usr/bin/env python3
"""Regenerate auto-generated Answer recaps using the patched extractor.

The original ``fix_answer_stubs.py`` (commit ``c775324b``) introduced three
truncation bugs that left ~145 fleet-wide Answer recaps in a broken state
(``\\textbf{Answer:} \\textbf{1.``, single-part-only output for multi-part
problems, etc.). The bugs are now fixed in ``fix_answer_stubs.py``; this
script re-applies the now-correct logic to existing
``% NEW: auto-generated 2026-04-30`` blocks **without needing to revert**
to the original ``See solution above`` stubs.

For each marker:

1. Locate the marker line and the ``\\textbf{Answer:}`` block that follows it
2. Find the enclosing ``\\begin{solution}...\\end{solution}`` block
3. Re-extract the Approach via ``fix_answer_stubs.generate_answer``
4. Replace the broken Answer (marker + Answer block) with marker + new Answer
5. Skip blocks where regeneration would produce IDENTICAL or WORSE content
   (keep the existing Answer if it already has substantive recap text).

Usage::

    python3 shared/audits/regenerate_answer_stubs.py --all                # preview
    python3 shared/audits/regenerate_answer_stubs.py --all --apply        # commit
    python3 shared/audits/regenerate_answer_stubs.py --guide <slug> [--apply]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


from tooling.audits.guide._guide_scope import (  # noqa: E402
    chapter_files,
    guide_dir_for_slug,
    guide_dirs,
)
from tooling.audits.guide.fix_answer_stubs import generate_answer, has_multipart_question  # noqa: E402

MARKER = "% NEW: auto-generated 2026-04-30 - please review and refine"

# Marker line followed by the regenerated Answer block.
# The Answer extends to (a) the next \textbf{...} that opens a new section,
# (b) \end{solution}, or (c) end-of-file. We anchor on \end{solution} for
# safety since auto-generated answers always sit just before it.
MARKER_BLOCK_RE = re.compile(
    re.escape(MARKER) + r"\n(\\textbf\{Answer:\}[\s\S]*?)(?=\\end\{solution\})",
)


def _is_truncated_recap(answer_text: str, expects_multipart: bool) -> bool:
    """Heuristic: should the existing Answer be regenerated?

    Decision tree:
    1. If body ends with a bare ``\\textbf{N.`` or ``\\textbf{(letter)`` → True
       (digit-period truncation bug: ``first_sentence`` stopped at ``1.``).
    2. If body is empty or just header punctuation → True.
    3. If problem is multi-part and Answer has < 2 enumerate items AND
       < 3 ``\\textbf{...}`` sub-headers → True (single-part output for a
       multi-part question, e.g. only ``(a)`` of ``(a)(b)(c)(d)``).
    4. Otherwise → False (substantive single-part recap is fine).
    """
    body = re.sub(r"^\\textbf\{Answer:\}\s*", "", answer_text.strip(), count=1)
    body = body.strip()
    if not body:
        return True
    if re.fullmatch(r"\\textbf\{\d+\.[\s\S]{0,5}", body):
        return True
    if re.fullmatch(r"\\textbf\{\([a-z]\)[\s\S]{0,5}", body):
        return True

    if expects_multipart:
        item_count = len(re.findall(r"\\item\s+", body))
        bold_headers = len(re.findall(r"\\textbf\{[^}]+\}", body))
        if item_count < 2 and bold_headers < 3:
            return True

    return False


def find_solution_for_marker(content: str, marker_pos: int) -> tuple[int, int] | None:
    """Find the enclosing ``\\begin{solution}...\\end{solution}`` for a marker."""
    begin = content.rfind(r"\begin{solution}", 0, marker_pos)
    end = content.find(r"\end{solution}", marker_pos)
    if begin == -1 or end == -1:
        return None
    return begin, end


def regenerate_file(path: Path, apply: bool, force: bool) -> tuple[int, int]:
    """Regenerate broken auto-gen recaps in one file.

    Returns ``(regenerated, kept)``.
    """
    content = path.read_text(encoding="utf-8")
    matches = list(MARKER_BLOCK_RE.finditer(content))
    if not matches:
        return 0, 0

    new_content = content
    regenerated = 0
    kept = 0

    for match in reversed(matches):
        existing_answer = match.group(1)

        sol_block = find_solution_for_marker(new_content, match.start())
        if not sol_block:
            kept += 1
            continue
        sol_begin, sol_end = sol_block
        solution_text = new_content[sol_begin:sol_end]

        problem_begin = new_content.rfind(r"\begin{problem}", 0, sol_begin)
        problem_text = (
            new_content[problem_begin:sol_begin] if problem_begin != -1 else ""
        )
        has_enum = has_multipart_question(problem_text)

        if not force and not _is_truncated_recap(existing_answer, has_enum):
            kept += 1
            continue

        new_answer = generate_answer(solution_text, has_enum)
        if new_answer.strip() == existing_answer.strip():
            kept += 1
            continue

        new_content = (
            new_content[: match.start()]
            + MARKER + "\n"
            + new_answer + "\n"
            + new_content[match.end():]
        )
        regenerated += 1

    if regenerated and apply:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(content, encoding="utf-8")
        path.write_text(new_content, encoding="utf-8")

    return regenerated, kept


def find_chapters(guide: str | None) -> list[Path]:
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
        description=(
            "Regenerate broken auto-generated Answer recaps using the "
            "patched fix_answer_stubs extractor."
        ),
    )
    parser.add_argument("--guide", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate ALL marker blocks, including those that look fine.",
    )
    args = parser.parse_args()

    if not args.guide and not args.all:
        parser.error("Specify --guide <slug> or --all")

    chapters = find_chapters(args.guide if not args.all else None)
    total_regen = 0
    total_kept = 0
    files_changed = 0
    by_guide: dict[str, int] = {}

    for chapter in chapters:
        n_regen, n_kept = regenerate_file(chapter, apply=args.apply, force=args.force)
        if n_regen == 0 and n_kept == 0:
            continue
        if n_regen > 0:
            files_changed += 1
            slug = chapter.parents[2].name
            by_guide[slug] = by_guide.get(slug, 0) + n_regen
            print(
                f"  {chapter}: {n_regen} regenerated, {n_kept} kept",
                file=sys.stderr,
            )
        total_regen += n_regen
        total_kept += n_kept

    action = "applied" if args.apply else "previewed"
    print(
        f"\n{total_regen} answer(s) regenerated {action} across "
        f"{files_changed} file(s); {total_kept} kept as-is.",
        file=sys.stderr,
    )
    if by_guide:
        print("Per-guide regenerations:", file=sys.stderr)
        for slug, n in sorted(by_guide.items(), key=lambda kv: -kv[1]):
            print(f"  {slug}: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
