#!/usr/bin/env python3
r"""Audit checkpoint items for template-tailing (recall-floor padding).

A stub-padding pass cleared G1's ``<10-word`` checkpoint stub floor by appending
identical boilerplate **tails** to short checkpoint prompts -- inflating the word
count without authoring chapter-specific content::

    \item[GBA-1.2] Apply Bayesian reasoning to update beliefs given new data to a
        concrete problem you construct. Show the first step, the signal that it
        worked, and one thing that can go wrong.
    \item[PWO-1.3] Compare alternative approaches and their performance for series.
        Name one metric that separates them, one scenario that flips the
        trade-off, and the mechanism behind the flip.

Because the padded items are now ``>10`` words they pass G1 silently, but the tail
is generic -- the same closing recurs verbatim across many checkpoints (and across
guides), so the prompt no longer cues recall of *this* chapter. G1's stub counter
measures the FRONT (prompt body); it cannot see that the words were padding. (The
generic checkpoint card BACK -- "Answer from memory..." -- is templated *by design*
in ``extract_cards.py`` and is NOT a defect; this audit only inspects the front.)

Two complementary signals; a hit on EITHER flags the item:

  (B) **Known-tail blocklist** -- exact trailing match against
      :data:`CHECKPOINT_TEMPLATE_TAILS`. Catches cross-guide singletons that a
      per-guide cluster threshold misses; zero false positives (exact strings).
  (A) **Intra-guide shared-suffix cluster** -- ``>=MIN_CLUSTER`` checkpoint items in
      the SAME guide whose trailing ``SUFFIX_WORDS`` normalized words are identical.
      Self-maintaining: catches future/unknown templates the moment a padding pass
      reuses any tail >=3x in a guide.

Usage::

    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug>
    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug> --strict
    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug> --json
    python -m tooling.audits.guide.audit_checkpoint_originality --fleet   # ranked worklist

Registered FLAGLESS (advisory) in ``audit_gold.GUIDE_AUDITS`` during the
warning-first rollout: without ``--strict`` it reports but exits 0 and prints no
``FAIL`` line, so it gates nothing. Flip the registration to ``["--strict"]`` once
the fleet reads zero templated items.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from tooling.audits.fleet.audit_gold import CHECKPOINT_ITEM_RE  # single source of truth
from tooling.audits.guide._guide_scope import (
    chapter_files,
    guide_dir_for_slug,
    guide_dirs,
)

# Detection thresholds. SUFFIX_WORDS must be <= the shortest known tail (13 words)
# so two items that share a known tail also share their last SUFFIX_WORDS words;
# and it sits above every benign shared checkpoint phrase observed fleet-wide
# (all < 10 words, e.g. "give one example of each"). Three hand-authored prompts
# sharing 10 verbatim trailing words essentially never happens. MIN_CLUSTER mirrors
# the observed template repetition (real tails recur 3-10x within a single guide);
# singletons (1-2x) are left to the known-tail blocklist.
SUFFIX_WORDS = 10
MIN_CLUSTER = 3

# Curated from the 2026-06 fleet sweep (fleet occurrence counts in comments),
# normalized exactly as _norm_words() emits: lowercased, hyphens + punctuation
# reduced to spaces, whitespace collapsed, single-character tokens dropped.
CHECKPOINT_TEMPLATE_TAILS: frozenset[str] = frozenset({
    "show the first step the signal that it worked and one thing that can go wrong",                                   # 89
    "name one metric that separates them one scenario that flips the trade off and the mechanism behind the flip",     # 61
    "give one operational example and name one signal that confirms the description applies in practice",              # 50
    "state the diagnostic that separates it from nearby lookalikes and one false positive",                            # 35
    "name the variable that drives the outcome the boundary where conclusions flip and why that boundary matters",     # 23
    "state the metric the threshold that matters in practice and one confounder you must control for",                 # 14
    "name the primary constraint one secondary constraint you consciously relax and why that relaxation is acceptable",# 12
})

# \texttt[opt]{...} etc. -- a macro NAME plus an optional [..] arg; the {..} arg
# content is preserved (only the braces are dropped) so prose inside \textbf{...}
# still counts toward the suffix, matching G1's count_stub_checkpoint_items.
_MACRO_RE = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?")


def _norm_words(body: str) -> list[str]:
    """Normalize a checkpoint body to lowercase word tokens.

    Strips macro names + optional args, drops braces, lowercases, then reduces
    every non-alphanumeric character (INCLUDING hyphens) to a space so the tail
    match is punctuation/hyphenation-insensitive ("trade-off" == "trade off").
    Single-character tokens are dropped (mirrors the G1 stub counter).
    """
    s = _MACRO_RE.sub(" ", body)
    s = s.replace("{", " ").replace("}", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return [w for w in s.split() if len(w) > 1]


@dataclass
class Templated:
    file: str
    line: int
    los_id: str
    reason: str   # "known-tail" | "shared-suffix(xN)"
    snippet: str


def find_template_tails(guide_dir) -> tuple[int, list[Templated]]:
    """Return ``(total_checkpoint_items, templated_items)`` for one guide."""
    # (file, line, los_id, normalized words)
    items: list[tuple[str, int, str, list[str]]] = []
    for tex in chapter_files(guide_dir):
        try:
            content = tex.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in CHECKPOINT_ITEM_RE.finditer(content):
            words = _norm_words(m.group(2))
            line = content[: m.start()].count("\n") + 1
            items.append((tex.name, line, m.group(1), words))

    flagged: dict[int, str] = {}

    # Signal A: >= MIN_CLUSTER items in THIS guide sharing the trailing suffix.
    suffix_groups: dict[str, list[int]] = defaultdict(list)
    for i, (_f, _l, _id, words) in enumerate(items):
        if len(words) >= SUFFIX_WORDS:
            suffix_groups[" ".join(words[-SUFFIX_WORDS:])].append(i)
    for idxs in suffix_groups.values():
        if len(idxs) >= MIN_CLUSTER:
            for i in idxs:
                flagged[i] = f"shared-suffix(x{len(idxs)})"

    # Signal B: known boilerplate tail (catches singletons that signal A misses).
    for i, (_f, _l, _id, words) in enumerate(items):
        joined = " ".join(words)
        if any(joined.endswith(tail) for tail in CHECKPOINT_TEMPLATE_TAILS):
            flagged.setdefault(i, "known-tail")

    templated = [
        Templated(items[i][0], items[i][1], items[i][2], reason,
                  " ".join(items[i][3])[:80])
        for i, reason in sorted(flagged.items())
    ]
    return len(items), templated


def _reason_tally(templated: list[Templated]) -> str:
    """e.g. '9 shared-suffix, 5 known-tail' -- collapse the (xN) detail."""
    counts: dict[str, int] = defaultdict(int)
    for t in templated:
        counts[t.reason.split("(", 1)[0]] += 1
    return ", ".join(f"{n} {kind}" for kind, n in sorted(
        counts.items(), key=lambda kv: kv[1], reverse=True))


def fleet_table() -> str:
    """A ranked (worst-first) markdown worklist over the whole fleet."""
    rows: list[tuple[str, int, int, float, str]] = []
    fleet_total = fleet_templated = 0
    for gd in guide_dirs():
        total, templated = find_template_tails(gd)
        if total == 0:
            continue
        fleet_total += total
        fleet_templated += len(templated)
        if templated:
            pct = len(templated) / total * 100
            rows.append((gd.name, total, len(templated), pct, _reason_tally(templated)))
    # Worst-first: by templated count (rewrite workload), then % (egregiousness).
    rows.sort(key=lambda r: (r[2], r[3]), reverse=True)

    out = ["| Guide | Checkpoints | Templated | % of deck | Reasons |",
           "|---|--:|--:|--:|---|"]
    for name, total, n, pct, reasons in rows:
        out.append(f"| `{name}` | {total} | {n} | {pct:.0f}% | {reasons} |")
    out.append("")
    out.append(f"**{len(rows)} guides affected** — {fleet_templated} templated "
               f"checkpoint(s) of {fleet_total} fleet-wide "
               f"({fleet_templated / fleet_total * 100:.1f}%).")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit checkpoint items for template-tailing (recall-floor padding)")
    ap.add_argument("--guide", help="guide slug to audit (e.g. manning_<slug>)")
    ap.add_argument("--fleet", action="store_true",
                    help="rank the whole fleet worst-first as a markdown table")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --guide)")
    ap.add_argument("--strict", "--check", dest="strict", action="store_true",
                    help="exit 1 if any checkpoint item is template-tailed")
    args = ap.parse_args()

    if args.fleet:
        print(fleet_table())
        return

    if not args.guide:
        ap.error("one of --guide or --fleet is required")

    guide_dir = guide_dir_for_slug(args.guide)
    if guide_dir is None or not guide_dir.is_dir():
        # Message matches audit_gold.NOT_FOUND_RE so G2 treats a bad slug as
        # out-of-scope, not as a gate failure.
        print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
        sys.exit(2)

    total, templated = find_template_tails(guide_dir)
    pct = len(templated) / total * 100 if total else 0.0

    if args.json:
        print(json.dumps({
            "slug": args.guide,
            "total": total,
            "templated": len(templated),
            "pct": round(pct, 1),
            "items": [vars(t) for t in templated],
        }, indent=2))
    elif templated:
        # Advisory line: must NOT start with "FAIL" (audit_gold.FAIL_RE) so the
        # flagless G2 run never gates on it.
        print(f"{args.guide}: {len(templated)}/{total} checkpoint item(s) "
              f"template-tailed ({pct:.0f}%)")
        for t in templated:
            print(f"  [{t.los_id}] {t.file}:{t.line}: {t.reason} -- {t.snippet}")
    else:
        print(f"PASS  {args.guide}: 0/{total} template-tailed checkpoints")

    # --strict: each templated item is an individual defect (zero-tolerance,
    # mirroring G1 stubs==0). FAIL -> stderr; exit 1 is what audit_gold G2 keys on.
    if args.strict and templated:
        for t in templated:
            print(f"FAIL  {args.guide}: checkpoint {t.los_id} template-tailed "
                  f"({t.reason}, {t.file}:{t.line})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
