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
generic checkpoint card BACK -- "Self-check from: ... Answer from memory..." -- is
the card extractor's placeholder for an item with no paired answer; it is counted
by ``audit_back_content`` rule M5, advisory on landing. This audit inspects only
the prompt.)

Three complementary signals; a hit on ANY flags the item:

  (B) **Known cross-guide suffix** -- the item's trailing ``SUFFIX_WORDS`` normalized
      words match a tail in :data:`CHECKPOINT_TEMPLATE_SUFFIXES`, a data-derived set
      of suffixes that recur across ``>=2`` DIFFERENT guides (regenerate/verify with
      ``--suffix-freq``). Cross-guide recurrence is boilerplate regardless of topic,
      and catches the singletons (a tail used only 1-2x in a given guide) that
      signal A misses.
  (A) **Intra-guide shared-suffix cluster** -- ``>=MIN_CLUSTER`` checkpoint items in
      the SAME guide share the trailing ``SUFFIX_WORDS`` normalized words. Catches
      guide-local templates (incl. topic-specific ones absent from the cross-guide
      set), and is self-maintaining as new padding appears.
  (C) **Verbatim-LOS prompt** (gt#33, r2 review 2026-08-28) -- the item's normalized
      words contain the normalized ``<level> <statement>`` of its own ``\los{ID}``
      as a contiguous run (equal, prefix, or embedded). A prompt that merely
      restates the learning objective has no discriminating answer -- the fleet's
      first GAMED guide shipped 18 of 27 that way and scored 0/27 here. Reported
      as ``verbatim-los``; gated separately by ``--strict-los`` so the tail flip
      (gm#77) and the LOS flip can land independently.

Counts are over checkpoint PROMPTS. A checkpoint box may repeat ``\item[LOS]`` in a
paired ``\textbf{Answers:}`` enumerate; an answer-key item -- one inside the Answers
enumerate whose LOS-ID ALSO appears as a question -- is excluded. This is NOT a LOS-ID
dedup (a question list may legitimately reuse a LOS-ID for two distinct prompts, which
dedup would wrongly collapse) and NOT a blunt "everything after Answers" cut (some
guides tag the LOS on items that live *inside* the answer enumerate, which that rule
would wrongly drop) -- only a true positional answer key is removed.

Usage::

    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug>
    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug> --strict
    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug> --strict-los
    python -m tooling.audits.guide.audit_checkpoint_originality --guide manning_<slug> --json
    python -m tooling.audits.guide.audit_checkpoint_originality --fleet         # ranked worklist
    python -m tooling.audits.guide.audit_checkpoint_originality --suffix-freq   # derive the blocklist

Registered FLAGLESS (advisory) in ``audit_gold.GUIDE_AUDITS`` during the
warning-first rollout: without ``--strict`` / ``--strict-los`` it reports but exits
0 and prints no ``FAIL`` line, so it gates nothing. Flip the registration to
``["--strict"]`` once the fleet reads zero template-tailed items, and add
``"--strict-los"`` once it reads zero verbatim-LOS prompts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from pathlib import Path

from tooling._fail_loud import read_text_or_warn, warn_audit_error
from tooling.audits.fleet.audit_gold import CHECKPOINT_ITEM_RE  # single source of truth
from tooling.audits.guide._guide_scope import (
    chapter_files,
    guide_dir_for_slug,
    guide_dirs,
)
from tooling.validation._latex import strip_latex_comments
from tooling.validation.extract_los import LOS_RE  # single source of truth

# Detection thresholds. SUFFIX_WORDS is the trailing-word window used by the two
# tail signals; 10 sits above every benign shared checkpoint phrase observed
# fleet-wide (all < 10 words, e.g. "give one example of each") -- three hand-authored
# prompts sharing 10 verbatim trailing words essentially never happens. MIN_CLUSTER
# mirrors the observed template repetition (real tails recur 3-10x within a guide).
SUFFIX_WORDS = 10
MIN_CLUSTER = 3
# Signal C: an LOS shorter than this (after normalization) is too generic to call a
# prompt that contains it a restatement ("Define it").
MIN_LOS_WORDS = 3
TAIL_REASONS = ("known-tail", "shared-suffix")
LOS_REASON = "verbatim-los"

# Data-derived 2026-06-26 (fleet count / #guides in comments): 10-word trailing
# suffixes that recur across >=2 DIFFERENT guides. Cross-guide recurrence across
# unrelated topics is boilerplate; this is what catches a tail used only 1-2x in a
# given guide (so it escapes signal A's >=3 intra-guide cluster). REGENERATE / verify
# with `--suffix-freq` if the corpus changes. Normalized exactly as _norm_words()
# emits (lowercased, hyphens + punctuation -> space, 1-char tokens dropped, trailing
# LOS-echo stripped).
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
# defeat a cross-guide suffix match. Tolerates a trailing period and/or comment.
_LOS_ECHO_RE = re.compile(r"\\hfill\s*\\textit\s*\{\s*\([^)]*\)\s*\}\s*\.?\s*(?:%[^\n]*)?$")
# \texttt[opt]{...} etc. -- a macro NAME plus an optional [..] arg; the {..} arg
# content is preserved (only the braces are dropped) so prose inside \textbf{...}
# still counts toward the suffix.
_MACRO_RE = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?")

# Checkpoint-box + "Answers:" boundaries, mirroring tooling.cards.extract_cards.
_ANSWERS_MARK_RE = re.compile(
    r"\\(?:textbf|paragraph|subparagraph)\s*\{\s*Answers?:?\s*\}")
_CHECKPOINTBOX_ENV_RE = re.compile(
    r"\\begin\{checkpointbox\}.*?\\end\{checkpointbox\}", re.DOTALL)
_TCOLORBOX_OPEN_RE = re.compile(r"\\begin\{tcolorbox\}\[checkpointbox")
_TCOLORBOX_DELIM_RE = re.compile(r"\\(begin|end)\{tcolorbox\}")


def _checkpoint_box_spans(content: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each checkpoint box. The tcolorbox form balances nested
    ``\\begin/\\end{tcolorbox}`` so a nested box (e.g. a debug aside) before the
    Answers marker cannot truncate the span (which would defeat answer-key exclusion).
    """
    spans: list[tuple[int, int]] = []
    # \begin{checkpointbox}..\end{checkpointbox}: its own \end token, not truncatable
    # by a nested tcolorbox.
    spans.extend((m.start(), m.end()) for m in _CHECKPOINTBOX_ENV_RE.finditer(content))
    # \begin{tcolorbox}[checkpointbox..]: walk \begin/\end{tcolorbox} with a depth count.
    for opener in _TCOLORBOX_OPEN_RE.finditer(content):
        depth, end = 1, len(content)
        for t in _TCOLORBOX_DELIM_RE.finditer(content, opener.end()):
            depth += 1 if t.group(1) == "begin" else -1
            if depth == 0:
                end = t.end()
                break
        spans.append((opener.start(), end))
    return spans


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


def _answer_key_offsets(content: str) -> set[int]:
    """Start offsets of answer-key ``\\item[LOS]`` items.

    A true answer key is an ``\\item[LOS]`` inside a box's Answers enumerate whose
    LOS-ID ALSO appears as a question in the same box (a positional answer to a
    prompt) -- those are excluded. An ``\\item[LOS]`` whose LOS appears ONLY in the
    answer region is a genuine (if oddly placed) prompt -- some guides tag the LOS on
    items inside the answer enumerate -- and is kept; a question-region ``\\item[LOS]``
    is always kept, so a list may reuse a LOS-ID for two distinct prompts.
    """
    offsets: set[int] = set()
    for box_start, box_end in _checkpoint_box_spans(content):
        marker = _ANSWERS_MARK_RE.search(content, box_start, box_end)
        if not marker:
            continue
        q_los = {m.group(1)
                 for m in CHECKPOINT_ITEM_RE.finditer(content[box_start:marker.start()])}
        for m in CHECKPOINT_ITEM_RE.finditer(content[marker.start():box_end]):
            if m.group(1) in q_los:
                offsets.add(marker.start() + m.start())
    return offsets


def _guide_items(
    guide_dir: "Path", unreadable: list[str] | None = None
) -> list[tuple[str, int, str, list[str]]]:
    """Every checkpoint PROMPT (answer-key items excluded) as (file, line, los, words).

    An unreadable chapter is appended (by name) to ``unreadable`` when a list is
    passed, and always warned on stderr -- never skipped as if it had no prompts.
    """
    items: list[tuple[str, int, str, list[str]]] = []
    for tex in chapter_files(guide_dir):
        content = read_text_or_warn("audit_checkpoint_originality", tex)
        if content is None:
            if unreadable is not None:
                unreadable.append(tex.name)
            continue
        answer_keys = _answer_key_offsets(content)
        for m in CHECKPOINT_ITEM_RE.finditer(content):
            if m.start() in answer_keys:
                continue  # a positional answer key, not a prompt
            words = _norm_words(m.group(2))
            line = content[: m.start()].count("\n") + 1
            items.append((tex.name, line, m.group(1), words))
    return items


def _los_words_by_id(guide_dir: "Path") -> dict[str, list[str]]:
    """``{LOS-ID: _norm_words("<level> <statement>")}`` over the guide's chapters.

    Comment-stripped, so a commented-out ``\\los{}`` cannot supply a match. Guide-wide
    (not per file): a checkpoint may sit in a different chapter than its LOS.
    """
    out: dict[str, list[str]] = {}
    for tex in chapter_files(guide_dir):
        content = read_text_or_warn("audit_checkpoint_originality", tex)
        if content is None:
            continue  # already counted as unreadable by _guide_items
        for m in LOS_RE.finditer(strip_latex_comments(content)):
            los_id, level, statement = (g.strip() for g in m.groups())
            words = _norm_words(f"{level} {statement}")
            prev = out.get(los_id)
            if prev is not None and prev != words:
                # Two different statements under one id: which one signal C compares
                # against would depend on chapter order, so say so rather than pick.
                warn_audit_error(
                    "audit_checkpoint_originality._los_words_by_id", tex,
                    ValueError(f"duplicate \\los id {los_id!r} with differing text; "
                               "signal C uses the first"),
                )
                continue
            out[los_id] = words
    return out


def _contains_run(words: list[str], sub: list[str]) -> bool:
    """True when ``sub`` occurs in ``words`` as a contiguous run."""
    n = len(sub)
    if n == 0 or n > len(words):
        return False
    return any(words[i:i + n] == sub for i in range(len(words) - n + 1))


def _reason_kinds(reason: str) -> set[str]:
    """``"known-tail,shared-suffix(x3)"`` -> ``{"known-tail", "shared-suffix"}``."""
    return {part.split("(", 1)[0] for part in reason.split(",") if part}


@dataclass
class Templated:
    file: str
    line: int
    los_id: str
    reason: str   # comma-joined: "known-tail", "shared-suffix(xN)" and/or "verbatim-los"
    snippet: str

    @property
    def is_tail(self) -> bool:
        return bool(_reason_kinds(self.reason) & set(TAIL_REASONS))

    @property
    def is_verbatim_los(self) -> bool:
        return LOS_REASON in _reason_kinds(self.reason)


def find_template_tails(
    guide_dir: "Path", unreadable: list[str] | None = None
) -> tuple[int, list[Templated]]:
    """Return ``(checkpoint_prompts, templated_items)`` for one guide.

    ``templated_items`` carries every prompt hit by signal A, B or C; use
    ``Templated.is_tail`` / ``Templated.is_verbatim_los`` to split them.
    ``unreadable`` (optional list) collects the names of chapters that could not
    be read; ``main()`` FAILs on them under ``--strict``.
    """
    items = _guide_items(guide_dir, unreadable)

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

    # Signal C: the prompt restates its own LOS (equal / prefix / embedded run).
    los_words = _los_words_by_id(guide_dir)
    for i, (_f, _l, los_id, words) in enumerate(items):
        lw = los_words.get(los_id)
        if lw and len(lw) >= MIN_LOS_WORDS and _contains_run(words, lw):
            reasons[i].add(LOS_REASON)

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


def fleet_suffix_frequency() -> str:
    """Dump the cross-guide trailing-suffix frequencies CHECKPOINT_TEMPLATE_SUFFIXES is
    derived from: every SUFFIX_WORDS-word suffix shared across >=2 guides, worst-first.
    Run this to regenerate / verify the blocklist when the corpus changes."""
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "guides": set()})
    for gd in guide_dirs():
        for (_f, _l, _id, words) in _guide_items(gd):
            if len(words) >= SUFFIX_WORDS:
                suf = " ".join(words[-SUFFIX_WORDS:])
                stats[suf]["count"] += 1
                stats[suf]["guides"].add(gd.name)
    rows = sorted(((s, v) for s, v in stats.items() if len(v["guides"]) >= 2),
                  key=lambda kv: kv[1]["count"], reverse=True)
    out = [f"{v['count']:>4}  {len(v['guides']):>2} guides  {s!r}" for s, v in rows]
    out.append("")
    out.append(f"{len(rows)} cross-guide (>=2 guides) suffix(es) = CHECKPOINT_TEMPLATE_SUFFIXES.")
    return "\n".join(out)


def fleet_table() -> str:
    """A ranked (worst-first) markdown worklist over the whole fleet."""
    rows: list[tuple[str, int, int, int, float, str, int]] = []
    fleet_total = fleet_tails = fleet_los = 0
    for gd in guide_dirs():
        total, templated = find_template_tails(gd)
        if total == 0:
            continue
        tails = sum(1 for t in templated if t.is_tail)
        los = sum(1 for t in templated if t.is_verbatim_los)
        fleet_total += total
        fleet_tails += tails
        fleet_los += los
        if templated:
            pct = len(templated) / total * 100
            rows.append((gd.name, total, tails, los, pct, _reason_tally(templated),
                         len(templated)))
    # Worst-first: by DISTINCT flagged prompts (the rewrite workload -- an item hit
    # by both signals is rewritten once), then % (egregiousness).
    rows.sort(key=lambda r: (r[6], r[4]), reverse=True)

    out = ["| Guide | Checkpoints | Template-tailed | Verbatim-LOS | % flagged | Reasons |",
           "|---|--:|--:|--:|--:|---|"]
    for name, total, tails, los, pct, reasons, _flagged in rows:
        out.append(f"| `{name}` | {total} | {tails} | {los} | {pct:.0f}% | {reasons} |")
    out.append("")
    pct_tails = (fleet_tails / fleet_total * 100) if fleet_total else 0.0
    pct_los = (fleet_los / fleet_total * 100) if fleet_total else 0.0
    out.append(f"**{len(rows)} guides affected** — {fleet_tails} template-tailed "
               f"({pct_tails:.1f}%) and {fleet_los} verbatim-LOS ({pct_los:.1f}%) "
               f"checkpoint prompt(s) of {fleet_total} fleet-wide.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit checkpoint items for template-tailing (recall-floor padding)")
    ap.add_argument("--guide", help="guide slug to audit (e.g. manning_<slug>)")
    ap.add_argument("--fleet", action="store_true",
                    help="rank the whole fleet worst-first as a markdown table")
    ap.add_argument("--suffix-freq", action="store_true",
                    help="dump cross-guide suffix frequencies (regenerate the blocklist)")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --guide)")
    ap.add_argument("--strict", "--check", dest="strict", action="store_true",
                    help="exit 1 if any checkpoint item is template-tailed (signals A/B)")
    ap.add_argument("--strict-los", dest="strict_los", action="store_true",
                    help="exit 1 if any checkpoint prompt is its own LOS restated (signal C)")
    args = ap.parse_args()

    if args.suffix_freq:
        print(fleet_suffix_frequency())
        return

    if args.fleet:
        print(fleet_table())
        return

    if not args.guide:
        ap.error("one of --guide, --fleet or --suffix-freq is required")

    guide_dir = guide_dir_for_slug(args.guide)
    if guide_dir is None or not guide_dir.is_dir():
        # Message matches audit_gold.NOT_FOUND_RE. NB: if this branch were reached
        # under audit_gold's G2 dispatch it WOULD register a G2 failure (NOT_FOUND is
        # appended to failures), but every slug audit_gold discovers resolves, so it
        # is unreachable in a real fleet run.
        print(f"Error: guide not found for slug: {args.guide}", file=sys.stderr)
        sys.exit(2)

    unreadable: list[str] = []
    total, templated = find_template_tails(guide_dir, unreadable)
    tails = [t for t in templated if t.is_tail]
    verbatim = [t for t in templated if t.is_verbatim_los]
    pct = len(templated) / total * 100 if total else 0.0

    if args.json:
        print(json.dumps({
            "slug": args.guide,
            "total": total,
            "templated": len(templated),
            "template_tailed": len(tails),
            "verbatim_los": len(verbatim),
            "pct": round(pct, 1),
            "items": [vars(t) for t in templated],
            "unreadable": unreadable,
        }, indent=2))
    elif templated:
        # Advisory line: must NOT start with "FAIL" (audit_gold.FAIL_RE) so the
        # flagless G2 run never gates on it.
        print(f"{args.guide}: {len(templated)}/{total} checkpoint prompt(s) flagged "
              f"({pct:.0f}%): {len(tails)} template-tailed, {len(verbatim)} verbatim-LOS")
        for t in templated:
            print(f"  [{t.los_id}] {t.file}:{t.line}: {t.reason} -- {t.snippet}")
    else:
        print(f"PASS  {args.guide}: 0/{total} template-tailed or verbatim-LOS checkpoints")

    # --strict: each template-tailed item is an individual defect (zero-tolerance,
    # mirroring G1 stubs==0); --strict-los does the same for verbatim-LOS prompts;
    # an unreadable chapter is an audit that could not run and fails either mode.
    # FAIL -> stderr; exit 1 is what audit_gold G2 keys on.
    strict_any = args.strict or args.strict_los
    # De-duplicate: an item hit by BOTH signal groups is one defect, not two
    # (review of #35 -- it used to emit two identical FAIL lines).
    selected = (tails if args.strict else []) + (verbatim if args.strict_los else [])
    failing = list(dict.fromkeys(selected))
    if strict_any and (failing or unreadable):
        for t in failing:
            print(f"FAIL  {args.guide}: checkpoint {t.los_id} {t.reason} "
                  f"({t.file}:{t.line})", file=sys.stderr)
        for name in unreadable:
            print(f"FAIL  {args.guide}: unreadable chapter {name}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
