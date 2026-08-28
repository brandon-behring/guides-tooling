#!/usr/bin/env python3
r"""Shared LaTeX text helpers for the validators (single source — guides-tooling#4).

Hoisted out of ``check_refs.py`` / ``extract_los.py`` (which carried byte-identical copies that would
drift) so the comment scanner has ONE home. It is intentionally a small char-walk, NOT a full LaTeX
tokenizer: it handles the two cases the validators actually hit — an escaped percent (backslash
parity) and a literal percent inside a url-family argument — and documents the rest as out of scope.
"""
from __future__ import annotations

import re
from typing import Iterable, Iterator

# url-family commands whose first ``{...}`` argument may legitimately contain a literal ``%`` (URL
# percent-encoding, e.g. ``\url{http://x/a%20b}``); there ``%`` is NOT a comment start.
_URL_CMDS: tuple[str, ...] = ("url", "nolinkurl", "path", "href")


def _skip_url_group(line: str, i: int) -> int | None:
    r"""If ``line[i:]`` begins with a url-family command + ``{``, return the index just past the
    matching ``}`` so its content is consumed verbatim (``%`` and all); else ``None``.

    Only the FIRST brace-group is skipped — enough for ``\url{u}`` / ``\path{p}`` and the URL arg of
    ``\href{u}{text}`` (the trailing text arg then scans normally, where ``%`` IS a comment). An
    unclosed group (multi-line url, rare) consumes to end-of-line.
    """
    if line[i] != "\\":
        return None
    for cmd in _URL_CMDS:
        if line.startswith("\\" + cmd + "{", i):
            j = i + len(cmd) + 2  # past ``\<cmd>{``
            depth = 1
            while j < len(line) and depth:
                if line[j] == "{":
                    depth += 1
                elif line[j] == "}":
                    depth -= 1
                j += 1
            return j
    return None


def _strip_line(line: str) -> str:
    """Return *line* truncated at its first real comment ``%`` (see :func:`strip_latex_comments`)."""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            url_end = _skip_url_group(line, i)
            if url_end is not None:
                i = url_end  # the url argument is verbatim; resume scanning after its ``}``
                continue
            i += 2  # consume the escaped pair ``\x`` — so ``\%`` is literal and ``\\`` is a unit,
            continue  # which makes an EVEN run of backslashes leave ``%`` exposed (a comment)
        if ch == "%":
            return line[:i]
        i += 1
    return line


def strip_latex_comments(content: str) -> str:
    r"""Blank out LaTeX comments (an unescaped ``%`` to end-of-line), preserving line structure.

    A ``%`` starts a comment UNLESS:

    - it is escaped — preceded by an ODD number of backslashes, so ``\%`` is a literal percent but
      ``\\%`` (a line-break ``\\`` *then* a comment) IS a comment (guides-tooling#4 p11/p12/p15); or
    - it sits inside the first ``{...}`` of a url-family command (``\url{…%…}``), where ``%`` is a
      literal percent-encoding byte.

    Newlines are preserved so line numbers and multi-line bodies are unaffected. Pragmatic scanner,
    not a full LaTeX tokenizer (``\verb|%|`` and ``verbatim`` environments are out of scope).
    """
    return "\n".join(_strip_line(ln) for ln in content.split("\n"))


def iter_macro_args(text: str, names: Iterable[str]) -> Iterator[tuple[str, str, int]]:
    r"""Yield ``(macro, payload, offset)`` for every ``\<name>{...}`` whose braces balance.

    A brace-balanced char walk, not a regex to end-of-line (gt#33 row 9): the payload may wrap
    across lines and may contain nested groups (``\textbf{...}``, ``$\mathrm{Beta}(4,2)$``,
    ``\{`` / ``\}`` escapes) -- all of which a ``\}\s*$``-anchored pattern truncates or misses.

    - ``names`` are bare macro names (``"interviewmargin"``); the match requires the opening
      brace immediately after the name (optional whitespace), so ``\interviewmarginx{``
      is not a hit.
    - A backslash escapes the next character, so ``\{`` and ``\}`` never change the depth and
      ``\\`` is consumed as a unit.
    - An unterminated argument (EOF before the matching ``}``) is skipped, not yielded.
    - Comments are NOT stripped here; pass comment-stripped text (:func:`strip_latex_comments`)
      when a commented-out macro must not count.

    ``offset`` is the index of the backslash that starts the macro (for line-number reporting).

    >>> list(iter_macro_args(r"\patternmargin{a \textbf{b} c}", ["patternmargin"]))
    [('patternmargin', 'a \\textbf{b} c', 0)]
    """
    alts = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    if not alts:
        return
    head = re.compile(r"\\(" + alts + r")\s*\{")
    n = len(text)
    for m in head.finditer(text):
        depth, i, start = 1, m.end(), m.end()
        while i < n:
            c = text[i]
            if c == "\\":
                i += 2  # escaped pair: \{ \} \\ \% -- never a delimiter
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield m.group(1), text[start:i], m.start()
                    break
            i += 1
