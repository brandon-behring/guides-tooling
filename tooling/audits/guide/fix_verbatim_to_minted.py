#!/usr/bin/env python3
"""Triage \\begin{verbatim}...\\end{verbatim} blocks; convert code-shaped
ones to \\begin{minted}{language}; keep ASCII art / output samples as
verbatim.

Per ``latex-conventions.md``: "Use ``\\begin{minted}{language}`` for code
blocks (not lstlisting)." Verbatim is acceptable for non-code (ASCII art,
output samples, tree diagrams).

Triage signals:
- Python keywords (``def``, ``class``, ``import``, ``async``, type hints) → minted{python}
- SQL (``SELECT``, ``FROM``, ``WHERE``, ``JOIN``) → minted{sql}
- JSON (``{``...``: "..."``...``}``) → minted{json}
- YAML (``---\\n``, ``key: value`` pairs) → minted{yaml}
- Cypher (``MATCH (n)-[:REL]->(m)``) → minted{cypher}
- Shell (``$ ``, ``>>> ``, pipes) → minted{bash}
- Otherwise → keep verbatim

Usage::

    python3 shared/audits/fix_verbatim_to_minted.py --all                 # preview
    python3 shared/audits/fix_verbatim_to_minted.py --all --apply         # commit
    python3 shared/audits/fix_verbatim_to_minted.py --guide <slug> [--apply]
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

VERBATIM_RE = re.compile(
    r"\\begin\{verbatim\}(.*?)\\end\{verbatim\}", re.DOTALL
)


def detect_language(content: str) -> str | None:
    """Heuristic language detection. Returns None for non-code."""
    # Strip leading/trailing whitespace
    text = content.strip()
    if not text:
        return None

    # Python (most distinctive)
    if re.search(r"\b(def|class|import|from\s+\w+\s+import|async\s+def|lambda|elif|@\w+)\b", text):
        return "python"
    if re.search(r"^\s*[a-zA-Z_]\w*\s*[:=]\s*[A-Za-z\[\(]", text, re.MULTILINE) and \
       re.search(r"^\s*(return|print|self\.|def\s)", text, re.MULTILINE):
        return "python"

    # SQL
    if re.search(r"\b(SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY)\b", text, re.IGNORECASE):
        if re.search(r";\s*$|\bFROM\s+\w+|\bWHERE\s+\w+", text, re.IGNORECASE):
            return "sql"

    # Cypher (Neo4j)
    if re.search(r"MATCH\s*\(.*?\)-\[:\w+\]->", text):
        return "cypher"
    if re.search(r"\b(MATCH|RETURN|CREATE|MERGE)\b\s*\(", text):
        return "cypher"

    # JSON (must look like an actual JSON object/array)
    if re.match(r"^\s*[\{\[]", text) and re.search(r'"\w+"\s*:', text):
        return "json"

    # YAML (key: value pairs at start of lines)
    yaml_lines = re.findall(r"^[a-zA-Z_][\w-]*\s*:\s*\S", text, re.MULTILINE)
    if len(yaml_lines) >= 3 and not re.search(r"\bdef\s+\w+\(", text):
        return "yaml"

    # Shell (prompts or command-line specific tokens)
    if re.search(r"^\s*\$\s+\w+", text, re.MULTILINE) or \
       re.search(r"^\s*>>>\s+", text, re.MULTILINE):
        return "bash"
    if re.search(r"\b(pip\s+install|npm\s+install|git\s+\w+|curl\s+|cd\s+)", text):
        return "bash"

    # ASCII art / tree structure / aligned output
    if re.search(r"[├└│─┐┌┘┴┬┤├]|[─-╿]", text):
        return None  # box-drawing characters → keep verbatim
    if re.search(r"^\s*\w+\s+\d+\s*\n", text, re.MULTILINE):
        # Tabular numeric output → keep verbatim
        return None

    return None  # default: keep verbatim


def fix_file(path: Path, apply: bool) -> tuple[int, int]:
    """Process one file. Returns (converted, kept_verbatim)."""
    content = path.read_text(encoding="utf-8")
    converted = 0
    kept = 0

    def replace(match: re.Match) -> str:
        nonlocal converted, kept
        body = match.group(1)
        lang = detect_language(body)
        if lang is None:
            kept += 1
            return match.group(0)  # unchanged
        converted += 1
        return f"\\begin{{minted}}{{{lang}}}{body}\\end{{minted}}"

    new_content = VERBATIM_RE.sub(replace, content)

    if converted and apply:
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(content, encoding="utf-8")
        path.write_text(new_content, encoding="utf-8")

    return converted, kept


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
        description="Triage verbatim blocks; convert code-shaped to minted."
    )
    parser.add_argument("--guide", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.guide and not args.all:
        parser.error("Specify --guide <slug> or --all")

    chapters = find_chapters(args.guide if not args.all else None)
    total_converted = 0
    total_kept = 0
    by_guide_conv: dict[str, int] = {}

    for chapter in chapters:
        n_conv, n_kept = fix_file(chapter, apply=args.apply)
        if n_conv == 0 and n_kept == 0:
            continue
        slug = chapter.parents[2].name
        if n_conv > 0:
            by_guide_conv[slug] = by_guide_conv.get(slug, 0) + n_conv
            print(f"  {chapter}: {n_conv} → minted, {n_kept} kept verbatim",
                  file=sys.stderr)
        total_converted += n_conv
        total_kept += n_kept

    action = "applied" if args.apply else "previewed"
    print(
        f"\n{total_converted} verbatim → minted {action}; "
        f"{total_kept} kept as verbatim (ASCII art / output).",
        file=sys.stderr,
    )
    if by_guide_conv:
        print("Per-guide conversions:", file=sys.stderr)
        for slug, n in sorted(by_guide_conv.items(), key=lambda kv: -kv[1]):
            print(f"  {slug}: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
