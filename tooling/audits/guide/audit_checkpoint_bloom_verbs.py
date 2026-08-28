#!/usr/bin/env python3
r"""Audit checkpoint items for the Bloom-verb duplication leak.

A scaffold-era generation bug left some checkpoint learning objectives with a
duplicated leading verb that ships, visibly, in the compiled PDF::

    \item[WGP-7.4] explain Explain how to scale Flask applications ...
    \item[SDP-8.2] apply Apply the Strategy pattern to swap algorithms ...
    \item[X-1.6]   Identify Identify code that would benefit ...

The defect is a lowercase Bloom verb immediately repeated in its capitalised
form (or the same word twice). It is invisible to the card/margin audits because
it lives in the chapter checkpoint list, not in a card or a margin note. This
audit flags every such item so it can never re-enter a Gold guide.

Usage:
    python -m tooling.audits.guide.audit_checkpoint_bloom_verbs --guide <slug>
    python -m tooling.audits.guide.audit_checkpoint_bloom_verbs --guide <slug> --strict
    python -m tooling.audits.guide.audit_checkpoint_bloom_verbs --guide <slug> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

from tooling._fail_loud import read_text_or_warn
from tooling.audits.fleet.audit_gold import CHECKPOINT_ITEM_RE  # single source of truth
from tooling.audits.guide._guide_scope import chapter_files, guide_dir_for_slug

# A duplicated leading word: two alphabetic words, case-insensitively equal, at
# the very start of the checkpoint body (e.g. "explain Explain", "Identify
# Identify"). The (?![\w-]) guard requires the second word to be COMPLETE — so a
# legit "Use use-case ..." (where "use" is the start of "use-case", not a repeat
# of "Use") is NOT flagged.
_LEADING_DUP_RE = re.compile(r"^([A-Za-z]+)\s+([A-Za-z]+)(?![\w-])")


@dataclass
class Leak:
    file: str
    line: int
    los_id: str
    snippet: str


def find_bloom_leaks(guide_dir, unreadable: list[str] | None = None) -> list[Leak]:
    """Return every checkpoint item whose body opens with a duplicated word.

    An unreadable chapter is appended (by name) to ``unreadable`` when the caller
    passes a list -- and always announced on stderr -- instead of being skipped as
    if it had no checkpoints (gt#33 row 8; this audit is strict-gated in G2, so a
    silent skip was a false PASS).
    """
    leaks: list[Leak] = []
    for tex in chapter_files(guide_dir):
        content = read_text_or_warn("audit_checkpoint_bloom_verbs", tex)
        if content is None:
            if unreadable is not None:
                unreadable.append(tex.name)
            continue
        for m in CHECKPOINT_ITEM_RE.finditer(content):
            los_id, body = m.group(1), m.group(2).lstrip()
            dup = _LEADING_DUP_RE.match(body)
            if dup and dup.group(1).lower() == dup.group(2).lower():
                line = content[: m.start()].count("\n") + 1
                leaks.append(Leak(tex.name, line, los_id, body[:80].strip()))
    return leaks


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit checkpoint items for the Bloom-verb duplication leak")
    ap.add_argument("--guide", required=True, help="guide slug to audit")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--strict", "--check", dest="strict", action="store_true",
                    help="exit 1 if any checkpoint item has a duplicated leading verb")
    args = ap.parse_args()

    guide_dir = guide_dir_for_slug(args.guide)
    if guide_dir is None or not guide_dir.is_dir():
        print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
        sys.exit(2)

    unreadable: list[str] = []
    leaks = find_bloom_leaks(guide_dir, unreadable)

    if args.json:
        print(json.dumps({
            "slug": args.guide,
            "count": len(leaks),
            "leaks": [vars(leak) for leak in leaks],
            "unreadable": unreadable,
        }, indent=2))
    else:
        if leaks:
            print(f"{args.guide}: {len(leaks)} checkpoint Bloom-verb leak(s)")
            for leak in leaks:
                print(f"  [{leak.los_id}] {leak.file}:{leak.line}: {leak.snippet}")
        else:
            print(f"PASS  {args.guide}: 0 checkpoint Bloom-verb leaks")

    # --strict: a duplicated leading verb is an unambiguous, visible defect, and an
    # unreadable chapter is an audit that could not run. FAIL goes to stderr; exit 1
    # is what audit_gold G2 keys on.
    if args.strict and (leaks or unreadable):
        for leak in leaks:
            print(f"FAIL  {args.guide}: checkpoint {leak.los_id} Bloom-verb leak "
                  f"({leak.file}:{leak.line})", file=sys.stderr)
        for name in unreadable:
            print(f"FAIL  {args.guide}: unreadable chapter {name}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
