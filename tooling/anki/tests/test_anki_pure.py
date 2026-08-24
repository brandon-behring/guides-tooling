"""First tests for the anki package (gt#28) — the 988-line package had zero.

Covers the pure text-transform core: GUID determinism, list auto-formatting,
math-delimiter conversion (incl. the currency-dollar heuristic), math-aware
HTML escaping, and the source→course/readable/topic mappers.
"""

import pytest

from tooling.anki import format_card_text as fct
from tooling.anki.anki_common import card_guid, deck_id_from_name
from tooling.anki.yaml_to_apkg import (
    card_type_to_topic,
    convert_math_delimiters,
    escape_html_outside_math,
    prefix_to_slug,
    source_to_course,
    source_to_readable,
)

# ── anki_common: deterministic IDs ───────────────────────────────────────────


def test_card_guid_deterministic_and_distinct():
    a = card_guid("Deck", "vol0-ch01-TERM-X")
    assert a == card_guid("Deck", "vol0-ch01-TERM-X")
    assert a != card_guid("Deck", "vol0-ch01-TERM-Y")
    assert a != card_guid("OtherDeck", "vol0-ch01-TERM-X")
    assert isinstance(a, int)


def test_deck_id_deterministic():
    assert deck_id_from_name("A::B") == deck_id_from_name("A::B")
    assert deck_id_from_name("A::B") != deck_id_from_name("A::C")


# ── format_card_text ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _formatting_enabled(monkeypatch):
    # Pin the env-derived flag so tests don't depend on AUTO_FORMAT_CARDS.
    monkeypatch.setattr(fct, "ENABLE_AUTO_FORMATTING", True)


def test_inline_numbered_list_gets_newlines():
    text = "Steps: 1) First item text, 2) Second item text, 3) Third item text"
    assert fct.format_card_text(text) == (
        "Steps:\n\n1) First item text\n2) Second item text\n3) Third item text"
    )


def test_list_without_prefix():
    text = "1) First item text, 2) Second item text, 3) Third item text"
    assert fct.format_card_text(text) == (
        "1) First item text\n2) Second item text\n3) Third item text"
    )


@pytest.mark.parametrize(
    "text",
    [
        "short text",  # under the 20-char floor
        "Already has\n1. formatted item lines in the text",  # existing newlines
        "Only 1) one item here, 2) two items here",  # fewer than 3 items
        "Gaps 1) first item text, 5) fifth item text, 9) ninth item text",  # not sequential
        "Short 1) a, 2) b, 3) c and other prose around them",  # items under 5 chars
        "Calculate NPV formula (1) uses r (2) uses t without commas",  # formula guard
    ],
)
def test_no_false_positive_reformat(text):
    assert fct.format_card_text(text) == text


def test_sequential_allows_gaps_of_two():
    assert fct.is_sequential(["1", "3", "5"]) is True
    assert fct.is_sequential(["1", "2", "3"]) is True
    assert fct.is_sequential(["1", "4"]) is False
    assert fct.is_sequential(["2", "1"]) is False
    assert fct.is_sequential(["1"]) is False
    assert fct.is_sequential(["a", "b"]) is False


def test_has_existing_newlines():
    assert fct.has_existing_newlines("intro\n1. item") is True
    assert fct.has_existing_newlines("inline 1. item") is False


# ── convert_math_delimiters ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$x+y$", r"\(x+y\)"),
        ("$$E=mc^2$$", r"\[E=mc^2\]"),
        ("no dollars here", "no dollars here"),
        (r"pre $\sim$ post", r"pre \(\sim\) post"),
        # Currency spans must NOT pair as math:
        ("$50-$150", "$50-$150"),  # trailing hyphen → not math; second $ unpaired
        ("costs $1.10/hr each", "costs $1.10/hr each"),  # '/' → not math
        ("about $5 per month", "about $5 per month"),  # 'per'/'month' keyword
        (r"escaped \$5 stays", "escaped \\$5 stays"),
        ("$a$ and $b$", r"\(a\) and \(b\)"),
    ],
)
def test_convert_math_delimiters(text, expected):
    assert convert_math_delimiters(text) == expected


def test_multiline_span_is_not_inline_math():
    text = "$a\nb$"
    assert convert_math_delimiters(text) == text


# ── escape_html_outside_math ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<|im_start|>", "&lt;|im_start|&gt;"),  # ChatML token: escape
        ("<p>keep</p>", "<p>keep</p>"),  # legitimate HTML: preserve
        ("<code>x</code>", "<code>x</code>"),
        ("a < b and c > d", "a &lt; b and c &gt; d"),
        ("<!-- note -->", "<!-- note -->"),  # comments preserved
        (r"\(a<b\)", r"\(a&lt;b\)"),  # inside math: angle escaped, span kept
        (r"\[x>y\]", r"\[x&gt;y\]"),
        ("<script>x</script>", "&lt;script&gt;x&lt;/script&gt;"),  # not on safe list
    ],
)
def test_escape_html_outside_math(text, expected):
    assert escape_html_outside_math(text) == expected


# ── slug/course/topic mappers ────────────────────────────────────────────────


def test_prefix_to_slug():
    assert prefix_to_slug("DE Course Guide") == "DE_Course_Guide"
    assert prefix_to_slug("a+b! c") == "a_b_c"


def test_source_to_course_legacy_and_new_patterns():
    assert source_to_course("vol0/01_c1m1_intro.tex", r"c([1-4])m\d+") == "c1"
    assert source_to_course("vol0/03_m5_topic.tex", r"(m\d+)_", key_prefix="") == "m5"
    assert source_to_course("vol0/A_reference.tex", r"c([1-4])m\d+") is None


def test_source_to_readable():
    assert (
        source_to_readable("vol0/01_c1m1_an_introduction.tex")
        == "Ch01: An Introduction"
    )
    assert source_to_readable("vol0/A_quick_reference.tex") == "App A: Quick Reference"
    assert source_to_readable("unrecognized.md") == "unrecognized.md"


def test_card_type_to_topic():
    assert card_type_to_topic({"type": "term", "source": "vol0/01_x.tex"}) == "Ch01 [Term]"
    assert card_type_to_topic({"type": "formula", "source": "vol0/A_ref.tex"}) == "App A [Formula]"
    assert card_type_to_topic({"type": "drill"}) == "[Drill]"
