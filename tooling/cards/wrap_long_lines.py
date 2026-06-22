#!/usr/bin/env python3
r"""Break card-level very_long_line issues at safe, readable boundaries.

The ``card_presentation`` audit flags any card front/back line longer than 200
chars (``very_long_line``). The chapter-level autofix can't help — the extractor
collapses source wrapping, so a long prose card back becomes one >200-char line
regardless of how the ``.tex`` is wrapped. This module fixes it where it lives:
on the extracted card text, by inserting newlines at sentence/clause boundaries.

``wrap_long_text`` is **math-safe** (reuses ``extract_cards._has_unclosed_math``)
— it never inserts a break inside ``$...$`` / ``\[...\]`` / ``\(...\)``, so it
cannot split an equation or a ``\command{...}`` mid-token. It only inserts ``\n``
at boundaries already present in the text (after ``. ``/``; ``/``: ``/``, `` or,
as a last resort, a plain space), so the rendered card is unchanged — Anki and the
LaTeX deck collapse intra-field whitespace — while the source becomes scannable
and clears the gate. A line with no safe boundary under the threshold (e.g. a long
URL or an equation spanning the limit) is left untouched rather than corrupted.

Usage:
    python -m tooling.cards.wrap_long_lines cards/            # in-place on *.yml
    python -m tooling.cards.wrap_long_lines cards/ --dry-run  # report only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from tooling.cards.extract_cards import _has_unclosed_math

THRESHOLD = 200
MIN_FRAG = 20  # don't emit a leading fragment shorter than this

# Break-point tiers, most-readable first. Each matches the SPACE that follows a
# boundary delimiter; we break by turning that space into a newline.
_TIERS = (
    re.compile(r"(?<=[.!?]) "),   # sentence
    re.compile(r"(?<=[;:]) "),    # clause
    re.compile(r"(?<=,) "),       # list comma
    re.compile(r" "),             # any space (last resort)
)


def _best_break(s: str, threshold: int) -> int | None:
    """Index of the latest safe break (a space to replace with ``\\n``) <= threshold.

    Tries each readability tier in order; within a tier picks the latest
    candidate that (a) sits in ``[MIN_FRAG, threshold]`` and (b) leaves math
    balanced when the line is cut there. Returns None if nothing is safe.
    """
    for pat in _TIERS:
        cands = [
            m.start()
            for m in pat.finditer(s)
            if MIN_FRAG <= m.start() <= threshold
            and _has_unclosed_math(s[: m.start()]) is None
        ]
        if cands:
            return max(cands)
    return None


def wrap_long_text(text: str, threshold: int = THRESHOLD) -> str:
    """Insert newlines so no line exceeds ``threshold`` chars, where safely possible."""
    out: list[str] = []
    for line in text.split("\n"):
        if len(line.strip()) <= threshold:
            out.append(line)
            continue
        s = line
        pieces: list[str] = []
        # Greedily peel off <=threshold prefixes at safe boundaries.
        guard = 0
        while len(s.strip()) > threshold and guard < 200:
            guard += 1
            bp = _best_break(s, threshold)
            if bp is None:
                break  # no safe break — leave the remainder intact
            pieces.append(s[:bp].rstrip())
            s = s[bp:].lstrip(" ")
        pieces.append(s)
        out.append("\n".join(pieces))
    return "\n".join(out)


# ── card YAML processing ─────────────────────────────────────────────────────

_FIELDS = ("front", "back")


def wrap_card(card: dict, threshold: int = THRESHOLD) -> bool:
    """Wrap a card's text fields in place; return True if anything changed."""
    changed = False
    for f in _FIELDS:
        v = card.get(f)
        if isinstance(v, str):
            w = wrap_long_text(v, threshold)
            if w != v:
                card[f] = w
                changed = True
    return changed


def process_file(path: Path, threshold: int, dry_run: bool) -> tuple[int, int]:
    """Return (cards_changed, total_cards) for one cards/*.yml file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cards = data.get("cards", data) if isinstance(data, dict) else data
    if not isinstance(cards, list):
        return (0, 0)
    changed = sum(wrap_card(c, threshold) for c in cards if isinstance(c, dict))
    if changed and not dry_run:
        # Block style + wide width so wrapped multi-line strings stay readable
        # and PyYAML does not re-wrap them (matches extract_cards' dump intent).
        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True, width=10_000),
            encoding="utf-8",
        )
    return (changed, len(cards))


def main() -> None:
    ap = argparse.ArgumentParser(description="Break card very_long_line issues at safe boundaries")
    ap.add_argument("cards_dir", help="a guide's cards/ directory")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = Path(a.cards_dir)
    files = sorted(d.glob("*.yml"))
    if not files:
        print(f"no *.yml in {d}", file=sys.stderr)
        sys.exit(1)
    tot_changed = tot = 0
    for f in files:
        c, n = process_file(f, a.threshold, a.dry_run)
        tot_changed += c
        tot += n
        if c:
            print(f"{'(dry) ' if a.dry_run else ''}{f.name}: wrapped {c}/{n} cards")
    print(f"{tot_changed} cards wrapped across {len(files)} files")


if __name__ == "__main__":
    main()
