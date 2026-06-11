#!/usr/bin/env python3
"""Auto-fix card_presentation issues by wrapping long LaTeX source lines.

Targets the two dominant issue types from `audit_card_presentation.py`:

  - `very_long_line` (>200 chars per line): wrap prose lines at sentence
    boundaries (`. `, `? `, `! `) into roughly 100-char lines.
  - `wall_of_text` (>500 char paragraph): if a paragraph's total length
    exceeds 500 chars after wrapping, insert a blank line between
    mid-paragraph sentences to create a paragraph break.

LaTeX treats consecutive whitespace as a single space for rendering, so
wrapping at sentence boundaries does not change the compiled PDF. Lines
inside verbatim/minted/tabular/equation blocks are left untouched.

Usage:
    python3 shared/audits/card_presentation_autofix.py <file1.tex> [<file2.tex> ...]
    python3 shared/audits/card_presentation_autofix.py --glob "manning_rlhf_book/notes/notebook/chapters/*.tex"

The script reports counts of modified lines per file; run with `--dry-run`
to preview without writing.
"""
from __future__ import annotations

import argparse
import glob as _glob
import re
import sys
import textwrap
from pathlib import Path

LINE_WIDTH_TARGET = 100
LINE_WIDTH_HARD_MAX = 180  # well under the 200-char audit threshold
PARA_MAX_CHARS = 500
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z\\])")

EXCLUDED_BLOCK_STARTS = (
    r"\begin{verbatim}",
    r"\begin{minted}",
    r"\begin{tabular}",
    r"\begin{equation}",
    r"\begin{equation*}",
    r"\begin{align}",
    r"\begin{align*}",
    r"\begin{lstlisting}",
)
EXCLUDED_BLOCK_ENDS = (
    r"\end{verbatim}",
    r"\end{minted}",
    r"\end{tabular}",
    r"\end{equation}",
    r"\end{equation*}",
    r"\end{align}",
    r"\end{align*}",
    r"\end{lstlisting}",
)


def is_long_prose_line(line: str) -> bool:
    if len(line) <= 200:
        return False
    if "\\begin{" in line and "\\end{" in line:
        return False
    return True


def hard_wrap_long_line(text: str, indent: str, width: int) -> list[str]:
    """Word-wrap a string that is still too long after sentence splitting.

    Uses textwrap but does not break inside words, so LaTeX commands like
    `\\textbf{foo}` or `\\begin{enumerate}` stay intact as long as they
    have no internal whitespace.
    """
    wrapped = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
        drop_whitespace=True,
    )
    return [indent + line for line in wrapped] if wrapped else [indent + text]


def wrap_prose_line(line: str, width: int = LINE_WIDTH_TARGET) -> list[str]:
    """Wrap one long prose line at sentence boundaries, preserving indent."""
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]

    sentences = SENTENCE_SPLIT_RE.split(stripped)

    result: list[str] = []
    current = ""
    if len(sentences) <= 1:
        current = stripped
    else:
        for s in sentences:
            tentative = (current + " " + s).strip() if current else s
            if len(tentative) <= width:
                current = tentative
            else:
                if current:
                    result.append(indent + current)
                    current = s
                else:
                    result.append(indent + s)
                    current = ""
    if current:
        if len(indent + current) <= LINE_WIDTH_HARD_MAX:
            result.append(indent + current)
        else:
            result.extend(hard_wrap_long_line(current, indent, LINE_WIDTH_HARD_MAX))

    # Safety net: any line still over the hard max gets word-wrapped.
    final: list[str] = []
    for l in result:
        stripped_l = l.lstrip()
        indent_l = l[: len(l) - len(stripped_l)]
        if len(l) > LINE_WIDTH_HARD_MAX and stripped_l:
            final.extend(hard_wrap_long_line(stripped_l, indent_l, LINE_WIDTH_HARD_MAX))
        else:
            final.append(l)
    return final if final else [line]


_STRUCTURAL_PREFIXES = (
    "\\item", "\\begin{", "\\end{",
    "\\foreach", "\\ifnum", "\\ifdim", "\\fi", "\\else", "\\or",
    "\\pgfmath", "\\filldraw", "\\draw", "\\path", "\\node",
    "\\tikzset", "\\edef", "\\def", "\\let", "\\makeatletter",
    "\\makeatother",
)


def _has_structural_markers(para_lines: list[str]) -> bool:
    """Paragraphs containing LaTeX env boundaries, flow-control tokens, or
    TikZ/pgf commands must NOT be reflowed — reflow would collapse multi-line
    list / env / foreach-loop structure onto one line and break extraction,
    rendering, or pgfmath parsing."""
    for line in para_lines:
        stripped = line.lstrip()
        if stripped.startswith(_STRUCTURAL_PREFIXES):
            return True
    return False


def break_long_paragraph(para_lines: list[str]) -> list[str]:
    if _has_structural_markers(para_lines):
        return para_lines
    joined = " ".join(l.strip() for l in para_lines)
    if len(joined) <= PARA_MAX_CHARS:
        return para_lines
    sentences = SENTENCE_SPLIT_RE.split(joined)
    if len(sentences) < 3:
        return para_lines
    mid = len(sentences) // 2
    first_text = " ".join(sentences[:mid])
    second_text = " ".join(sentences[mid:])
    indent = ""
    for line in para_lines:
        stripped = line.lstrip()
        if stripped:
            indent = line[: len(line) - len(stripped)]
            break
    first_wrapped = wrap_prose_line(indent + first_text)
    second_wrapped = wrap_prose_line(indent + second_text)
    return first_wrapped + [""] + second_wrapped


def process_file(path: Path, dry_run: bool = False) -> dict[str, int]:
    original = path.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    in_excluded_block = False
    modified_lines = 0

    # Pass 1: wrap long prose lines, leaving paragraph structure intact.
    for line in original:
        if any(marker in line for marker in EXCLUDED_BLOCK_STARTS):
            in_excluded_block = True
            result.append(line)
            continue
        if any(marker in line for marker in EXCLUDED_BLOCK_ENDS):
            in_excluded_block = False
            result.append(line)
            continue
        if in_excluded_block:
            result.append(line)
            continue
        if is_long_prose_line(line):
            wrapped = wrap_prose_line(line)
            if wrapped != [line]:
                modified_lines += 1
            result.extend(wrapped)
        else:
            result.append(line)

    # Pass 2: break walls of text — scan paragraphs (separated by blank lines).
    pass2: list[str] = []
    paragraph: list[str] = []
    broken_paragraphs = 0
    in_excluded_block = False
    for line in result:
        if any(marker in line for marker in EXCLUDED_BLOCK_STARTS):
            in_excluded_block = True
        if any(marker in line for marker in EXCLUDED_BLOCK_ENDS):
            in_excluded_block = False
        is_blank = line.strip() == ""
        if in_excluded_block or is_blank:
            if paragraph:
                broken = break_long_paragraph(paragraph)
                if broken != paragraph:
                    broken_paragraphs += 1
                pass2.extend(broken)
                paragraph = []
            pass2.append(line)
        else:
            paragraph.append(line)
    if paragraph:
        broken = break_long_paragraph(paragraph)
        if broken != paragraph:
            broken_paragraphs += 1
        pass2.extend(broken)

    new_text = "\n".join(pass2)
    if not new_text.endswith("\n"):
        new_text += "\n"

    if not dry_run and new_text != path.read_text(encoding="utf-8"):
        path.write_text(new_text, encoding="utf-8")

    return {
        "wrapped_long_lines": modified_lines,
        "broken_paragraphs": broken_paragraphs,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="Individual .tex files to fix")
    ap.add_argument("--glob", help="Glob pattern for .tex files")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = ap.parse_args()

    paths: list[Path] = []
    if args.glob:
        paths.extend(Path(p) for p in _glob.glob(args.glob))
    for p in args.paths:
        paths.append(Path(p))
    if not paths:
        print("No .tex paths given.", file=sys.stderr)
        sys.exit(1)

    total_wrapped = 0
    total_broken = 0
    for path in paths:
        if not path.exists() or path.suffix != ".tex":
            continue
        stats = process_file(path, dry_run=args.dry_run)
        total_wrapped += stats["wrapped_long_lines"]
        total_broken += stats["broken_paragraphs"]
        if stats["wrapped_long_lines"] or stats["broken_paragraphs"]:
            print(
                f"  {path.name}: wrapped {stats['wrapped_long_lines']} long lines, "
                f"broke {stats['broken_paragraphs']} walls"
            )
    print(
        f"\nTotal across {len(paths)} files: "
        f"{total_wrapped} long lines wrapped, {total_broken} walls broken"
        f"{' (dry run)' if args.dry_run else ''}"
    )


if __name__ == "__main__":
    main()
