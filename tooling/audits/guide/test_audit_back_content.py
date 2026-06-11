"""Unit tests for ``audit_back_content.py`` detection rules.

Run with::

    cd ~/Claude/course_learning && python3 -m pytest \\
        shared/audits/test_audit_back_content.py -v
"""

from __future__ import annotations

import pytest

from tooling.audits.guide.audit_back_content import (
    assess_card_back,
    check_c1_empty_back,
    check_c2_whitespace_only,
    check_c3_todo_only,
    check_c4_front_back_duplicate,
    check_c5_truncated,
    check_h1_below_threshold,
    check_h2_keyconcept_structure,
    check_h3_formula_structure,
    check_h4_drill_structure,
    check_h5_comparison_structure,
    check_h6_answer_stub,
    check_i1_above_split_threshold,
    check_m1_code_only,
    check_m2_question_as_answer,
    check_m3_evasive_reference,
    check_m4_inline_styling,
)


# ── C1: Empty back ───────────────────────────────────────────────────────────


def test_c1_fires_on_empty_string() -> None:
    assert check_c1_empty_back("", "term") is not None


def test_c1_fires_on_whitespace_only() -> None:
    assert check_c1_empty_back("   \n  ", "term") is not None


def test_c1_skips_cloze_cards() -> None:
    assert check_c1_empty_back("", "cloze") is None
    assert check_c1_empty_back("", "clozeterm") is None


def test_c1_no_fire_on_substantive_back() -> None:
    assert check_c1_empty_back("This is a real definition.", "term") is None


# ── C2: Whitespace/punct only ────────────────────────────────────────────────


def test_c2_fires_on_punctuation_only() -> None:
    assert check_c2_whitespace_only("...   ;;;", "term") is not None


def test_c2_no_fire_on_real_content() -> None:
    assert check_c2_whitespace_only("Real content.", "term") is None


# ── C3: TODO/scaffold only ───────────────────────────────────────────────────


def test_c3_fires_on_code_only_with_todo() -> None:
    back = "```python\n# TODO: implement\npass\n```"
    assert check_c3_todo_only(back, "problem") is not None


def test_c3_no_fire_on_complete_problem_with_todo_in_prompt() -> None:
    """A complete problem card might have TODO in the question text — that's
    legitimate. Only fire when TODO is the dominant content."""
    back = (
        "**Approach:** Start by implementing the TODO function.\n\n"
        "**Step 1:** Define the input/output types.\n"
        "**Step 2:** Add validation logic.\n\n"
        "**Key Insight:** The TODO marker indicates intent, not absence.\n\n"
        "**Answer:** A complete implementation requires type hints and validation."
    )
    # Has substantive prose — not a scaffold
    assert check_c3_todo_only(back, "problem") is None


def test_c3_no_fire_on_no_todo() -> None:
    assert check_c3_todo_only("Real implementation here", "problem") is None


# ── C4: Front-back duplicate ─────────────────────────────────────────────────


def test_c4_fires_on_verbatim_duplicate() -> None:
    front = "What is the primary use of cosine similarity in retrieval systems?"
    back = "What is the primary use of cosine similarity in retrieval systems?"
    result = check_c4_front_back_duplicate(front, back, "checkpoint")
    assert result is not None


def test_c4_skips_term_cards() -> None:
    """Term cards have a structural pattern that may overlap; skip them."""
    front = "Cosine Similarity"
    back = "Cosine Similarity is the angle between two vectors."
    assert check_c4_front_back_duplicate(front, back, "term") is None


def test_c4_skips_cloze() -> None:
    assert check_c4_front_back_duplicate("anything", "anything", "cloze") is None


def test_c4_no_fire_on_distinct_content() -> None:
    front = "What is cosine similarity?"
    back = "An angle-based metric used to compare embedding vectors."
    assert check_c4_front_back_duplicate(front, back, "checkpoint") is None


# ── C5: Truncated ────────────────────────────────────────────────────────────


def test_c5_fires_on_short_back_with_trailing_ellipsis() -> None:
    # term minimum is 40; 25-char back ends with ...
    short = "Cosine sim is angle..."
    assert check_c5_truncated(short, "term") is not None


def test_c5_no_fire_on_long_back_with_ellipsis() -> None:
    # Above minimum even with ellipsis (legitimate trailing dots on a substantive answer)
    long_back = "A " + "very " * 30 + "thorough definition that ends with..."
    assert check_c5_truncated(long_back, "term") is None


def test_c5_no_fire_on_no_ellipsis() -> None:
    assert check_c5_truncated("Short.", "term") is None


# ── H1: Below threshold ──────────────────────────────────────────────────────


def test_h1_fires_on_short_keyconcept() -> None:
    # keyconcept min 100 chars
    assert check_h1_below_threshold("Too short.", "keyconcept") is not None


def test_h1_no_fire_on_substantive_keyconcept() -> None:
    long_back = "A " * 60  # ~120 chars
    assert check_h1_below_threshold(long_back, "keyconcept") is None


def test_h1_uses_default_for_unknown_type() -> None:
    """Unknown card type should use the 30-char default."""
    assert check_h1_below_threshold("ab", "unknown_type") is not None


def test_h1_skips_cloze() -> None:
    assert check_h1_below_threshold("", "cloze") is None


# ── H2: keyconcept structure ─────────────────────────────────────────────────


def test_h2_fires_on_prose_only_keyconcept() -> None:
    back = "This concept is important for production systems."
    assert check_h2_keyconcept_structure(back, "keyconcept") is not None


def test_h2_passes_with_canonical_headers() -> None:
    back = (
        "**Core Insight:** Embedding norms can drift.\n\n"
        "**Why It Matters:** Drift breaks similarity ranking.\n\n"
        "**When It Breaks:** Catastrophic on long-tail terms."
    )
    assert check_h2_keyconcept_structure(back, "keyconcept") is None


def test_h2_partial_pass_with_core_and_why() -> None:
    """Core Insight + Why It Matters is acceptable (When It Breaks optional)."""
    back = "**Core Insight:** X.\n\n**Why It Matters:** Y."
    assert check_h2_keyconcept_structure(back, "keyconcept") is None


def test_h2_skips_non_keyconcept() -> None:
    assert check_h2_keyconcept_structure("anything", "term") is None


# ── H3: formula structure ────────────────────────────────────────────────────


def test_h3_fires_on_prose_only_formula() -> None:
    back = "This formula is used for attention scoring."
    assert check_h3_formula_structure(back, "formula") is not None


def test_h3_passes_with_math_and_variables() -> None:
    back = (
        "$$Q K^T / \\sqrt{d_k}$$\n\n"
        "**Variables:** $Q, K$ are projections.\n"
        "**When to Use:** scaled attention."
    )
    assert check_h3_formula_structure(back, "formula") is None


# ── H4: drill structure ──────────────────────────────────────────────────────


def test_h4_fires_on_drill_with_no_answer_indicator() -> None:
    """A drill with no MCQ options, no Answer header — clearly missing."""
    back = "Some prose without any answer indication or option labels."
    assert check_h4_drill_structure(back, "drill") is not None


def test_h4_passes_with_answer_section_alone() -> None:
    """Answer section alone is sufficient (Technique is optional per standards)."""
    back = "**Answer:** 42"
    assert check_h4_drill_structure(back, "drill") is None


def test_h4_passes_with_answer_and_technique() -> None:
    back = "**Answer:** 42\n\n**Technique:** Multiply life by 6."
    assert check_h4_drill_structure(back, "drill") is None


def test_h4_passes_with_mcq_format() -> None:
    """MCQ format with bolded correct option is a legitimate drill style."""
    back = (
        "A. Wrong option\n"
        "B. Wrong option\n"
        "**C. The correct answer**\n"
        "D. Wrong option\n"
    )
    assert check_h4_drill_structure(back, "drill") is None


def test_h4_fires_on_mcq_without_bold() -> None:
    """MCQ options without any bolded answer — ambiguous, flag it."""
    back = (
        "A. Wrong option\n"
        "B. Maybe correct\n"
        "C. Possibly\n"
        "D. Unclear\n"
    )
    assert check_h4_drill_structure(back, "drill") is not None


# ── H5: comparison structure ─────────────────────────────────────────────────


def test_h5_fires_on_comparison_without_table() -> None:
    back = "Foo is faster but Bar is more accurate."
    assert check_h5_comparison_structure(back, "comparison") is not None


def test_h5_passes_with_pipe_table() -> None:
    back = (
        "| Dim | Foo | Bar |\n"
        "|---|---|---|\n"
        "| Speed | Fast | Slow |"
    )
    assert check_h5_comparison_structure(back, "comparison") is None


# ── H6: Answer stub ──────────────────────────────────────────────────────────


def test_h6_fires_on_classic_see_solution_above() -> None:
    back = (
        "**Approach:** Step 1, step 2.\n\n"
        "**Key Insight:** The bottleneck dominates.\n\n"
        "**Answer:** See solution above."
    )
    assert check_h6_answer_stub(back, "problem") is not None


def test_h6_no_fire_on_substantive_answer() -> None:
    back = (
        "**Approach:** Step 1.\n\n"
        "**Answer:** The end-to-end accuracy is 80.8% computed as "
        "0.95 * 0.85; both dimensions need to reach 97% to hit 95% e2e."
    )
    assert check_h6_answer_stub(back, "problem") is None


def test_h6_no_fire_on_math_only_answer() -> None:
    back = "**Approach:** ... \n\n**Answer:** $x = 0.5$, accuracy 80%."
    # 30+ chars, not in stub list — should pass
    assert check_h6_answer_stub(back, "problem") is None


def test_h6_skips_non_solution_card_types() -> None:
    back = "**Answer:** See solution above."
    assert check_h6_answer_stub(back, "term") is None
    assert check_h6_answer_stub(back, "keyconcept") is None


def test_h6_no_fire_on_card_without_answer_section() -> None:
    """H4 covers the missing-Answer case; H6 is text-content only."""
    back = "**Approach:** Step 1, step 2. **Key Insight:** Done."
    assert check_h6_answer_stub(back, "problem") is None


def test_h6_fires_on_alternate_stub_phrasing() -> None:
    """Detect 'see above', 'as discussed above' variants too."""
    back = "**Approach:** ...\n\n**Answer:** See above for details."
    assert check_h6_answer_stub(back, "problem") is not None


# ── M1: code-only ────────────────────────────────────────────────────────────


def test_m1_fires_on_pure_code_back() -> None:
    back = "```python\nx = 1\nprint(x)\n```"
    assert check_m1_code_only(back, "problem") is not None


def test_m1_no_fire_on_code_with_prose() -> None:
    back = "We compute x:\n```python\nx = 1\n```\nThen print it."
    assert check_m1_code_only(back, "problem") is None


# ── M2: question-as-answer ───────────────────────────────────────────────────


def test_m2_fires_on_back_ending_with_question() -> None:
    assert check_m2_question_as_answer("What do you think?", "checkpoint") is not None


def test_m2_no_fire_on_declarative_answer() -> None:
    assert check_m2_question_as_answer("The answer is 42.", "checkpoint") is None


# ── M3: evasive reference ────────────────────────────────────────────────────


def test_m3_fires_on_short_evasive_reference() -> None:
    back = "see Chapter 3."
    assert check_m3_evasive_reference(back, "checkpoint") is not None


def test_m3_no_fire_on_substantive_after_reference() -> None:
    back = "see Chapter 3 — specifically the discussion of cache invalidation strategies and their tradeoffs in distributed systems."
    assert check_m3_evasive_reference(back, "checkpoint") is None


def test_m3_no_fire_on_substantive_definition_before_reference() -> None:
    back = (
        "An auxiliary reward signal that incentivizes proper response structure "
        "alongside correctness during training. See Chapter 7."
    )
    assert check_m3_evasive_reference(back, "term") is None


# ── M4: inline styling ───────────────────────────────────────────────────────


def test_m4_fires_on_textcolor() -> None:
    back = "This is \\textcolor{red}{important}."
    assert check_m4_inline_styling(back, "term") is not None


def test_m4_fires_on_html_font_tag() -> None:
    back = "<font color='red'>warning</font>"
    assert check_m4_inline_styling(back, "term") is not None


# ── I1: above split threshold ────────────────────────────────────────────────


def test_i1_fires_on_long_problem() -> None:
    back = "x" * 900
    assert check_i1_above_split_threshold(back, "problem") is not None


def test_i1_no_fire_on_short_problem() -> None:
    assert check_i1_above_split_threshold("short", "problem") is None


def test_i1_no_fire_on_unknown_type() -> None:
    """No threshold defined for non-standard types."""
    assert check_i1_above_split_threshold("x" * 5000, "checkpoint") is None


# ── Integration: assess_card_back ────────────────────────────────────────────


def test_assess_card_back_empty_term_fires_c1_and_h1() -> None:
    card = {"id": "test", "type": "term", "front": "Foo", "back": ""}
    findings = assess_card_back(card)
    rules = {f[0] for f in findings}
    assert "C1" in rules


def test_assess_card_back_complete_keyconcept_no_findings() -> None:
    card = {
        "id": "test",
        "type": "keyconcept",
        "front": "Embedding Drift",
        "back": (
            "**Core Insight:** Embeddings drift over time.\n\n"
            "**Why It Matters:** Search relevance degrades.\n\n"
            "**When It Breaks:** Models trained on stale data."
        ),
    }
    findings = assess_card_back(card)
    assert findings == []


def test_assess_card_back_returns_multiple_findings() -> None:
    """A card can trip multiple rules simultaneously."""
    card = {
        "id": "test",
        "type": "drill",
        "front": "What is X?",
        "back": "X?",  # H1 (too short) + M2 (ends with ?) + H4 (no answer indicator)
    }
    findings = assess_card_back(card)
    rules = {f[0] for f in findings}
    assert "H1" in rules  # below 40-char drill min
    assert "M2" in rules  # ends with ?
    assert "H4" in rules  # no MCQ, no **Answer:**
