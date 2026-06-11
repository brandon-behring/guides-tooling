#!/usr/bin/env python3
"""Auto-rewrite "See solution above" Answer stubs to substantive recaps.

For each ``\\textbf{Answer:} See solution above.`` stub, this script:

1. Locates the enclosing ``\\begin{solution}...\\end{solution}`` block
2. Extracts the ``\\textbf{Approach:}`` section content
3. If Approach uses ``\\begin{enumerate}[label=(\\alph*)]`` or numbered
   enumerate, the generated Answer lists each item's first sentence as
   the bottom-line recap
4. Otherwise generates a single declarative sentence drawn from the
   Key Insight section (or first paragraph of Approach)
5. Marks the new Answer with ``% NEW: auto-generated 2026-04-30 -
   please review and refine`` for user editing

Usage::

    python3 shared/audits/fix_answer_stubs.py --guide <slug>          # preview
    python3 shared/audits/fix_answer_stubs.py --guide <slug> --apply  # commit
    python3 shared/audits/fix_answer_stubs.py --all
    python3 shared/audits/fix_answer_stubs.py --all --apply

Each generated Answer is a DRAFT — the bullet contents are mechanically
extracted, so voice + pedagogical polish requires user review (per the
``% NEW:`` flag-for-refinement convention).
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

STUB_PATTERN = re.compile(
    r"\\textbf\{Answer:\}\s+See solution above\.?",
    re.IGNORECASE,
)


def find_solution_block(content: str, stub_pos: int) -> tuple[int, int] | None:
    """Find the enclosing solution block around a stub at ``stub_pos``."""
    begin = content.rfind(r"\begin{solution}", 0, stub_pos)
    end = content.find(r"\end{solution}", stub_pos)
    if begin == -1 or end == -1:
        return None
    return begin, end


def extract_approach(solution_text: str) -> str:
    """Extract the Approach section's prose content."""
    m = re.search(r"\\textbf\{Approach:\}\s*", solution_text)
    if not m:
        return ""
    after = solution_text[m.end():]
    # Stop at the next \textbf header (Step / Key Insight / Answer / etc.)
    next_header = re.search(
        r"\\textbf\{(?:Step|Key Insight|Answer|Decision Rule|Why It Matters|"
        r"When It Breaks|Note|Final|Trade-off|Verification|Implementation)",
        after,
    )
    chunk = after[: next_header.start()] if next_header else after
    return chunk.strip()


def _split_items_top_level(body: str) -> list[str]:
    """Split on ``\\item`` at outer nesting depth only.

    Tracks ``\\begin{X}`` / ``\\end{X}`` pairs so that nested lists do not
    contaminate top-level item extraction. Returns a list of trimmed item
    bodies.
    """
    items: list[str] = []
    current: list[str] = []
    depth = 0
    pos = 0
    n = len(body)
    while pos < n:
        m_begin = re.match(r"\\begin\{[^}]+\}", body[pos:])
        m_end = re.match(r"\\end\{[^}]+\}", body[pos:])
        m_item = re.match(r"\\item\b\s*", body[pos:])
        if m_begin:
            depth += 1
            current.append(body[pos:pos + m_begin.end()])
            pos += m_begin.end()
        elif m_end:
            depth -= 1
            current.append(body[pos:pos + m_end.end()])
            pos += m_end.end()
        elif m_item and depth == 0:
            if current:
                items.append("".join(current).strip())
            current = []
            pos += m_item.end()
        else:
            current.append(body[pos])
            pos += 1
    if current:
        items.append("".join(current).strip())
    return [item for item in items if item]


def extract_enumerate_items(text: str) -> list[str] | None:
    """Extract items from an ``\\begin{enumerate}...\\end{enumerate}`` block.

    Returns list of stripped item bodies, or ``None`` if no enumerate found.
    Nested ``\\begin{itemize}/\\begin{enumerate}`` blocks are respected so
    that ``\\item`` markers inside them do not split the outer list.
    """
    # Find the outermost \begin{enumerate}...\end{enumerate} block to handle
    # nested enumerates correctly.
    begin_match = re.search(r"\\begin\{enumerate\}(?:\[[^\]]*\])?", text)
    if not begin_match:
        return None
    pos = begin_match.end()
    depth = 1
    while pos < len(text) and depth > 0:
        m_begin = re.match(r"\\begin\{enumerate\}", text[pos:])
        m_end = re.match(r"\\end\{enumerate\}", text[pos:])
        if m_begin:
            depth += 1
            pos += m_begin.end()
        elif m_end:
            depth -= 1
            if depth == 0:
                body = text[begin_match.end():pos]
                return _split_items_top_level(body)
            pos += m_end.end()
        else:
            pos += 1
    return None


def _strip_nested_lists(item: str) -> str:
    """Remove nested ``itemize``/``enumerate`` blocks from an item's text.

    Used when summarizing an outer enumerate item that contains its own
    sub-list. We keep the prose preceding/following the nested block so the
    item's introductory sentence remains usable for ``first_sentence``.
    """
    return re.sub(
        r"\\begin\{(itemize|enumerate)\}(?:\[[^\]]*\])?[\s\S]*?\\end\{\1\}",
        " ",
        item,
    )


def first_sentence(text: str, min_break_pos: int = 30, max_chars: int = 280) -> str:
    """Return first sentence of ``text``.

    Refuses to break on digit-period patterns like ``1.``, ``0.5`` so that
    enumerated bullets and decimal numerals don't truncate prematurely.
    Requires the break position to be at least ``min_break_pos`` chars in,
    otherwise falls through to a length-limited prefix that prefers a
    sentence boundary.
    """
    cleaned = text.strip()
    # Negative lookbehind: don't treat digit-period as a sentence boundary
    m = re.search(r"(?<!\d)([.!?])\s+[A-Z]", cleaned)
    if m and m.start() >= min_break_pos:
        return cleaned[: m.start() + 1].strip()
    if len(cleaned) <= max_chars:
        return cleaned.rstrip()
    fallback = cleaned[:max_chars]
    last_period = fallback.rfind(".")
    if last_period >= 60:
        return fallback[: last_period + 1].rstrip()
    return fallback.rstrip()


_PART_STOP = (
    r"(?=\\textbf\{\([a-z]\)|\\textbf\{\d+\.|\\textbf\{Key Insight"
    r"|\\textbf\{Answer|\\textbf\{Why It Matters|\\textbf\{When It Breaks"
    r"|\\textbf\{Decision Rule|\\textbf\{Final|\\textbf\{Asymmetry"
    r"|\\textbf\{Strategy|\\end\{solution\}|\Z)"
)


def extract_inline_parts(text: str) -> list[tuple[str, str, str]] | None:
    """Detect inline ``\\textbf{(a) Title:}`` / ``\\textbf{1. Title:}`` parts.

    Many Approach sections use bold inline labels rather than a real
    ``\\begin{enumerate}``. Returns a list of ``(label, title, body)``
    tuples, where ``title`` is the bold heading content (without trailing
    punctuation) and ``body`` is the prose that follows up to the next
    label or stop marker. Returns ``None`` if fewer than two clean parts
    are found.
    """
    lettered_re = re.compile(
        r"\\textbf\{\(([a-z])\)\s*([^}]*?)\}\s*([\s\S]*?)" + _PART_STOP,
    )
    lettered = lettered_re.findall(text)
    if len(lettered) >= 2:
        return [
            (f"({letter})", title.rstrip(":").strip(), body.strip())
            for letter, title, body in lettered
        ]
    numbered_re = re.compile(
        r"\\textbf\{(\d+)\.\s*([^}]*?)\}\s*([\s\S]*?)" + _PART_STOP,
    )
    numbered = numbered_re.findall(text)
    if len(numbered) >= 2:
        return [
            (f"{n}.", title.rstrip(":").strip(), body.strip())
            for n, title, body in numbered
        ]
    return None


def has_multipart_question(problem_text: str) -> bool:
    """Detect multi-part question structures in the problem statement.

    Triggers on any of:
    - ``\\begin{enumerate}`` block,
    - inline ``(a)~`` / ``(b)~`` markers (>= 2),
    - inline ``(a) `` / ``(b) `` markers (>= 2).
    """
    if re.search(r"\\begin\{enumerate\}", problem_text, re.DOTALL):
        return True
    if len(re.findall(r"\(([a-z])\)~", problem_text)) >= 2:
        return True
    if len(re.findall(r"\(([a-z])\)\s+[A-Za-z\\$]", problem_text)) >= 2:
        return True
    return False


def _bullet_from_part(label: str, title: str, body: str) -> str:
    """Compose an enumerate item from a ``(label, title, body)`` triple.

    Nested ``itemize``/``enumerate`` blocks inside ``body`` are stripped so
    the bullet contains only flat prose. Math, ``\\texttt``, and inline
    formatting are preserved.
    """
    body_flat = re.sub(r"\s+", " ", _strip_nested_lists(body)).strip()
    summary = first_sentence(body_flat) if body_flat else ""
    title_clean = title.rstrip(".").rstrip(":").strip()
    if title_clean and summary:
        return f"\\textbf{{{title_clean}:}} {summary}"
    if title_clean:
        return f"\\textbf{{{title_clean}}}."
    return summary or "(see solution body)"


def generate_answer(solution_text: str, has_enumerate_in_problem: bool) -> str:
    """Generate the replacement Answer text from Approach content."""
    approach = extract_approach(solution_text)
    if not approach:
        ki_match = re.search(
            r"\\textbf\{Key Insight:\}\s*(.+?)(?=\\textbf\{|\Z)",
            solution_text, re.DOTALL,
        )
        if ki_match:
            return r"\textbf{Answer:} " + first_sentence(ki_match.group(1))
        return r"\textbf{Answer:} See Approach above for derivation."

    if has_enumerate_in_problem:
        parts = extract_inline_parts(approach)
        if parts and len(parts) >= 2:
            bullets = [_bullet_from_part(*p) for p in parts]
            body_str = "\n".join(f"  \\item {b}" for b in bullets)
            return (
                "\\textbf{Answer:}\n"
                "\\begin{enumerate}[label=(\\alph*)]\n"
                f"{body_str}\n"
                "\\end{enumerate}"
            )

    items = extract_enumerate_items(approach)
    if items and len(items) >= 2 and has_enumerate_in_problem:
        bullets = []
        for item in items:
            stripped = _strip_nested_lists(item)
            cleaned = re.sub(r"^\\textbf\{[^}]+\}\s*[:.]?\s*", "", stripped)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                bullets.append(first_sentence(cleaned))
        if len(bullets) >= 2:
            body_str = "\n".join(f"  \\item {b}" for b in bullets)
            return (
                "\\textbf{Answer:}\n"
                "\\begin{enumerate}[label=(\\alph*)]\n"
                f"{body_str}\n"
                "\\end{enumerate}"
            )

    return r"\textbf{Answer:} " + first_sentence(approach)


def fix_file(path: Path, apply: bool) -> int:
    """Process a single chapter file. Returns number of stubs replaced."""
    content = path.read_text(encoding="utf-8")
    matches = list(STUB_PATTERN.finditer(content))
    if not matches:
        return 0

    new_content = content
    # Process matches in reverse so earlier offsets remain valid
    for match in reversed(matches):
        block = find_solution_block(new_content, match.start())
        if not block:
            continue
        begin, end = block
        solution_text = new_content[begin:end]
        # Was the problem statement using enumerate (multi-part question)?
        # Heuristic: look back from \begin{solution} to nearest \begin{problem}
        problem_begin = new_content.rfind(r"\begin{problem}", 0, begin)
        problem_end = begin
        problem_text = (
            new_content[problem_begin:problem_end] if problem_begin != -1 else ""
        )
        has_enum = has_multipart_question(problem_text)

        replacement = generate_answer(solution_text, has_enum)
        new_content = (
            new_content[: match.start()]
            + "% NEW: auto-generated 2026-04-30 - please review and refine\n"
            + replacement
            + new_content[match.end():]
        )

    if apply:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(content, encoding="utf-8")
        path.write_text(new_content, encoding="utf-8")

    return len(matches)


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
        description="Auto-rewrite 'See solution above' Answer stubs."
    )
    parser.add_argument("--guide", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.guide and not args.all:
        parser.error("Specify --guide <slug> or --all")

    chapters = find_chapters(args.guide if not args.all else None)
    total = 0
    files_changed = 0
    by_guide: dict[str, int] = {}

    for chapter in chapters:
        n = fix_file(chapter, apply=args.apply)
        if n == 0:
            continue
        total += n
        files_changed += 1
        slug = chapter.parents[2].name
        by_guide[slug] = by_guide.get(slug, 0) + n
        print(f"  {chapter}: {n} stub(s)", file=sys.stderr)

    action = "applied" if args.apply else "previewed"
    print(
        f"\n{total} stub(s) {action} across {files_changed} file(s).",
        file=sys.stderr,
    )
    for slug, n in sorted(by_guide.items(), key=lambda kv: -kv[1]):
        print(f"  {slug}: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
