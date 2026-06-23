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

# A custom style is defined via \tcbset{NAME/.style={...}} or \newtcolorbox{NAME}.
_DEF_RE = re.compile(r"\\(?:tcbset\{\s*|newtcolorbox\{)([a-zA-Z][a-zA-Z0-9]*)(?:/\.style|\})")
# Capture the full option list of each \begin{tcolorbox}[...].
_BEGIN_RE = re.compile(r"\\begin\{tcolorbox\}\[([^\]]*)\]", re.DOTALL)
# A bare option token (a style name, not a key=value built-in).
_BARE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9]*$")


def _styles_in(text: str) -> set[str]:
    return set(_DEF_RE.findall(text))


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
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
    """Bare custom-style tokens used in any \\begin{tcolorbox}[...] of the guide."""
    used: set[str] = set()
    g = guide_dir / "guide"
    for tex in list(g.glob("chapters/*.tex")) + list(g.glob("appendices/*.tex")):
        for opts in _BEGIN_RE.findall(_read(tex)):
            for tok in opts.split(","):
                tok = tok.strip()
                if tok and "=" not in tok and _BARE_RE.match(tok):
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
