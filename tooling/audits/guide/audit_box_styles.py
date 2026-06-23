#!/usr/bin/env python3
r"""Audit that every custom tcolorbox style a guide USES is also DEFINED.

The callout boxes (``narrativebox``, ``checkpointbox``, ``debugbox``,
``conceptbox``, ``decisionbox``, ...) are defined per-guide in
``guide/notebook-extensions.sty`` (a couple more live in the shared
``tooling/latex/*.sty``). Each guide's sty defines only a SUBSET, so a scaffolded
chapter can use a style the guide's sty never defines, e.g.::

    \begin{tcolorbox}[narrativebox, title=...]   % but narrativebox/.style undefined

which fails the build with ``Package pgfkeys Error: I do not know the key
'/tcb/narrativebox'`` -- a latent error the OLD static audit never compiled and so
never saw (python_workout_2e had 13 of these). This audit catches that class
STATICALLY (no build): for each ``\begin{tcolorbox}[...]``, every bare option
token that is a KNOWN custom style (defined by some guide / the shared sty) must
be defined for THIS guide. Built-in tcolorbox keys (``breakable``, ``title=...``)
are ignored because they are not in the custom-style universe.

Usage:
    python -m tooling.audits.guide.audit_box_styles --guide <slug>
    python -m tooling.audits.guide.audit_box_styles --guide <slug> --strict
    python -m tooling.audits.guide.audit_box_styles --guide <slug> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from tooling import discovery, paths
from tooling.audits.guide._guide_scope import guide_dir_for_slug

_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
_STYLE_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9]*)/\.style\b")        # only WITHIN a \tcbset{}
_NEWBOX_RE = re.compile(r"\\newtcolorbox\{([a-zA-Z][a-zA-Z0-9]*)\}")
_TCBSET_RE = re.compile(r"\\tcbset\{")
_BEGIN_RE = re.compile(r"\\begin\{tcolorbox\}\[")
# Strip a LaTeX line comment (% to end of line, but not an escaped \%), so a
# commented-out \begin{tcolorbox}[...] / \tcbset example is not scanned.
_COMMENT_RE = re.compile(r"(?<!\\)%.*")


def _matched_group(text: str, open_pos: int, open_c: str = "{", close_c: str = "}") -> int:
    """Index just past the ``close_c`` that matches the bracket/brace at ``open_pos``."""
    depth, j = 0, open_pos
    while j < len(text):
        c = text[j]
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


def _styles_in(text: str) -> set[str]:
    r"""Custom box styles DEFINED in ``text``: every ``NAME/.style`` inside a
    (brace-matched) ``\tcbset{...}`` block + every ``\newtcolorbox{NAME}``. Scoping
    ``/.style`` to ``\tcbset`` is essential — a shared ``\tikzset{ every node/.style
    ...}`` or a tikzpicture option must NOT register ``node`` as a tcolorbox style."""
    out = set(_NEWBOX_RE.findall(text))
    for m in _TCBSET_RE.finditer(text):
        end = _matched_group(text, m.end() - 1)        # the '{' of \tcbset{
        out |= set(_STYLE_RE.findall(text[m.end():end]))
    return out


def _split_top_commas(s: str) -> list[str]:
    """Split on commas at brace depth 0 (so ``title={a, b}`` stays one token)."""
    parts, buf, depth = [], [], 0
    for c in s:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
    parts.append("".join(buf))
    return parts


def _read(p: Path) -> str:
    try:
        return _COMMENT_RE.sub("", p.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""


@lru_cache(maxsize=1)
def _shared_styles() -> frozenset[str]:
    """Custom styles defined in the shared ``tooling/latex/*.sty`` (every guide)."""
    latex = paths.host_root() / "tooling" / "latex"
    out: set[str] = set()
    for sty in latex.glob("*.sty"):
        out |= _styles_in(_read(sty))
    return frozenset(out)


@lru_cache(maxsize=1)
def _universe() -> frozenset[str]:
    """Every custom style name defined ANYWHERE (shared + any guide's sty).

    Used to tell a custom style (check it) from a built-in tcolorbox key (ignore)."""
    out = set(_shared_styles())
    for gd in discovery.iter_guide_dirs():
        out |= _styles_in(_read(gd / "guide" / "notebook-extensions.sty"))
    return frozenset(out)


def _defined_styles(guide_dir: Path) -> set[str]:
    """Styles available to this guide: shared + its own notebook-extensions.sty."""
    return set(_shared_styles()) | _styles_in(_read(guide_dir / "guide" / "notebook-extensions.sty"))


def _used_styles(guide_dir: Path) -> set[str]:
    """Bare custom-style tokens used in any \\begin{tcolorbox}[...] of the guide.

    Bracket-aware: the option list is read to the ``]`` that matches at brace
    depth 0, so a nested ``title={Array [i] {x}}`` never truncates the scan."""
    used: set[str] = set()
    g = guide_dir / "guide"
    for tex in list(g.glob("chapters/*.tex")) + list(g.glob("appendices/*.tex")):
        text = _read(tex)
        for m in _BEGIN_RE.finditer(text):
            end = _matched_group(text, m.end() - 1, "[", "]")   # the '[' of [...]
            opts = text[m.end():end - 1]
            for tok in _split_top_commas(opts):
                tok = tok.strip()
                if tok and "=" not in tok and _NAME_RE.fullmatch(tok):
                    used.add(tok)
    return used


def find_undefined_box_styles(guide_dir: Path) -> list[str]:
    """Custom styles the guide USES (and that exist somewhere) but does not DEFINE."""
    return sorted((_used_styles(guide_dir) & _universe()) - _defined_styles(guide_dir))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit that every custom tcolorbox style used is defined")
    ap.add_argument("--guide", required=True, help="guide slug to audit")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", "--check", dest="strict", action="store_true",
                    help="exit 1 if any used custom box style is undefined")
    args = ap.parse_args()

    guide_dir = guide_dir_for_slug(args.guide)
    if guide_dir is None or not guide_dir.is_dir():
        print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
        sys.exit(2)

    undefined = find_undefined_box_styles(guide_dir)

    if args.json:
        print(json.dumps({"slug": args.guide, "undefined_styles": undefined}, indent=2))
    elif undefined:
        print(f"{args.guide}: {len(undefined)} undefined tcolorbox style(s): {', '.join(undefined)}")
    else:
        print(f"PASS  {args.guide}: all used tcolorbox styles are defined")

    if args.strict and undefined:
        print(f"FAIL  {args.guide}: tcolorbox style(s) used but not defined "
              f"(add to notebook-extensions.sty): {', '.join(undefined)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
