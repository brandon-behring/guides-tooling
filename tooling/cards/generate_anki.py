#!/usr/bin/env python3
"""
Generate Anki .apkg decks from YAML card definitions.

Ported from interview_prep_series with full LaTeX→MathJax→HTML pipeline.

Usage:
    python shared/cards/generate_anki.py dlai_advanced_rag/notes/notebook/cards/all_cards.yml -o output/dlai_advanced_rag.apkg
    python shared/cards/generate_anki.py --all --output-dir output/  # All guides
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
from pathlib import Path
from typing import Any

import genanki
import yaml


# Anki model IDs (stable across regenerations)
MODEL_ID_BASIC = 1607392319
MODEL_ID_CLOZE = 1607392320

# Anki deck base ID
DECK_ID_BASE = 2059400110

# Valid HTML tags for Anki field validation
VALID_HTML_TAGS = {
    'b', 'i', 'em', 'strong', 'br', 'hr', 'p', 'div', 'span',
    'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'thead', 'tbody',
    'pre', 'code', 'dl', 'dt', 'dd', 'a', 'img', 'sub', 'sup',
}


def normalize_math_delimiters(text: str) -> str:
    r"""Normalize ALL math markup to Anki MathJax delimiters.

    Contract: After this function, all math uses \(...\) (inline)
    or \[...\] (display). No $, $$, or LaTeX math environments remain.

    Handles (in order):
    1. Single-symbol math → Unicode (e.g., $\rightarrow$ → →)
    2. Mixed delimiter cleanup ($\(...\)$ → clean)
    3. Display environments → \[...\]
    4. Display $$ → \[...\]
    5. Single-char math before digits (e.g., $-$8 → −8)
    6. Inline $...$ → \(...\) (multi-line safe)
    """
    # --- Step 1: Single-symbol math → Unicode ---
    # Do this BEFORE math delimiter conversion so we don't process these as math
    text = re.sub(r'\$\\rightarrow\$', '→', text)
    text = re.sub(r'\$\\leftarrow\$', '←', text)
    text = re.sub(r'\$\\Rightarrow\$', '⇒', text)
    text = re.sub(r'\$\\Leftarrow\$', '⇐', text)
    text = re.sub(r'\$\\uparrow\$', '↑', text)
    text = re.sub(r'\$\\downarrow\$', '↓', text)
    text = re.sub(r'\$\\geq\$', '≥', text)
    text = re.sub(r'\$\\leq\$', '≤', text)
    text = re.sub(r'\$\\times\$', '×', text)
    text = re.sub(r'\$\\neq\$', '≠', text)
    text = re.sub(r'\$\\approx\$', '≈', text)
    text = re.sub(r'\$\\pm\$', '±', text)

    # --- Step 2: Mixed delimiter cleanup ---
    # Fix mixed math delimiters: patterns like $\(...\)$ or $...\(...\)...$
    # These occur when LaTeX extraction mangles delimiter boundaries
    def fix_mixed_delimiters(m: re.Match) -> str:
        content = m.group(1)
        if r'\(' in content or r'\)' in content:
            return content.replace(r'\(', '').replace(r'\)', '')
        return m.group(0)

    text = re.sub(r'\$([^$]*\\[\(\)][^$]*)\$', fix_mixed_delimiters, text)

    # --- Step 3: Display environments → \[...\] ---
    text = re.sub(
        r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}',
        r'\\[\1\\]',
        text,
        flags=re.DOTALL
    )
    text = re.sub(
        r'\\begin\{align\*?\}(.*?)\\end\{align\*?\}',
        r'\\[\1\\]',
        text,
        flags=re.DOTALL
    )
    text = re.sub(
        r'\\begin\{aligned\*?\}(.*?)\\end\{aligned\*?\}',
        r'\\[\1\\]',
        text,
        flags=re.DOTALL
    )

    # --- Step 4: Display $$ → \[...\] ---
    text = re.sub(r'\$\$(.*?)\$\$', r'\\[\1\\]', text, flags=re.DOTALL)

    # --- Step 5: Single-char math → Unicode (context-free) ---
    # e.g., "$-$8%" → "−8%", "$\sim$30" → "≈30", "$\to$" → "→"
    text = re.sub(r'\$-\$', '−', text)
    text = re.sub(r'\$\+\$', '+', text)
    text = re.sub(r'\$<\$', '<', text)
    text = re.sub(r'\$>\$', '>', text)
    text = re.sub(r'\$\\sim\$', '≈', text)
    text = re.sub(r'\$\\to\$', '→', text)

    # --- Step 6: Inline $...$ → \(...\) (multi-line safe, escape-aware) ---
    # Escape-aware: (?:[^$\\]|\\.)+? allows \$ inside math without terminating.
    # e.g., $MC = \$20$ → \(MC = \$20\) — MathJax renders \$ as literal $.
    text = re.sub(
        r'(?<![\\$])\$((?:[^$\\]|\\.)+?)\$',
        r'\\(\1\\)',
        text
    )

    # --- Step 7: Restore escaped dollars outside MathJax ---
    # \$ inside \(...\) stays (MathJax renders \$ as literal $).
    # \$ outside math becomes plain $ for display (e.g., currency \$500 → $500).
    def _restore_outside_math(t: str) -> str:
        parts = re.split(r'(\\\(.*?\\\)|\\\[.*?\\\])', t, flags=re.DOTALL)
        for i in range(0, len(parts), 2):  # Even indices = outside math
            parts[i] = parts[i].replace('\\$', '$')
        return ''.join(parts)

    text = _restore_outside_math(text)

    return text


def protect_math_regions(text: str) -> tuple[str, list[str]]:
    r"""Replace \(...\) and \[...\] with placeholders before LaTeX cleanup.

    Returns (modified_text, list_of_preserved_regions).
    """
    regions: list[str] = []

    def _preserve(match: re.Match) -> str:
        regions.append(match.group(0))
        return f'__MATH_REGION_{len(regions) - 1}__'

    # Protect display math \[...\]
    text = re.sub(r'\\\[.*?\\\]', _preserve, text, flags=re.DOTALL)
    # Protect inline math \(...\)
    text = re.sub(r'\\\(.*?\\\)', _preserve, text, flags=re.DOTALL)

    return text, regions


def restore_math_regions(text: str, regions: list[str]) -> str:
    r"""Restore math regions from placeholders after whitespace handling."""
    for i, region in enumerate(regions):
        text = text.replace(f'__MATH_REGION_{i}__', region)
    return text


def validate_html_fields(fields: list[str], card_id: str) -> list[str]:
    """Warn about non-standard HTML tags before genanki ingestion.

    Returns list of warning messages (empty if clean).
    """
    warnings: list[str] = []
    for i, field in enumerate(fields):
        if not field:
            continue
        tags = re.findall(r'</?([a-zA-Z][a-zA-Z0-9-]*)', field)
        for tag in tags:
            if tag.lower() not in VALID_HTML_TAGS:
                warnings.append(
                    f"[{card_id}] field {i}: unexpected HTML tag <{tag}>"
                )
    return warnings


def convert_latex_to_anki(text: str) -> str:
    """Convert LaTeX markup to Anki-compatible format (MathJax + HTML).

    Handles:
    - Math environments → MathJax delimiters
    - Lists → HTML <ul>/<ol>
    - Formatting → HTML tags
    """
    if not text:
        return text

    # TODO(#2): Refactor into staged pipeline with explicit contracts.
    # Current structure has implicit order dependencies between steps
    # (math, lists, code, cleanup, whitespace).
    # See: https://github.com/brandon-behring/interview_prep_series/issues/2
    # Phase 1 (this PR): math extracted into normalize_math_delimiters().
    # Phase 2 (future): full decomposition into named stages.
    #   normalize_math() → convert_environments() → convert_lists()
    #   → strip_latex() → format_html() → normalize_whitespace()

    # =========================================================================
    # PRE-PROCESSING: Handle special patterns before math conversion
    # =========================================================================

    # Strip \multirow{rows}{width}{content} → just content
    text = re.sub(
        r'\\multirow\{[^}]*\}\{[^}]*\}\{([^}]+)\}',
        r'\1',
        text
    )

    # Note: \text{} is NOT stripped here — it is valid MathJax 3 and renders
    # correctly as upright text inside math regions.  Outside math, the
    # catch-all cleanup (\\[a-zA-Z]+\s*) strips the command,
    # and the \text{} stripping after math-region protection handles the
    # brace argument.  See the block after protect_math_regions() below.
    text = re.sub(r'\\textit\{([^}]+)\}', r'<i>\1</i>', text)
    text = re.sub(r'\\textrm\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', text)

    # =========================================================================
    # MATH DELIMITERS → \(...\) / \[...\]
    # =========================================================================
    text = normalize_math_delimiters(text)

    # =========================================================================
    # LISTS → HTML
    # =========================================================================

    def convert_itemize(match: re.Match) -> str:
        """Convert itemize environment to HTML unordered list."""
        content = match.group(1)
        items = re.split(r'\\item\s*', content)
        items = [item.strip() for item in items if item.strip()]
        if not items:
            return ''
        html_items = ''.join(f'<li>{item}</li>' for item in items)
        return f'<ul>{html_items}</ul>'

    def convert_enumerate(match: re.Match) -> str:
        """Convert enumerate environment to HTML ordered list."""
        content = match.group(1)
        items = re.split(r'\\item\s*', content)
        items = [item.strip() for item in items if item.strip()]
        if not items:
            return ''
        html_items = ''.join(f'<li>{item}</li>' for item in items)
        return f'<ol>{html_items}</ol>'

    text = re.sub(
        r'\\begin\{itemize\}(.*?)\\end\{itemize\}',
        convert_itemize,
        text,
        flags=re.DOTALL
    )

    text = re.sub(
        r'\\begin\{enumerate\}(.*?)\\end\{enumerate\}',
        convert_enumerate,
        text,
        flags=re.DOTALL
    )

    def convert_description(match: re.Match) -> str:
        """Convert description environment to HTML definition list.

        Handles multiple formats:
        1. \\item[label] text - standard LaTeX
        2. - [label:] text - YAML extraction format
        3. - [label:] followed by sub-bullets without brackets
        """
        content = match.group(1)

        # Format 1: Standard LaTeX \item[label] text
        items = re.findall(r'\\item\s*\[([^\]]+)\]\s*([^\\]*?)(?=\\item|\Z)', content, re.DOTALL)
        if items:
            html_items = []
            for term, desc in items:
                term = term.rstrip(':').strip()
                desc = desc.strip()
                if desc:
                    html_items.append(f'<dt><b>{term}</b></dt><dd>{desc}</dd>')
            if html_items:
                return f'<dl style="margin:10px 0">{"".join(html_items)}</dl>'

        # Format 2: YAML format - [label:] followed by content until next - [
        # This handles nested sub-bullets by capturing everything until next labeled item
        items = re.findall(r'-\s*\[([^\]]+)\]\s*(.*?)(?=\n\s*-\s*\[|\Z)', content, re.DOTALL)
        if items:
            html_items = []
            for term, desc in items:
                term = term.rstrip(':').strip()
                desc = desc.strip()
                if desc:
                    # Convert any sub-bullets (lines starting with -) to nested list
                    sub_bullets = re.findall(r'^\s*-\s+(.+)$', desc, re.MULTILINE)
                    if sub_bullets:
                        # If there's text before bullets, include it
                        first_non_bullet = re.split(r'^\s*-\s+', desc, maxsplit=1, flags=re.MULTILINE)[0].strip()
                        if first_non_bullet:
                            desc_html = first_non_bullet + '<ul>'
                        else:
                            desc_html = '<ul>'
                        desc_html += ''.join(f'<li>{b.strip()}</li>' for b in sub_bullets)
                        desc_html += '</ul>'
                        html_items.append(f'<dt><b>{term}</b></dt><dd>{desc_html}</dd>')
                    else:
                        html_items.append(f'<dt><b>{term}</b></dt><dd>{desc}</dd>')
                else:
                    # Label only, no description (will be followed by sub-bullets in next section)
                    html_items.append(f'<dt><b>{term}</b></dt><dd></dd>')
            if html_items:
                return f'<dl style="margin:10px 0">{"".join(html_items)}</dl>'

        # Fallback: Just convert labeled items without requiring content
        simple_items = re.findall(r'-\s*\[([^\]]+)\]', content)
        if simple_items:
            html_parts = []
            for term in simple_items:
                term = term.rstrip(':').strip()
                html_parts.append(f'<br><b>{term}:</b>')
            # Replace original markers with bold labels
            result = content
            for term in simple_items:
                result = re.sub(r'-\s*\[' + re.escape(term) + r'\]\s*', f'<br><b>{term.rstrip(":")}:</b> ', result)
            return result

        return content  # Fallback: return as-is

    text = re.sub(
        r'\\begin\{description\}(.*?)\\end\{description\}',
        convert_description,
        text,
        flags=re.DOTALL
    )

    # Standalone \item not in list → bullet point
    text = re.sub(r'\\item\s*', '• ', text)

    # =========================================================================
    # CODE BLOCKS → HTML
    # =========================================================================

    def convert_code_block(match: re.Match) -> str:
        """Convert verbatim/lstlisting to HTML pre block."""
        content = match.group(1)
        # Escape HTML entities
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre style="background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;font-family:monospace;font-size:13px;line-height:1.4">{content}</pre>'

    # verbatim environment
    text = re.sub(
        r'\\begin\{verbatim\}(.*?)\\end\{verbatim\}',
        convert_code_block,
        text,
        flags=re.DOTALL
    )

    # lstlisting environment (with optional options like [language=python, style=minted])
    # Using [^\]]* instead of .*? for more robust option matching
    text = re.sub(
        r'\\begin\{lstlisting\}(?:\[[^\]]*\])?(.*?)\\end\{lstlisting\}',
        convert_code_block,
        text,
        flags=re.DOTALL
    )

    # minted environment (language in braces, optional [options] before language)
    # Handles: \begin{minted}{python} and \begin{minted}[fontsize=\small]{python}
    text = re.sub(
        r'\\begin\{minted\}(?:\[[^\]]*\])?\{[^}]*\}(.*?)\\end\{minted\}',
        convert_code_block,
        text,
        flags=re.DOTALL
    )

    # Markdown fenced code blocks (canonical format from extract_cards.py)
    # Handles: ```python\n...\n``` and bare ```\n...\n```
    text = re.sub(
        r'```\w*\n?(.*?)\n?```',
        convert_code_block,
        text,
        flags=re.DOTALL
    )

    def convert_code_block_raw(content: str) -> str:
        """Convert raw code content to HTML pre block (for orphaned opening tags)."""
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre style="background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;font-family:monospace;font-size:13px;line-height:1.4">{content}</pre>'

    # Fallback: orphaned opening tags from truncated solutions
    for orphan_pattern in [
        r'\\begin\{minted\}(?:\[[^\]]*\])?\{[^}]*\}\s*(.*)',
        r'\\begin\{lstlisting\}(?:\[[^\]]*\])?\s*(.*)',
        r'```\w*\n?(.*)',
    ]:
        text = re.sub(
            orphan_pattern,
            lambda m: convert_code_block_raw(m.group(1)),
            text,
            flags=re.DOTALL
        )

    # =========================================================================
    # TEXT FORMATTING → HTML
    # =========================================================================

    # Bold: \textbf{...} → <b>...</b>
    text = re.sub(r'\\textbf\{([^}]+)\}', r'<b>\1</b>', text)

    # Emphasis: \emph{...} → <em>...</em>
    text = re.sub(r'\\emph\{([^}]+)\}', r'<em>\1</em>', text)

    # Italic: \textit{...} → <i>...</i>
    text = re.sub(r'\\textit\{([^}]+)\}', r'<i>\1</i>', text)

    # Teletype: \texttt{...} → <code>...</code>
    text = re.sub(r'\\texttt\{([^}]+)\}', r'<code>\1</code>', text)

    # Underline: \underline{...} → <u>...</u>
    text = re.sub(r'\\underline\{([^}]+)\}', r'<u>\1</u>', text)

    # MCQ-aware paragraph break: a line starting with `A.`, `B.`, `C.`, or `D.`
    # (with optional `**` wrapping for the correct answer) is a discrete
    # multiple-choice option, not flowing prose. Promote the preceding single
    # newline to a paragraph break so the later whitespace-collapse step
    # preserves visual separation between options. Without this, the
    # supplement quick-drill cards collapse all options onto one line.
    text = re.sub(r'\n((?:\*\*)?[A-D][.)]\s)', r'\n\n\1', text)

    # Markdown bold: **text** → <b>text</b>
    # (Common in YAML cards from manual authoring)
    #
    # Protect <pre> blocks (code) from the bold regex: Python's `**kwargs` and
    # `x ** 2` would otherwise be matched as bold pairs and corrupt the code.
    # We replace `**` inside `<pre>...</pre>` with a sentinel, run the bold
    # regex on the rest, then restore the literal `**`.
    _PRE_BOLD_SENTINEL = '\x00PRE_BOLD\x00'
    def _protect_pre_stars(m: re.Match) -> str:
        return m.group(0).replace('**', _PRE_BOLD_SENTINEL)
    text = re.sub(r'<pre[^>]*>.*?</pre>', _protect_pre_stars, text, flags=re.DOTALL)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = text.replace(_PRE_BOLD_SENTINEL, '**')

    # =========================================================================
    # SPECIAL CHARACTERS
    # =========================================================================

    # Quotes
    text = text.replace('``', '"').replace("''", '"')

    # =========================================================================
    # MARKDOWN TABLES → HTML (must happen BEFORE dash conversion)
    # =========================================================================
    # Process Markdown tables early because |---|---| separator uses hyphens
    # that would otherwise be converted to em-dashes

    def convert_markdown_table_early(text: str) -> str:
        """Convert Markdown-style pipe tables to HTML."""
        lines = text.split('\n')
        result_lines = []
        table_buffer = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            is_table_row = (
                stripped.startswith('|') and
                stripped.endswith('|') and
                stripped.count('|') >= 3
            )

            if is_table_row:
                if not in_table:
                    in_table = True
                table_buffer.append(stripped)
            else:
                if in_table and len(table_buffer) >= 2:
                    html_table = _markdown_table_to_html_early(table_buffer)
                    result_lines.append(html_table)
                elif table_buffer:
                    result_lines.extend(table_buffer)

                table_buffer = []
                in_table = False
                result_lines.append(line)

        if in_table and len(table_buffer) >= 2:
            html_table = _markdown_table_to_html_early(table_buffer)
            result_lines.append(html_table)
        elif table_buffer:
            result_lines.extend(table_buffer)

        return '\n'.join(result_lines)

    def _markdown_table_to_html_early(rows: list) -> str:
        """Convert Markdown table rows to HTML table."""
        html_rows = []
        has_separator = len(rows) > 1 and re.match(r'^[-:\s|]+$', rows[1])

        if has_separator and len(rows) >= 2:
            header_row = rows[0]
            data_rows = rows[2:]
        else:
            header_row = rows[0]
            data_rows = rows[1:]

        # Header
        cells = [c.strip() for c in header_row.split('|')[1:-1]]
        html_cells = ''.join(
            f'<th style="padding:8px;border-bottom:2px solid #333;text-align:left;background:#f5f5f5">{cell}</th>'
            for cell in cells
        )
        html_rows.append(f'<tr>{html_cells}</tr>')

        # Data
        for row in data_rows:
            cells = [c.strip() for c in row.split('|')[1:-1]]
            html_cells = ''.join(
                f'<td style="padding:6px;border-bottom:1px solid #ddd">{cell}</td>'
                for cell in cells
            )
            html_rows.append(f'<tr>{html_cells}</tr>')

        return f'<table style="border-collapse:collapse;margin:10px 0;width:100%">{"".join(html_rows)}</table>'

    text = convert_markdown_table_early(text)

    # ---- Loose Markdown tables (without leading/trailing pipes) --------
    # Many YAML cards use "Name | Value | Desc" format (no leading |)
    # and no separator line (---|---).  The strict parser above requires
    # leading + trailing pipes.  This second pass detects tables by
    # finding 2+ lines with 2+ pipe characters and consistent column
    # counts.  Must run BEFORE em-dash conversion (--- → —).

    def _is_pipe_table_row(line: str) -> bool:
        """Return True if line looks like a pipe-delimited table row."""
        stripped = line.strip()
        if not stripped or stripped.count('|') < 2:
            return False
        # Skip lines already converted to HTML
        if '<table' in stripped or '<tr' in stripped:
            return False
        # Skip separator-only lines (will be consumed but not counted)
        if re.match(r'^[-:\s|]+$', stripped):
            return False
        return True

    def _is_separator_line(line: str) -> bool:
        """Return True if line is a markdown table separator (---|---)."""
        stripped = line.strip()
        return bool(
            stripped
            and re.match(r'^[-:\s|]+$', stripped)
            and '---' in stripped
            and '|' in stripped
        )

    def convert_loose_markdown_table(text: str) -> str:
        """Convert pipe-separated tables (no leading pipes, no separator)."""
        lines = text.split('\n')
        result = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()

            if _is_pipe_table_row(stripped):
                # Potential table start — collect consecutive pipe rows
                # (allow blank lines and separator lines between rows)
                table_rows = [stripped]
                j = i + 1
                while j < len(lines):
                    next_s = lines[j].strip()
                    if not next_s:
                        # Blank line — peek ahead for more table rows
                        peek = j + 1
                        while peek < len(lines) and not lines[peek].strip():
                            peek += 1
                        if peek < len(lines) and _is_pipe_table_row(lines[peek].strip()):
                            j = peek
                            continue
                        break
                    elif _is_separator_line(next_s):
                        j += 1  # Skip separator, keep collecting
                        continue
                    elif _is_pipe_table_row(next_s):
                        table_rows.append(next_s)
                        j += 1
                    else:
                        break

                if len(table_rows) >= 2:
                    html = _loose_table_to_html(table_rows[0], table_rows[1:])
                    result.append(html)
                    i = j
                    continue

            result.append(lines[i])
            i += 1
        return '\n'.join(result)

    def _loose_table_to_html(header_line: str, data_lines: list) -> str:
        """Convert header + data rows (without mandatory leading pipes) to HTML."""
        def _parse_cells(line: str) -> list:
            cells = [c.strip() for c in line.split('|')]
            # Strip empty edge cells from optional leading/trailing pipes
            if cells and not cells[0]:
                cells = cells[1:]
            if cells and not cells[-1]:
                cells = cells[:-1]
            return cells

        header_cells = _parse_cells(header_line)
        html_rows = []
        # Header
        html_rows.append('<tr>' + ''.join(
            f'<th style="padding:8px;border-bottom:2px solid #333;'
            f'text-align:left;background:#f5f5f5">{c}</th>'
            for c in header_cells
        ) + '</tr>')
        # Data
        for row in data_lines:
            cells = _parse_cells(row)
            html_rows.append('<tr>' + ''.join(
                f'<td style="padding:6px;border-bottom:1px solid #ddd">{c}</td>'
                for c in cells
            ) + '</tr>')
        return (
            '<table style="border-collapse:collapse;margin:10px 0;width:100%">'
            + ''.join(html_rows)
            + '</table>'
        )

    text = convert_loose_markdown_table(text)

    # Dashes (AFTER Markdown tables to preserve |---|---|)
    text = re.sub(r'---', '—', text)  # Em dash
    text = re.sub(r'--', '–', text)   # En dash

    # Non-breaking space
    text = re.sub(r'~', ' ', text)

    # =========================================================================
    # TABLES & ENVIRONMENTS (must happen before \\\\ → <br>)
    # =========================================================================

    # Remove table wrapper first, keep inner content (tabular/tabularx)
    text = re.sub(
        r'\\begin\{table\}(?:\[[^\]]*\])?\s*(?:\\centering\s*)?(.*?)\\end\{table\}',
        r'\1',
        text,
        flags=re.DOTALL
    )

    def convert_tabular(match: re.Match) -> str:
        """Convert tabular/tabularx to HTML table with booktabs styling.

        Handles both:
        - Multi-line format: rows separated by \\\\ (newlines)
        - Single-line format: rows separated by booktabs commands (\\midrule, etc.)
        """
        content = match.group(1)  # Content inside tabular

        # Track if this is a booktabs-style table (has header)
        has_header = '\\toprule' in content or '\\midrule' in content

        # Try splitting by \\ (LaTeX row break)
        rows = re.split(r'\\\\', content)

        # If only 1 row but has \\midrule, it's a collapsed single-line table
        # Split by booktabs commands instead
        if len(rows) <= 1 and has_header:
            # Single-line format: content between booktabs markers
            # Remove \toprule and \bottomrule, split by \midrule
            content_clean = re.sub(r'\\toprule\s*', '', content)
            content_clean = re.sub(r'\\bottomrule\s*', '', content_clean)
            parts = re.split(r'\\midrule\s*', content_clean)

            if len(parts) >= 2:
                # First part = header row, rest = data rows
                header_text = parts[0].strip()
                data_text = ' '.join(parts[1:]).strip()

                # Now we need to parse cells - they're separated by &
                # Data rows might be space-separated or identifiable by patterns
                header_cells = [c.strip() for c in header_text.split('&')]

                # For data: try to split into rows based on number of cells in header
                num_cols = len(header_cells)
                data_cells = [c.strip() for c in data_text.split('&')]

                # Group data cells into rows
                data_rows = []
                for i in range(0, len(data_cells), num_cols):
                    row = data_cells[i:i + num_cols]
                    if len(row) == num_cols:
                        data_rows.append(row)

                # Build HTML
                html_rows = []
                html_cells = ''.join(
                    f'<th style="padding:8px;border-bottom:2px solid #333;text-align:left;background:#f5f5f5">{cell}</th>'
                    for cell in header_cells
                )
                html_rows.append(f'<tr>{html_cells}</tr>')

                for row in data_rows:
                    html_cells = ''.join(
                        f'<td style="padding:6px;border-bottom:1px solid #ddd">{cell}</td>'
                        for cell in row
                    )
                    html_rows.append(f'<tr>{html_cells}</tr>')

                return f'<table style="border-collapse:collapse;margin:10px 0;width:100%">{"".join(html_rows)}</table>'

        # Standard multi-line format
        # Clean rows - remove booktabs commands
        cleaned_rows = []
        for row in rows:
            row = re.sub(r'\\(?:hline|toprule|midrule|bottomrule)', '', row).strip()
            if row:
                cleaned_rows.append(row)

        if not cleaned_rows:
            return ''

        html_rows = []
        for i, row in enumerate(cleaned_rows):
            cells = [cell.strip() for cell in row.split('&')]
            # First row in booktabs table = header
            if has_header and i == 0:
                html_cells = ''.join(
                    f'<th style="padding:8px;border-bottom:2px solid #333;text-align:left;background:#f5f5f5">{cell}</th>'
                    for cell in cells
                )
                html_rows.append(f'<tr>{html_cells}</tr>')
            else:
                html_cells = ''.join(
                    f'<td style="padding:6px;border-bottom:1px solid #ddd">{cell}</td>'
                    for cell in cells
                )
                html_rows.append(f'<tr>{html_cells}</tr>')

        return f'<table style="border-collapse:collapse;margin:10px 0;width:100%">{"".join(html_rows)}</table>'

    # Step 1: Handle tabular with robust column spec parsing
    # The simple regex [^}]* fails on nested braces like {|l|p{3cm}|}
    # Instead, extract content from booktabs markers (toprule/hline) to end
    def convert_tabular_full(match: re.Match) -> str:
        """Convert tabular by extracting content starting from booktabs markers.

        This avoids parsing the column spec which can have nested braces.
        """
        full_match = match.group(0)

        # Find content starting from \toprule, \hline, or first data
        content_match = re.search(
            r'(\\(?:toprule|hline).*?)\\end\{tabular\}',
            full_match,
            re.DOTALL
        )
        if not content_match:
            # No booktabs - try to find content after the column spec
            # Match everything after \begin{tabular}{...} to \end{tabular}
            # Use a balanced brace approach: find first { after tabular, then content
            content_match = re.search(
                r'\\begin\{tabular\}\{(?:[^{}]|\{[^{}]*\})*\}(.*?)\\end\{tabular\}',
                full_match,
                re.DOTALL
            )
        if not content_match:
            return full_match  # Can't parse, return as-is

        content = content_match.group(1).strip()

        # Call tabular converter with fake match
        class FakeMatch:
            def group(self, n):
                return content
        return convert_tabular(FakeMatch())

    # Match tabular with any format
    text = re.sub(
        r'\\begin\{tabular\}.*?\\end\{tabular\}',
        convert_tabular_full,
        text,
        flags=re.DOTALL
    )

    # tabularx: handle various column spec formats including @{} patterns
    def convert_tabularx_full(match: re.Match) -> str:
        """Convert tabularx by extracting content starting from \\toprule or \\hline."""
        full_match = match.group(0)

        # Find content starting from \toprule, \hline, or first data cell
        # This skips the preamble regardless of column spec complexity
        content_match = re.search(
            r'(\\(?:toprule|hline).*?)\\end\{tabularx\}',
            full_match,
            re.DOTALL
        )
        if not content_match:
            # No booktabs - try to find content after last } before \end
            content_match = re.search(
                r'\}\s*([^\\].*?)\\end\{tabularx\}',
                full_match,
                re.DOTALL
            )
        if not content_match:
            return full_match  # Can't parse, return as-is

        content = content_match.group(1).strip()

        # Call tabular converter with fake match
        class FakeMatch:
            def group(self, n):
                return content
        return convert_tabular(FakeMatch())

    # Match tabularx with any format (single-line or multi-line)
    text = re.sub(
        r'\\begin\{tabularx\}.*?\\end\{tabularx\}',
        convert_tabularx_full,
        text,
        flags=re.DOTALL
    )

    # Center environment → just remove wrapper (content stays)
    text = re.sub(
        r'\\begin\{center\}(.*?)\\end\{center\}',
        r'\1',
        text,
        flags=re.DOTALL
    )

    # Multicols → remove wrapper
    text = re.sub(
        r'\\begin\{multicols\}\{[^}]*\}(.*?)\\end\{multicols\}',
        r'\1',
        text,
        flags=re.DOTALL
    )

    # =========================================================================
    # SPECIAL CHARACTERS (after tables, before cleanup)
    # =========================================================================

    # Escaped characters
    text = re.sub(r'\\%', '%', text)
    text = re.sub(r'\\&', '&amp;', text)
    text = re.sub(r'\\#', '#', text)
    text = re.sub(r'\\_', '_', text)
    text = re.sub(r'\\{', '{', text)
    text = re.sub(r'\\}', '}', text)

    # LaTeX line breaks → HTML (AFTER tables processed)
    text = re.sub(r'\\\\', '<br>', text)

    # =========================================================================
    # CLEANUP - CONTEXT AWARE
    # =========================================================================

    # Protect math regions before stripping LaTeX commands
    text, math_regions = protect_math_regions(text)

    # Strip \text{content} → content OUTSIDE math regions.
    # Inside math, \text{} is safely hidden in __MATH_REGION__ placeholders
    # and will be restored intact for MathJax 3 (which handles it natively).
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)

    # Protect code blocks BEFORE cleanup (prevents {} stripping inside code)
    code_regions = []

    def preserve_code_block(match: re.Match) -> str:
        """Preserve code block content by replacing with placeholder."""
        code_regions.append(match.group(0))
        return f'__CODE_REGION_{len(code_regions) - 1}__'

    # Protect <pre>...</pre> blocks (from minted, lstlisting, verbatim, markdown fences)
    text = re.sub(
        r'<pre[^>]*>.*?</pre>',
        preserve_code_block,
        text,
        flags=re.DOTALL
    )

    # Now safe to remove remaining LaTeX commands outside math/code
    text = re.sub(r'\\[a-zA-Z]+\s*', '', text)

    # Remove leftover braces from commands
    text = re.sub(r'\{\}', '', text)

    # =========================================================================
    # HTML SAFETY (avoid accidental tags/entities)
    # =========================================================================

    # Escape raw ampersands not already part of an entity.
    text = re.sub(r'&(?![a-zA-Z]+;|#\d+;)', '&amp;', text)

    # Escape '<' unless it starts an HTML tag like <b>, </b>, <br>, <table>, etc.
    text = re.sub(r'<(?![a-zA-Z/])', '&lt;', text)

    # =========================================================================
    # WHITESPACE HANDLING (preserve intentional structure)
    # =========================================================================

    # Step 4: Clean excessive newlines in lists (YAML extraction artifact)
    # Remove blank lines between list items: </li>\n\n<li> → </li><li>
    text = re.sub(r'</li>\s*\n\s*\n+\s*<li>', '</li><li>', text)
    # Also clean blank lines in definition lists
    text = re.sub(r'</dd>\s*\n\s*\n+\s*<dt>', '</dd><dt>', text)

    # Preserve paragraph breaks (double newline) before collapsing whitespace
    text = re.sub(r'\n\n+', '__PARA_BREAK__', text)

    # Single newlines become spaces
    text = re.sub(r'\n', ' ', text)

    # Collapse multiple spaces
    text = re.sub(r' +', ' ', text).strip()

    # Restore paragraph breaks as HTML
    text = text.replace('__PARA_BREAK__', '<br><br>')

    # Restore math regions AFTER whitespace handling to prevent <br><br>
    # from appearing inside \[...\] display math blocks
    text = restore_math_regions(text, math_regions)

    # Restore code blocks with preserved formatting
    for i, region in enumerate(code_regions):
        text = text.replace(f'__CODE_REGION_{i}__', region)

    # Step 5: Section header handling - ensure bold headers get line break after
    # Prevents "**Header:**Content" run-on patterns
    text = re.sub(r'</b>([A-Za-z])', r'</b><br>\1', text)

    # Clean up excessive <br> tags (more than 2 in a row)
    text = re.sub(r'(<br>){3,}', '<br><br>', text)

    # =========================================================================
    # FINAL: Unescape HTML entities for display
    # =========================================================================
    # Source YAML often has &amp; from LaTeX extraction
    # These should display as & in Anki

    # Unescape &amp; to & but only when not followed by entity pattern
    # e.g., &amp;nbsp; should stay, but "Question &amp; Answer" → "Question & Answer"
    text = re.sub(r'&amp;(?![a-zA-Z]+;|#\d+;)', '&', text)

    # Note: We do NOT unescape &lt; and &gt; because:
    # 1. They often represent math comparisons (p < 0.01) which look fine as &lt;
    # 2. Unescaping creates invalid HTML tags that genanki warns about
    # The &lt; rendering in Anki looks identical to < for the user

    return text


def create_basic_model() -> genanki.Model:
    """Create a basic front/back model for interview prep cards."""
    return genanki.Model(
        MODEL_ID_BASIC,
        'Course Learning Basic',
        fields=[
            {'name': 'Front'},
            {'name': 'Back'},
            {'name': 'Source'},
            {'name': 'CardID'},
        ],
        templates=[
            {
                'name': 'Card 1',
                'qfmt': '''
                    <div class="front">{{Front}}</div>
                    <div class="source">{{Source}}</div>
                ''',
                'afmt': '''
                    <div class="front">{{Front}}</div>
                    <hr id="answer">
                    <div class="back">{{Back}}</div>
                    <div class="source">{{Source}}</div>
                ''',
            },
        ],
        css='''
            .card {
                font-family: Georgia, serif;
                font-size: 18px;
                text-align: left;
                color: #333;
                background-color: #fefefe;
                padding: 20px;
            }
            .front {
                font-weight: bold;
                color: #005293;
                margin-bottom: 10px;
            }
            .back {
                line-height: 1.5;
            }
            .back ul, .back ol {
                margin: 10px 0;
                padding-left: 25px;
            }
            .back li {
                margin: 5px 0;
            }
            .source {
                font-size: 12px;
                color: #888;
                margin-top: 15px;
                font-style: italic;
            }
            code {
                background: #f4f4f4;
                padding: 2px 5px;
                border-radius: 3px;
                font-family: monospace;
            }
            pre {
                background: #f4f4f4;
                padding: 10px;
                border-radius: 4px;
                overflow-x: auto;
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: 'Courier New', Courier, monospace;
                font-size: 13px;
                line-height: 1.4;
                max-width: 100%;
            }
            /* Tables with booktabs styling */
            table {
                border-collapse: collapse;
                margin: 10px 0;
                width: 100%;
            }
            th {
                background: #f5f5f5;
                padding: 8px;
                border-bottom: 2px solid #333;
                text-align: left;
                font-weight: bold;
            }
            td {
                padding: 6px;
                border-bottom: 1px solid #ddd;
            }
            /* Definition lists */
            dl {
                margin: 10px 0;
            }
            dt {
                font-weight: bold;
                margin-top: 8px;
                color: #005293;
            }
            dd {
                margin-left: 20px;
                margin-bottom: 4px;
            }
        '''
    )


def create_cloze_model() -> genanki.Model:
    """Create a cloze deletion model for formula/procedure cards."""
    return genanki.Model(
        MODEL_ID_CLOZE,
        'Course Learning Cloze',
        model_type=genanki.Model.CLOZE,
        fields=[
            {'name': 'Text'},
            {'name': 'Source'},
            {'name': 'CardID'},
        ],
        templates=[
            {
                'name': 'Cloze',
                'qfmt': '{{cloze:Text}}<div class="source">{{Source}}</div>',
                'afmt': '{{cloze:Text}}<div class="source">{{Source}}</div>',
            },
        ],
        css='''
            .card {
                font-family: Georgia, serif;
                font-size: 18px;
                text-align: left;
                color: #333;
                background-color: #fefefe;
                padding: 20px;
            }
            .cloze {
                font-weight: bold;
                color: #005293;
            }
            .source {
                font-size: 12px;
                color: #888;
                margin-top: 15px;
                font-style: italic;
            }
            pre {
                background: #f4f4f4;
                padding: 10px;
                border-radius: 4px;
                overflow-x: auto;
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: 'Courier New', Courier, monospace;
                font-size: 13px;
                line-height: 1.4;
                max-width: 100%;
            }
        '''
    )


def generate_card_guid(card_id: str) -> str:
    """Generate a stable GUID for a card based on its ID."""
    return hashlib.md5(card_id.encode()).hexdigest()[:10]


def sanitize_tags(tags: list[str]) -> list[str]:
    """Sanitize tags for Anki (no spaces allowed).

    Replaces spaces with underscores, strips empty tags.
    """
    sanitized: list[str] = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            continue
        # Replace spaces, slashes, dashes that create problems
        clean = tag.strip().replace(" ", "_").replace("/", "_").replace("---", "-")
        sanitized.append(clean)
    return sanitized


def create_note(card: dict[str, Any], basic_model: genanki.Model) -> genanki.Note:
    """Create an Anki note from a card definition."""
    card_id = card.get('id', f"CARD-{random.randint(10000, 99999)}")
    source = card.get('source', 'unknown')
    tags = sanitize_tags(card.get('tags', []))

    # Convert LaTeX to Anki-compatible format
    front = convert_latex_to_anki(card.get('front', ''))
    back = convert_latex_to_anki(card.get('back', ''))

    # Validate HTML before genanki ingestion
    fields = [front, back, source, card_id]
    warnings = validate_html_fields(fields, card_id)
    for w in warnings:
        print(f"  WARNING: {w}", file=sys.stderr)

    return genanki.Note(
        model=basic_model,
        fields=fields,
        tags=tags,
        guid=generate_card_guid(card_id)
    )


def generate_deck_id(deck_name: str) -> int:
    """Generate a stable deck ID from the deck name."""
    return DECK_ID_BASE + int(hashlib.md5(deck_name.encode()).hexdigest()[:8], 16) % 1000000


def load_cards_from_yaml(filepath: Path) -> list[dict[str, Any]]:
    """Load cards from a YAML file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict):
        # Combined file format with 'cards' key
        if 'cards' in data:
            return data['cards']
        # Per-file format
        elif 'cards' in data.get('cards', {}):
            return data['cards']
        else:
            return data.get('cards', [])
    elif isinstance(data, list):
        return data
    else:
        return []


from tooling import paths  # noqa: E402


def find_all_card_yamls() -> list[Path]:
    """Discover all all_cards.yml files across course guides (guide/ layout)."""
    return sorted(paths.host_root().glob("*/guide/cards/all_cards.yml"))


def generate_single_deck(
    yaml_files: list[Path],
    output_path: Path,
    deck_name: str | None = None,
    verbose: bool = False,
) -> int:
    """Generate a single .apkg deck from one or more YAML files.

    Returns:
        Number of cards added.
    """
    name = deck_name or output_path.stem.replace("_", " ").title()
    deck_id = generate_deck_id(name)
    deck = genanki.Deck(deck_id, name)
    basic_model = create_basic_model()

    total_cards = 0
    for filepath in yaml_files:
        if not filepath.exists():
            print(f"Warning: File not found: {filepath}", file=sys.stderr)
            continue
        if verbose:
            print(f"Processing: {filepath}")

        cards = load_cards_from_yaml(filepath)
        for card in cards:
            note = create_note(card, basic_model)
            deck.add_note(note)
            total_cards += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    package = genanki.Package(deck)
    package.write_to_file(str(output_path))

    print(f"  {name}: {total_cards} cards -> {output_path}")
    return total_cards


def main():
    parser = argparse.ArgumentParser(
        description="Generate Anki decks from YAML card definitions",
    )
    parser.add_argument(
        "files", nargs="*", help="YAML files to process (or use --all)",
    )
    parser.add_argument(
        "-o", "--output", default=None, help="Output .apkg file (single deck mode)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Generate per-guide decks for all guides with cards",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Output directory for --all mode (default: output/)",
    )
    parser.add_argument(
        "--deck-name", default=None, help="Custom deck name",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print detailed generation info",
    )
    args = parser.parse_args()

    if args.all:
        # Per-guide deck generation
        yaml_files = find_all_card_yamls()
        if not yaml_files:
            print("No card files found across guides.", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        total = 0
        for yaml_path in yaml_files:
            guide_name = yaml_path.relative_to(paths.host_root()).parts[0]  # slug
            out_path = output_dir / f"{guide_name}.apkg"
            deck_name = guide_name.replace("_", " ").title()
            total += generate_single_deck(
                [yaml_path], out_path, deck_name, verbose=args.verbose,
            )

        print(f"\nGenerated {len(yaml_files)} decks, {total} total cards")

    elif args.files:
        # Single deck mode
        if not args.output:
            print("Error: -o/--output required for single deck mode", file=sys.stderr)
            sys.exit(1)

        file_paths: list[Path] = []
        for file_pattern in args.files:
            if "*" in file_pattern:
                file_paths.extend(Path(".").glob(file_pattern))
            else:
                file_paths.append(Path(file_pattern))

        output_path = Path(args.output)
        total = generate_single_deck(
            file_paths, output_path, args.deck_name, verbose=args.verbose,
        )
        print(f"\nGenerated deck: {total} cards -> {output_path}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
