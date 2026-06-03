#!/usr/bin/env python3
"""Build Anki ``.apkg`` decks for every guide in the host repo (fleet ``decks-all``).

Iterates :func:`tooling.discovery.iter_guide_dirs` and runs ``make -C <guide>/guide
decks`` for each guide that has extracted cards. The ``.apkg`` outputs are
gitignored (``**/decks/*.apkg``), so this produces no tracked diff — it is a
build step, not a content change.

Run from the consuming host repo root::

    python -m tooling.anki.build_all          # build all
    python -m tooling.anki.build_all --list   # just list what would build
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from tooling import discovery


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="list guides that would build, don't build")
    args = ap.parse_args()

    try:
        import genanki  # noqa: F401
    except ImportError:
        print("ERROR: genanki not installed. Run: pip install genanki  (or pip install -e tooling/)", file=sys.stderr)
        return 1

    guides = discovery.iter_guide_dirs()
    built, skipped, failed = 0, [], []
    for g in guides:
        gdir = g / "guide"
        if not (gdir / "cards" / "all_cards.yml").exists():
            skipped.append(g.name)
            continue
        if args.list:
            print(f"  would build  {g.name}")
            built += 1
            continue
        r = subprocess.run(["make", "-C", str(gdir), "decks"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  OK    {g.name}")
            built += 1
        else:
            tail = (r.stderr or r.stdout).strip().splitlines()
            print(f"  FAIL  {g.name}: {tail[-1] if tail else 'see output'}")
            failed.append(g.name)

    verb = "would build" if args.list else "built"
    print(f"\ndecks {verb}: {built}/{len(guides)}"
          + (f" · skipped (no cards): {len(skipped)}" if skipped else "")
          + (f" · FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
