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
measures word *count* on the front; it cannot see the words were padding. (The
generic checkpoint card BACK -- "Answer from memory..." -- is templated *by design*
in ``extract_cards.py`` and is NOT a defect; this audit only inspects the prompt.)

Two complementary signals; a hit on EITHER flags the item:

  (B) **Known cross-guide suffix** -- the item's trailing ``SUFFIX_WORDS`` normalized
      words match a tail in :data:`CHECKPOINT_TEMPLATE_SUFFIXES`, a data-derived set
      of suffixes that recur across ``>=2`` DIFFERENT guides. Cross-guide recurrence
      is boilerplate regardless of topic, and catches the singletons (a tail used
      only 1-2x in a given guide) that signal A misses.
  (A) **Intra-guide shared-suffix cluster** -- ``>=MIN_CLUSTER`` checkpoint items in
      the SAME guide share the trailing ``SUFFIX_WORDS`` normalized words. Catches
      guide-local templates (incl. topic-specific ones absent from the cross-guide
      set), and is self-maintaining as new padding appears.

Counts are over UNIQUE checkpoint prompts: a checkpoint box may repeat ``\item[LOS]``
in a paired ``\textbf{Answers:}`` enumerate, so items are de-duplicated by LOS-ID
(keeping the first = the prompt) before counting/flagging.

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

# Detection thresholds. SUFFIX_WORDS is the trailing-word window used by BOTH
# signals; 10 sits above every benign shared checkpoint phrase observed fleet-wide
# (all < 10 words, e.g. "give one example of each") -- three hand-authored prompts
# sharing 10 verbatim trailing words essentially never happens. MIN_CLUSTER mirrors
# the observed template repetition (real tails recur 3-10x within a single guide).
SUFFIX_WORDS = 10
MIN_CLUSTER = 3

# Data-derived 2026-06-26 (fleet count / #guides in comments): 10-word trailing
# suffixes that recur across >=2 DIFFERENT guides. Cross-guide recurrence across
# unrelated topics is boilerplate; this is what catches a tail used only 1-2x in a
# given guide (so it escapes signal A's >=3 intra-guide cluster). Regenerate with
# the fleet suffix-frequency analysis if the corpus changes. Normalized exactly as
# _norm_words() emits (lowercased, hyphens + punctuation -> space, 1-char tokens
# dropped, trailing LOS-echo stripped).
CHECKPOINT_TEMPLATE_SUFFIXES: frozenset[str] = frozenset({
    "that it worked and one thing that can go wrong",                        # 92 / 18 guides
    "flips the trade off and the mechanism behind the flip",                 # 63 / 17 guides
    "name one signal that confirms the description applies in practice",     # 52 / 14 guides
    "that separates it from nearby lookalikes and one false positive",       # 36 / 10 guides
    "and the failure mode you hit at the domain boundary",                   # 32 / 10 guides
    "state what goes wrong if you ignore the underlying mechanism",          # 23 / 12 guides
    "the boundary where conclusions flip and why that boundary matters",     # 23 /  6 guides
    "matters in practice and one confounder you must control for",           # 14 /  3 guides
    "constraint you consciously relax and why that relaxation is acceptable",# 12 /  2 guides
})

# A trailing right-aligned LOS echo "\hfill\textit{(DLJ-6.6)}" some guides append to
# every checkpoint. Stripped BEFORE normalization so its parenthesized LOS (whose
# letters survive as a stray token, e.g. "dlj") cannot shift the suffix window or
# defeat a cross-guide suffix match.
_LOS_ECHO_RE = re.compile(r"\\hfill\s*\\textit\s*\{\s*\([^)]*\)\s*\}\s*$")
# \texttt[opt]{...} etc. -- a macro NAME plus an optional [..] arg; the {..} arg
# content is preserved (only the braces are dropped) so prose inside \textbf{...}
# still counts toward the suffix.
_MACRO_RE = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?")


def _norm_words(body: str) -> list[str]:
    """Normalize a checkpoint body to lowercase word tokens.

    Strips a trailing LOS-echo, then macro names + optional args, drops braces,
    lowercases, and reduces every non-alphanumeric character (INCLUDING hyphens) to
    a space so suffix matching is punctuation/hyphenation-insensitive ("trade-off"
    == "trade off"). Single-character tokens are dropped. This shares G1's macro/brace
    handling but ALSO normalizes punctuation/hyphens -- a deliberate, detector-specific
    divergence for stable suffix comparison, not a mirror of the G1 word counter.
    """
    body = _LOS_ECHO_RE.sub("", body)
    s = _MACRO_RE.sub(" ", body)
    s = s.replace("{", " ").replace("}", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return [w for w in s.split() if len(w) > 1]


@dataclass
class Templated:
    file: str
    line: int
    los_id: str
    reason: str   # comma-joined: "known-tail" and/or "shared-suffix(xN)"
    snippet: str


def find_template_tails(guide_dir) -> tuple[int, list[Templated]]:
    """Return ``(unique_checkpoint_prompts, templated_items)`` for one guide."""
    # (file, line, los_id, normalized words), de-duplicated by LOS-ID so a paired
    # "Answers:" enumerate that repeats \item[LOS] is not counted as a 2nd prompt.
    items: list[tuple[str, int, str, list[str]]] = []
    seen: set[str] = set()
    for tex in chapter_files(guide_dir):
        try:
            content = tex.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in CHECKPOINT_ITEM_RE.finditer(content):
            los_id = m.group(1)
            if los_id in seen:        # keep the first occurrence (the prompt)
                continue
            seen.add(los_id)
            words = _norm_words(m.group(2))
            line = content[: m.start()].count("\n") + 1
            items.append((tex.name, line, los_id, words))

    # Trailing SUFFIX_WORDS-word key per item (None if the prompt is shorter).
    suffixes = [
        " ".join(words[-SUFFIX_WORDS:]) if len(words) >= SUFFIX_WORDS else None
        for (_f, _l, _id, words) in items
    ]

    reasons: dict[int, set[str]] = defaultdict(set)

    # Signal A: >= MIN_CLUSTER items in THIS guide sharing the trailing suffix.
    groups: dict[str, list[int]] = defaultdict(list)
    for i, suf in enumerate(suffixes):
        if suf is not None:
            groups[suf].append(i)
    for idxs in groups.values():
        if len(idxs) >= MIN_CLUSTER:
            for i in idxs:
                reasons[i].add(f"shared-suffix(x{len(idxs)})")

    # Signal B: known cross-guide suffix (catches singletons signal A misses).
    for i, suf in enumerate(suffixes):
        if suf is not None and suf in CHECKPOINT_TEMPLATE_SUFFIXES:
            reasons[i].add("known-tail")

    templated = [
        Templated(items[i][0], items[i][1], items[i][2],
                  ",".join(sorted(reasons[i])), " ".join(items[i][3])[:80])
        for i in sorted(reasons)
    ]
    return len(items), templated


def _reason_tally(templated: list[Templated]) -> str:
    """e.g. '14 shared-suffix, 5 known-tail' -- per-signal item counts (an item may
    hit both signals, so the parts can sum to more than len(templated))."""
    counts: dict[str, int] = defaultdict(int)
    for t in templated:
        for part in t.reason.split(","):
            counts[part.split("(", 1)[0]] += 1
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
    pct_fleet = (fleet_templated / fleet_total * 100) if fleet_total else 0.0
    out.append(f"**{len(rows)} guides affected** — {fleet_templated} templated "
               f"checkpoint(s) of {fleet_total} fleet-wide ({pct_fleet:.1f}%).")
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
        # Message matches audit_gold.NOT_FOUND_RE. NB: in audit_gold's G2 dispatch a
        # NOT_FOUND match records an out-of-scope note (it does not contribute a
        # template-tailing FAIL). In a real fleet run every discovered slug resolves,
        # so this branch is unreachable there.
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
