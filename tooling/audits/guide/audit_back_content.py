#!/usr/bin/env python3
"""Audit Anki card back-content for substance / pedagogical completeness.

Catches the "meaningless back" anti-pattern in all its forms:

- Empty backs (CRITICAL): the answer literally doesn't exist
- TODO/TBD scaffolds (CRITICAL): incomplete authoring left as placeholder
- Truncated content (CRITICAL): trailing ``...`` below per-type minimum
- Front-back duplicates (CRITICAL): back rephrases the front without adding value
- Per-type structural deficiencies (HIGH): keyconcept missing 3-part form,
  formula missing variables, drill missing technique, etc.
- Below-threshold lengths (HIGH): per-card-type minimum content
- Evasive references (MEDIUM): "see Chapter X" with no substantive content
- Code-only backs (MEDIUM): no prose explanation around code

Distinct from existing audits:
- ``audit_card_quality.py`` flags thin (<50 chars) without per-type rules,
  no empty-back detection
- ``audit_solution_quality.py`` only checks problem/vignette structure
- ``audit_card_presentation.py`` is formatting-only

Each finding includes the originating chapter ``.tex`` file and macro
location to enable guide-level remediation (the durable fix paradigm).

Usage::

    python3 shared/audits/audit_back_content.py
    python3 shared/audits/audit_back_content.py --guides slug1,slug2
    python3 shared/audits/audit_back_content.py --fail-on critical
    python3 shared/audits/audit_back_content.py --report-only
    python3 shared/audits/audit_back_content.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tooling.audits.guide._guide_scope import (  # noqa: E402
    GuideInfo,
    get_all_guides,
    get_guide_by_slug,
    get_repo_root,
    guide_dir_for_slug,
)


# ── Constants ────────────────────────────────────────────────────────────────


# Per-card-type minimum back length (H1 thresholds).
# Tuned empirically from sampled cards across the fleet.
MIN_BACK_LENGTH_BY_TYPE: dict[str, int] = {
    "term": 40,
    "keyconcept": 100,
    "problem": 100,
    "vignette": 200,
    "checkpoint": 30,
    "drill": 40,
    "formula": 50,
    "redflag": 50,
    "interview": 50,
    "interviewcontext": 50,
    "interviewtip": 30,
    "starstory": 100,
    "paradox": 100,
    "decisiontree": 80,
    "levelcard": 50,
    "comparison": 100,
    "comparison3": 150,
    "sixtysec": 50,
    "actuarialbridge": 50,
    "termbi": 40,
    "mathdef": 40,
    "proposition": 50,
    "theorem": 50,
    "pitfall": 50,
    "generatefirst": 50,
    "ordering": 30,
    "matching": 30,
}
DEFAULT_MIN_BACK_LENGTH = 30

# Card types where front-back duplication is structurally expected
# (e.g., cloze cards have the cloze in front; term cards have a name+definition
# pattern that may overlap by intent).
SKIP_DUPLICATE_CHECK_TYPES = {"cloze", "clozeterm", "term", "termbi"}

# Card types where empty backs should be tolerated (cloze cards encode the
# answer in the front via {{c1::...}} markers).
SKIP_EMPTY_CHECK_TYPES = {"cloze", "clozeterm"}

# Split thresholds (informational, per card_standards.md)
SPLIT_THRESHOLD_BY_TYPE: dict[str, int] = {
    "problem": 800,
    "vignette": 1000,
    "keyconcept": 700,
}


# ── Regex patterns ───────────────────────────────────────────────────────────


# Code fences (markdown style). Match opening ``` plus optional language
# plus content plus closing ```. Used to strip code from back when checking
# for purely-code-only backs (M1) or to skip TODO inside code (C3).
CODE_FENCE_RE = re.compile(r"```[a-zA-Z]*\n.*?\n```", re.DOTALL)

# Inline backticks
INLINE_CODE_RE = re.compile(r"`[^`]+?`", re.DOTALL)

# TODO/scaffold markers — detect when these are the SOLE substantive content
TODO_MARKER_RE = re.compile(
    r"\b(?:TODO|TBD|FIXME|PLACEHOLDER|XXX)\b", re.IGNORECASE
)

# Trailing ellipsis (real ``...`` not ``\\dots``). Allows trailing whitespace
# after the ellipsis.
TRAILING_ELLIPSIS_RE = re.compile(r"\.\.\.\s*$")

# Helper to build a lenient header regex that matches:
# - **Core Insight:**         (markdown bold)
# - <b>Core Insight:</b>      (HTML bold)
# - <strong>Core Insight:</strong>
# - Core Insight:             (plain, at start of line)
# The extractor strips \textbf{} to plain text per
# extract_cards.py:1026; the source-side bold is the user's intent
# but downstream tooling may strip it. Accept all variants — the
# structural intent (a header named "Core Insight" followed by a
# colon) is what we're auditing.
def _header_pattern(name: str) -> "re.Pattern[str]":
    """Build a regex that matches header *name* in markdown/HTML/plain forms.

    Matches at the start of a line (after optional whitespace) followed by
    optional bold markers, the header name, and a colon or period.
    """
    name_re = name.replace(" ", r"\s+")
    return re.compile(
        r"(?:"
        r"\*\*\s*" + name_re + r"\s*[:.]?\s*\*\*"          # markdown bold
        r"|<b>\s*" + name_re + r"\s*[:.]?\s*</b>"          # HTML <b>
        r"|<strong>\s*" + name_re + r"\s*[:.]?\s*</strong>" # HTML <strong>
        r"|(?:^|\n)\s*" + name_re + r"\s*:"                # plain start-of-line
        r")",
        re.IGNORECASE,
    )


# keyconcept canonical headers (H2)
# "Why It Matters" has accepted variants: "Decision Rule" (used in
# some guides for prescriptive concepts) — both express the practical
# implication of the Core Insight.
CORE_INSIGHT_RE = _header_pattern("Core Insight")
WHY_IT_MATTERS_RE = re.compile(
    _header_pattern("Why It Matters").pattern
    + "|"
    + _header_pattern("Decision Rule").pattern,
    re.IGNORECASE,
)
WHEN_IT_BREAKS_RE = _header_pattern("When It Breaks")

# formula canonical sections (H3)
VARIABLES_RE = _header_pattern("Variables?")
WHEN_TO_USE_RE = _header_pattern("When to Use")
INTUITION_RE = _header_pattern("Intuition")
MATH_INLINE_RE = re.compile(r"\\\(.*?\\\)|\$[^$\n]+\$", re.DOTALL)
MATH_DISPLAY_RE = re.compile(r"\\\[.*?\\\]|\$\$.*?\$\$", re.DOTALL)

# drill canonical sections (H4)
ANSWER_RE = _header_pattern("Answer")
TECHNIQUE_RE = _header_pattern("Technique")

# MCQ drill format — back contains lettered options A. / B. / C. / D. with
# at least one bolded option (the correct answer). Common in
# manning_llm_from_scratch and similar guides. This is a legitimate drill
# format per card_standards.md and should not trigger H4.
MCQ_OPTION_RE = re.compile(
    r"(?:^|\n)\s*[A-D]\.\s+\S",  # at least one A./B./C./D. option
    re.MULTILINE,
)
MCQ_BOLD_OPTION_RE = re.compile(
    r"\*\*[A-D]\.\s+[^*]+\*\*"
    r"|<b>\s*[A-D]\.\s+[^<]+</b>",
    re.IGNORECASE,
)

# comparison canonical structure (H5): pipe-table separator
PIPE_SEPARATOR_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$", re.MULTILINE)

# Evasive reference (M3): "see Chapter"/"refer to"/"see §" + ≤20 chars after
EVASIVE_REF_RE = re.compile(
    r"(?:see\s+(?:Chapter|Module|§|chapter|module|section)|refer\s+to)\b",
    re.IGNORECASE,
)

# Inline styling (M4)
INLINE_STYLING_RE = re.compile(
    r"\\textcolor\{|<font\b|<span\s+style|<i>|<b>", re.IGNORECASE
)


# ── Severity tiers ───────────────────────────────────────────────────────────


SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_INFO = "info"


# ── Finding dataclass ────────────────────────────────────────────────────────


@dataclass
class Finding:
    """A single back-content quality finding."""

    card_id: str
    card_type: str
    rule: str
    severity: str
    guide_slug: str
    filepath: str
    source_file: str
    source_macro: str
    front: str
    back_excerpt: str
    back_length: int
    detail: str = ""


# ── Detection rules ──────────────────────────────────────────────────────────


def _strip_code_blocks(back: str) -> str:
    """Remove fenced code blocks and inline backticks for prose-only checks."""
    out = CODE_FENCE_RE.sub("", back)
    out = INLINE_CODE_RE.sub("", out)
    return out


def _normalize_for_dup_check(text: str) -> str:
    """Lowercase + collapse whitespace for fuzzy duplicate detection."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _similarity(a: str, b: str) -> float:
    """Character-level similarity (Jaccard on character bigrams).

    Returns a float in [0, 1] where 1.0 means identical. Cheap O(n) approximation
    of Levenshtein-based similarity that's adequate for detecting near-duplicate
    front/back pairs.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    def bigrams(s: str) -> set[str]:
        return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    bg_a, bg_b = bigrams(a), bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    inter = len(bg_a & bg_b)
    union = len(bg_a | bg_b)
    return inter / union if union else 0.0


def check_c1_empty_back(back: str, card_type: str) -> tuple[str, str] | None:
    """C1 CRITICAL: Empty back (after strip)."""
    if card_type in SKIP_EMPTY_CHECK_TYPES:
        return None
    if not back or not back.strip():
        return ("C1", f"Empty back (length {len(back) if back else 0})")
    return None


def check_c2_whitespace_only(back: str, card_type: str) -> tuple[str, str] | None:
    """C2 CRITICAL: Whitespace or punctuation only."""
    if card_type in SKIP_EMPTY_CHECK_TYPES:
        return None
    if not back:
        return None
    stripped = re.sub(r"[\s\W_]", "", back)
    if not stripped and back.strip():
        return ("C2", f"Whitespace/punctuation only (raw len {len(back)})")
    return None


def check_c3_todo_only(back: str, card_type: str) -> tuple[str, str] | None:
    """C3 CRITICAL: TODO/TBD/FIXME/PLACEHOLDER as sole substantive content.

    Strip code fences first so a problem-card prompt with TODO inside an
    intentionally-incomplete code block doesn't false-positive.
    """
    if not back or not back.strip():
        return None
    prose = _strip_code_blocks(back).strip()
    # If after stripping code, what remains is only TODO markers (or nothing
    # but TODO + ellipsis), it's a scaffold.
    prose_no_punct = re.sub(r"[\s\W_]", "", prose)
    if not prose_no_punct:
        # prose is empty after stripping code — back is 100% code; if that
        # code contains TODO, it's likely a scaffold.
        if TODO_MARKER_RE.search(back):
            return ("C3", "Back is code-only with TODO/TBD/PLACEHOLDER markers")
        return None
    # Otherwise check if prose itself is dominantly TODO
    if TODO_MARKER_RE.search(prose) and len(prose_no_punct) < 40:
        return ("C3", f"Back is dominantly TODO/TBD scaffolding (prose len {len(prose)})")
    return None


def check_c4_front_back_duplicate(
    front: str, back: str, card_type: str
) -> tuple[str, str] | None:
    """C4 CRITICAL: Back is verbatim copy of front (≥85% similarity)."""
    if card_type in SKIP_DUPLICATE_CHECK_TYPES:
        return None
    if not front or not back:
        return None
    norm_front = _normalize_for_dup_check(front)
    norm_back = _normalize_for_dup_check(back)
    if len(norm_front) < 20 or len(norm_back) < 20:
        # Both must be substantive enough for similarity check to be meaningful
        return None
    sim = _similarity(norm_front, norm_back)
    if sim >= 0.85:
        return ("C4", f"Front-back duplicate (similarity {sim:.0%})")
    return None


def check_c5_truncated(back: str, card_type: str) -> tuple[str, str] | None:
    """C5 CRITICAL: Trailing ``...`` AND below per-type minimum length."""
    if not back:
        return None
    stripped = back.rstrip()
    if not TRAILING_ELLIPSIS_RE.search(stripped):
        return None
    min_len = MIN_BACK_LENGTH_BY_TYPE.get(card_type, DEFAULT_MIN_BACK_LENGTH)
    actual = len(stripped)
    if actual < min_len:
        return ("C5", f"Trailing '...' below per-type minimum ({actual} < {min_len})")
    return None


def check_h1_below_threshold(back: str, card_type: str) -> tuple[str, str] | None:
    """H1 HIGH: Below per-card-type minimum length."""
    if not back:
        return None
    if card_type in SKIP_EMPTY_CHECK_TYPES:
        return None
    min_len = MIN_BACK_LENGTH_BY_TYPE.get(card_type, DEFAULT_MIN_BACK_LENGTH)
    actual = len(back.strip())
    if actual == 0:
        return None  # C1 will catch
    if actual < min_len:
        return ("H1", f"Below {card_type} minimum ({actual} < {min_len})")
    return None


# Generic header marker — any \textbf{Name:} or **Name:** at start of
# a section. Used to detect alternative keyconcept structures (e.g.,
# comparison: "KG (explicit)" / "LLM (implicit)").
GENERIC_HEADER_RE = re.compile(
    r"(?:"
    r"\*\*\s*[A-Z][^*\n]{1,40}\s*[:.]\s*\*\*"            # **Name:**
    r"|<b>\s*[A-Z][^<\n]{1,40}\s*[:.]\s*</b>"            # <b>Name:</b>
    r"|<strong>\s*[A-Z][^<\n]{1,40}\s*[:.]\s*</strong>"  # <strong>Name:</strong>
    r"|(?:^|\n)\s*[A-Z][A-Za-z][A-Za-z\s/()'-]{1,40}\s*:\s+\S"  # Name: at line start
    r")",
)


def check_h2_keyconcept_structure(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """H2 HIGH: keyconcept lacks structural markers entirely.

    Accepts multiple legitimate structures per ``card_standards.md``:
    - Canonical 3-part: Core Insight + (Why It Matters | When It Breaks |
      Decision Rule)
    - Comparison/dichotomy: any 2+ distinct bold headers (e.g.,
      "KG (explicit) / LLM (implicit)", "Bottom-up / Purpose-driven")
    - Bidirectional: any 2+ distinct bold headers explaining a
      relationship from two sides

    Only fires when the keyconcept has NO structural markers at all —
    a wall of prose without any header signal that this is a structured
    pedagogical concept.
    """
    if card_type != "keyconcept":
        return None
    if not back:
        return None

    # Canonical form check
    has_core = bool(CORE_INSIGHT_RE.search(back))
    has_why = bool(WHY_IT_MATTERS_RE.search(back))
    has_when = bool(WHEN_IT_BREAKS_RE.search(back))
    if has_core and (has_why or has_when):
        return None

    # Alternative structure check: any 2+ generic headers
    headers = GENERIC_HEADER_RE.findall(back)
    # Deduplicate and require at least 2 distinct ones
    distinct_headers = {h.strip().lower() for h in headers}
    if len(distinct_headers) >= 2:
        return None

    # No canonical, no alternative structure — flag it
    return ("H2", "keyconcept has no structural markers (canonical 3-part nor 2+ alternative headers)")


def check_h3_formula_structure(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """H3 HIGH: formula missing math markers AND prose sections."""
    if card_type != "formula":
        return None
    if not back:
        return None
    has_math = bool(MATH_INLINE_RE.search(back) or MATH_DISPLAY_RE.search(back))
    has_variables = bool(VARIABLES_RE.search(back))
    has_when_to_use = bool(WHEN_TO_USE_RE.search(back) or INTUITION_RE.search(back))
    if has_math and (has_variables or has_when_to_use):
        return None
    missing = []
    if not has_math:
        missing.append("math markers ($...$ or \\[...\\])")
    if not has_variables:
        missing.append("Variables")
    if not has_when_to_use:
        missing.append("When to Use / Intuition")
    return ("H3", f"formula missing canonical sections: {', '.join(missing)}")


def check_h4_drill_structure(back: str, card_type: str) -> tuple[str, str] | None:
    """H4 HIGH: drill missing answer indicator.

    Per ``card_standards.md``, drills can use multiple legitimate formats:
    - **Answer:** + **Technique:** sections (canonical formal form)
    - MCQ format: A./B./C./D. options with one bolded as the correct answer
    - Short Q&A: terse answer text without explicit headers

    Only flag drills with NO recognizable answer indicator at all.
    """
    if card_type != "drill":
        return None
    if not back:
        return None

    # MCQ format: A. B. C. D. options with at least one bolded
    # (the correct answer). Legitimate per card_standards.md.
    has_mcq_options = bool(MCQ_OPTION_RE.search(back))
    has_bold_option = bool(MCQ_BOLD_OPTION_RE.search(back))
    if has_mcq_options and has_bold_option:
        return None

    # Canonical formal form: Answer + Technique sections
    has_answer = bool(ANSWER_RE.search(back))
    has_technique = bool(TECHNIQUE_RE.search(back))
    if has_answer:
        # Has Answer; Technique is optional but recommended. Only flag if
        # back is also short (suggesting both sections missing AND content
        # is thin) — covered by H1.
        return None

    # No MCQ, no Answer header — flag it
    return ("H4", "drill missing answer indicator (no MCQ-bold, no **Answer:**)")


def check_h5_comparison_structure(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """H5 HIGH: comparison/comparison3 missing pipe-table separator."""
    if card_type not in {"comparison", "comparison3"}:
        return None
    if not back:
        return None
    if PIPE_SEPARATOR_RE.search(back):
        return None
    return ("H5", f"{card_type} missing pipe-table separator (|---|)")


# Stub patterns for H6 — phrases that, when they comprise the entire
# Answer section, indicate a non-substantive pointer back to the body
# instead of a real answer recap.
ANSWER_STUB_PATTERNS = (
    "see solution above",
    "see above",
    "see solution",
    "see the answer",
    "as discussed above",
    "as discussed",
    "as shown above",
    "refer to solution",
    "refer to above",
)


def check_h6_answer_stub(back: str, card_type: str) -> tuple[str, str] | None:
    """H6 HIGH: Answer section is a non-substantive stub pointer.

    Targets the "See solution above" anti-pattern: Approach + Key Insight
    + Answer headers all present (so audit_solution_quality.py PASSES),
    but the Answer text is just a pointer back to the body. Useless for
    spaced repetition because the Anki card back ends with the stub.

    Only flags ``problem``/``vignette``/``drill`` cards. Stub detection
    is anchor-based: find the ``**Answer:**`` header, take ≤80 chars
    after it (or to next header), normalise, check against known stubs.
    """
    if card_type not in {"problem", "vignette", "drill"}:
        return None
    if not back:
        return None

    # Find the **Answer:** header (or HTML/plain variants per the
    # _header_pattern regexes already used by H4)
    match = ANSWER_RE.search(back)
    if not match:
        return None  # H4 covers missing-Answer; H6 is text-content only

    # Slice from after the Answer header to the next section header (or
    # end-of-back, whichever first). Look for **Foo:** or "% NEW:" or
    # \end{solution} to terminate.
    after = back[match.end() :]
    next_header = re.search(
        r"\*\*\s*[A-Z][^*\n]{1,40}\s*[:.]?\s*\*\*"
        r"|<b>\s*[A-Z][^<\n]{1,40}\s*[:.]?\s*</b>"
        r"|\\end\{solution\}",
        after,
    )
    answer_text = after[: next_header.start()] if next_header else after
    answer_text = answer_text.strip()

    # If the answer is short AND matches a stub pattern, flag it
    if len(answer_text) > 80:
        return None  # Substantive answer (>80 chars after Answer header)

    answer_lower = answer_text.lower().strip(" .,;:")
    for stub in ANSWER_STUB_PATTERNS:
        if stub in answer_lower:
            return ("H6", f"Answer is stub: '{answer_text[:50]}'")

    return None


def check_m1_code_only(back: str, card_type: str) -> tuple[str, str] | None:
    """M1 MEDIUM: Back is 100% code-fence with no surrounding prose."""
    if not back or not back.strip():
        return None
    prose = _strip_code_blocks(back).strip()
    if not prose and CODE_FENCE_RE.search(back):
        return ("M1", "Back is code-only with no prose explanation")
    return None


def check_m2_question_as_answer(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """M2 MEDIUM: Back ends with ``?`` (question instead of answer)."""
    if not back:
        return None
    stripped = back.rstrip()
    if stripped.endswith("?"):
        return ("M2", "Back ends with '?' — possibly question instead of answer")
    return None


def check_m3_evasive_reference(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """M3 MEDIUM: 'see Chapter X' followed by ≤20 chars (no substantive content)."""
    if not back:
        return None
    match = EVASIVE_REF_RE.search(back)
    if not match:
        return None
    before = _strip_code_blocks(back[:match.start()]).strip()
    before_words = re.findall(r"[A-Za-z0-9_]+", before)
    if len(before) >= 80 or len(before_words) >= 12:
        return None
    after = back[match.end():].strip()
    # Pull through one digit/section number, then check what's left
    after_pruned = re.sub(r"^[\s\d.,;:§\-–—]+", "", after)
    if len(after_pruned) <= 20:
        return ("M3", f"Evasive reference: '{match.group()}' with little content after")
    return None


def check_m4_inline_styling(back: str, card_type: str) -> tuple[str, str] | None:
    """M4 MEDIUM: Back contains inline styling (\\textcolor, HTML tags)."""
    if not back:
        return None
    if INLINE_STYLING_RE.search(back):
        return ("M4", "Back contains inline styling (\\textcolor / HTML tags)")
    return None


def check_i1_above_split_threshold(
    back: str, card_type: str
) -> tuple[str, str] | None:
    """I1 INFO: Back length above card_standards.md split threshold."""
    if not back:
        return None
    threshold = SPLIT_THRESHOLD_BY_TYPE.get(card_type)
    if threshold is None:
        return None
    actual = len(back.strip())
    if actual > threshold:
        return ("I1", f"{card_type} exceeds split threshold ({actual} > {threshold})")
    return None


# Severity classification for each rule
RULE_SEVERITY: dict[str, str] = {
    "C1": SEVERITY_CRITICAL,
    "C2": SEVERITY_CRITICAL,
    "C3": SEVERITY_CRITICAL,
    "C4": SEVERITY_CRITICAL,
    "C5": SEVERITY_CRITICAL,
    "H1": SEVERITY_HIGH,
    "H2": SEVERITY_HIGH,
    "H3": SEVERITY_HIGH,
    "H4": SEVERITY_HIGH,
    "H5": SEVERITY_HIGH,
    "H6": SEVERITY_HIGH,
    "M1": SEVERITY_MEDIUM,
    "M2": SEVERITY_MEDIUM,
    "M3": SEVERITY_MEDIUM,
    "M4": SEVERITY_MEDIUM,
    "I1": SEVERITY_INFO,
}

# Detection rule order: CRITICAL → HIGH → MEDIUM → INFO. Once a CRITICAL fires,
# we still check HIGH/MEDIUM (a card can have multiple findings).
ALL_CHECKS = [
    check_c1_empty_back,
    check_c2_whitespace_only,
    check_c3_todo_only,
    check_c5_truncated,
    check_h1_below_threshold,
    check_h2_keyconcept_structure,
    check_h3_formula_structure,
    check_h4_drill_structure,
    check_h5_comparison_structure,
    check_h6_answer_stub,
    check_m1_code_only,
    check_m2_question_as_answer,
    check_m3_evasive_reference,
    check_m4_inline_styling,
    check_i1_above_split_threshold,
]


def assess_card_back(card: dict[str, Any]) -> list[tuple[str, str]]:
    """Run all detection rules on a single card's back. Returns list of (rule_id, detail)."""
    front = str(card.get("front", "") or "")
    back = str(card.get("back", "") or "")
    card_type = card.get("type", "")
    findings: list[tuple[str, str]] = []

    # C4 needs both front and back; handle separately
    c4_result = check_c4_front_back_duplicate(front, back, card_type)
    if c4_result is not None:
        findings.append(c4_result)

    for check_fn in ALL_CHECKS:
        result = check_fn(back, card_type)
        if result is not None:
            findings.append(result)

    return findings


# ── Source location resolver ─────────────────────────────────────────────────


def resolve_source_location(
    card: dict[str, Any], guide: GuideInfo, repo_root: Path
) -> tuple[str, str, int]:
    """Resolve a card's originating chapter ``.tex`` file and approximate line.

    Returns (source_file_relative, source_macro, source_line_approx).
    Falls back to ("", "", 0) if resolution fails — non-fatal.
    """
    source = card.get("source", "")
    if not source:
        return ("", "", 0)

    # source is like "vol0/03_m3_coding_attention_mechanisms.tex"
    # Look in <guide>/notes/notebook/chapters/ first, then appendices/
    chapters_dir = guide.resolve_chapters_dir(repo_root)
    appendices_dir = chapters_dir.parent / "appendices"
    src_path_relative = source.split("/", 1)[-1] if "/" in source else source

    candidate = chapters_dir / src_path_relative
    if not candidate.exists():
        candidate = appendices_dir / src_path_relative
        if not candidate.exists():
            return (str(source), "", 0)

    rel_path = candidate.relative_to(repo_root)

    # Locate the macro by grep'ing for the card's slug or ID fragment
    card_id = card.get("id", "")
    # Card ID is like "<slug>-vol0-ch03-TERM-FOO_BAR" — pull the last
    # component (the slug after the last dash) to grep for
    id_tail = card_id.rsplit("-", 1)[-1] if "-" in card_id else ""
    front = card.get("front", "")

    # Try grepping for the macro pattern. \term[ID]{Name}{... uses the front
    # as the second argument; grep for the front's first 30 chars.
    front_grep = front[:30].strip() if front else ""

    line_no = 0
    macro_excerpt = ""
    try:
        text = candidate.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            # Match by front (most reliable) or by id_tail in macro args
            if front_grep and front_grep in line:
                # Ensure it's a card-extraction macro, not just prose
                if any(
                    macro in line
                    for macro in (
                        "\\term",
                        "\\keyconcept",
                        "\\problem",
                        "\\vignette",
                        "\\drill",
                        "\\formula",
                        "\\redflag",
                        "\\checkpoint",
                        "\\interview",
                        "\\interviewcontext",
                        "\\decisiontree",
                        "\\levelcard",
                        "\\comparison",
                        "\\sixtysec",
                        "\\interviewtip",
                        "\\starstory",
                        "\\paradox",
                        "\\actuarialbridge",
                        "\\cloze",
                        "\\clozeterm",
                        "\\termbi",
                        "\\mathdef",
                        "\\proposition",
                        "\\theorem",
                        "\\pitfall",
                        "\\generatefirst",
                    )
                ):
                    line_no = i
                    macro_excerpt = line.strip()[:120]
                    break
        if line_no == 0 and id_tail:
            for i, line in enumerate(text.splitlines(), 1):
                if id_tail.replace("_", " ").lower() in line.lower():
                    line_no = i
                    macro_excerpt = line.strip()[:120]
                    break
    except OSError:
        pass

    return (str(rel_path), macro_excerpt, line_no)


# ── Guide audit ──────────────────────────────────────────────────────────────


@dataclass
class GuideMetrics:
    """Back-content quality metrics for a guide."""

    slug: str
    total_cards: int = 0
    by_severity: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_rule: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_card_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    findings: list[Finding] = field(default_factory=list)


def audit_guide(guide: GuideInfo, repo_root: Path) -> GuideMetrics | None:
    """Audit back-content quality for a guide's cards."""
    cards_dir = guide.resolve_cards_dir(repo_root)
    if not cards_dir.exists():
        return None

    metrics = GuideMetrics(slug=guide.slug)

    # Prefer all_cards.yml; fall back to per-chapter glob.
    all_cards_path = cards_dir / "all_cards.yml"
    if all_cards_path.exists():
        card_files = [all_cards_path]
    else:
        card_files = sorted(cards_dir.glob("*_cards.yml"))

    for cards_file in card_files:
        try:
            with open(cards_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"Failed to parse {cards_file}: {exc}") from exc
        cards = data.get("cards", []) if isinstance(data, dict) else []

        for card in cards:
            metrics.total_cards += 1
            findings = assess_card_back(card)
            if not findings:
                continue

            source_file, source_macro, source_line = resolve_source_location(
                card, guide, repo_root
            )

            for rule_id, detail in findings:
                severity = RULE_SEVERITY[rule_id]
                metrics.by_severity[severity] += 1
                metrics.by_rule[rule_id] += 1
                card_type = card.get("type", "")
                metrics.by_card_type[card_type] += 1

                front_excerpt = (card.get("front") or "")[:80]
                back_excerpt = (card.get("back") or "")[:120]
                back_length = len((card.get("back") or "").strip())

                metrics.findings.append(
                    Finding(
                        card_id=card.get("id", "<no-id>"),
                        card_type=card_type,
                        rule=rule_id,
                        severity=severity,
                        guide_slug=guide.slug,
                        filepath=str(cards_file.relative_to(repo_root)),
                        source_file=source_file,
                        source_macro=source_macro,
                        front=front_excerpt,
                        back_excerpt=back_excerpt,
                        back_length=back_length,
                        detail=detail,
                    )
                )

    return metrics


# ── Output ───────────────────────────────────────────────────────────────────


def write_per_guide_json(metrics: GuideMetrics, repo_root: Path) -> Path:
    """Write per-guide JSON to <guide>/review/back_content_audit_<DATE>.json (layout-agnostic)."""
    guide_dir = guide_dir_for_slug(metrics.slug) or (repo_root / metrics.slug)
    review_dir = guide_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    out_path = review_dir / f"back_content_audit_{date_str}.json"
    payload = {
        "guide": metrics.slug,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "total_cards": metrics.total_cards,
        "by_severity": dict(metrics.by_severity),
        "by_rule": dict(metrics.by_rule),
        "by_card_type": dict(metrics.by_card_type),
        "findings": [asdict(f) for f in metrics.findings],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    return out_path


def write_fleet_report(
    all_metrics: list[GuideMetrics], repo_root: Path
) -> Path:
    """Write fleet-wide markdown summary to reports/qa_back_content_<DATE>.md."""
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    out_path = reports_dir / f"qa_back_content_{date_str}.md"

    lines: list[str] = []
    lines.append(f"# Back-Content Quality Audit — {date_str}")
    lines.append("")
    lines.append(f"Guides audited: {len(all_metrics)}")
    total_cards = sum(m.total_cards for m in all_metrics)
    total_critical = sum(m.by_severity.get("critical", 0) for m in all_metrics)
    total_high = sum(m.by_severity.get("high", 0) for m in all_metrics)
    total_medium = sum(m.by_severity.get("medium", 0) for m in all_metrics)
    total_info = sum(m.by_severity.get("info", 0) for m in all_metrics)
    lines.append(f"Total cards: {total_cards}")
    lines.append(f"CRITICAL: {total_critical} | HIGH: {total_high} | "
                 f"MEDIUM: {total_medium} | INFO: {total_info}")
    lines.append("")

    lines.append("## Per-guide breakdown (sorted by CRITICAL+HIGH desc)")
    lines.append("")
    lines.append("| Guide | Cards | C | H | M | I |")
    lines.append("|---|---|---|---|---|---|")
    sorted_metrics = sorted(
        all_metrics,
        key=lambda m: -(
            m.by_severity.get("critical", 0) + m.by_severity.get("high", 0)
        ),
    )
    for m in sorted_metrics:
        lines.append(
            f"| {m.slug} | {m.total_cards} | "
            f"{m.by_severity.get('critical', 0)} | "
            f"{m.by_severity.get('high', 0)} | "
            f"{m.by_severity.get('medium', 0)} | "
            f"{m.by_severity.get('info', 0)} |"
        )

    lines.append("")
    lines.append("## Rule trigger counts (fleet-wide)")
    lines.append("")
    rule_totals: dict[str, int] = defaultdict(int)
    for m in all_metrics:
        for rule_id, count in m.by_rule.items():
            rule_totals[rule_id] += count
    lines.append("| Rule | Count | Severity |")
    lines.append("|---|---|---|")
    for rule_id in sorted(rule_totals.keys()):
        lines.append(
            f"| {rule_id} | {rule_totals[rule_id]} | {RULE_SEVERITY[rule_id]} |"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0] if __doc__ else "Audit card back-content"
    )
    parser.add_argument(
        "--guides",
        type=str,
        default=None,
        help="Comma-separated guide slugs (default: all guides)",
    )
    parser.add_argument(
        "--fail-on",
        choices=("critical", "high", "medium", "any"),
        default="critical",
        help="Severity threshold for non-zero exit (default: critical)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Skip per-guide JSON; only generate fleet report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print fleet results as JSON to stdout (no human report)",
    )
    args = parser.parse_args()

    repo_root = get_repo_root()

    # Resolve guide set
    if args.guides:
        slugs = [s.strip() for s in args.guides.split(",") if s.strip()]
        guides = []
        for slug in slugs:
            g = get_guide_by_slug(slug)
            if g is None:
                raise ValueError(f"Unknown guide slug: {slug}")
            guides.append(g)
    else:
        guides = get_all_guides()

    all_metrics: list[GuideMetrics] = []
    for guide in guides:
        if not guide.has_chapters(repo_root):
            continue
        metrics = audit_guide(guide, repo_root)
        if metrics is None:
            continue
        all_metrics.append(metrics)
        if not args.report_only:
            write_per_guide_json(metrics, repo_root)

    report_path = write_fleet_report(all_metrics, repo_root)

    if args.json:
        print(json.dumps(
            {
                "guides": len(all_metrics),
                "total_cards": sum(m.total_cards for m in all_metrics),
                "by_severity": {
                    "critical": sum(m.by_severity.get("critical", 0) for m in all_metrics),
                    "high": sum(m.by_severity.get("high", 0) for m in all_metrics),
                    "medium": sum(m.by_severity.get("medium", 0) for m in all_metrics),
                    "info": sum(m.by_severity.get("info", 0) for m in all_metrics),
                },
                "report": str(report_path.relative_to(repo_root)),
            },
            indent=2,
        ))
    else:
        # Print human summary
        print(f"\n{'=' * 60}")
        print("BACK-CONTENT QUALITY AUDIT — course_learning")
        print(f"{'=' * 60}")
        print(f"\nGuides audited: {len(all_metrics)}")
        total_cards = sum(m.total_cards for m in all_metrics)
        total_c = sum(m.by_severity.get("critical", 0) for m in all_metrics)
        total_h = sum(m.by_severity.get("high", 0) for m in all_metrics)
        total_m = sum(m.by_severity.get("medium", 0) for m in all_metrics)
        total_i = sum(m.by_severity.get("info", 0) for m in all_metrics)
        print(f"Total cards: {total_cards}")
        print(f"\nCRITICAL: {total_c}")
        print(f"HIGH:     {total_h}")
        print(f"MEDIUM:   {total_m}")
        print(f"INFO:     {total_i}")
        print(f"\nReport: {report_path.relative_to(repo_root)}")

        # Top-10 worst guides
        print(f"\n{'-' * 60}")
        print(f"{'Guide':<48} {'Crit':>5} {'High':>5} {'Med':>5}")
        print("-" * 60)
        for m in sorted(
            all_metrics,
            key=lambda x: -(
                x.by_severity.get("critical", 0) + x.by_severity.get("high", 0)
            ),
        )[:10]:
            print(
                f"  {m.slug:<46} "
                f"{m.by_severity.get('critical', 0):>5} "
                f"{m.by_severity.get('high', 0):>5} "
                f"{m.by_severity.get('medium', 0):>5}"
            )
        print(f"{'=' * 60}\n")

    # Exit code
    threshold_map = {
        "critical": [SEVERITY_CRITICAL],
        "high": [SEVERITY_CRITICAL, SEVERITY_HIGH],
        "medium": [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM],
        "any": [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_INFO],
    }
    failing_severities = threshold_map[args.fail_on]
    failed = any(
        m.by_severity.get(sev, 0) > 0
        for m in all_metrics
        for sev in failing_severities
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
