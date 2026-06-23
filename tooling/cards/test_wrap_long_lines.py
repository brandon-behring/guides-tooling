"""Tests for the card-level very_long_line breaker (wrap_long_lines)."""
import re

from tooling.cards.extract_cards import _has_unclosed_math
from tooling.cards.wrap_long_lines import THRESHOLD, wrap_card, wrap_long_text


def _maxline(t: str) -> int:
    return max(len(l.strip()) for l in t.split("\n"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_breaks_long_prose_under_threshold():
    prose = (
        "The first idea is that graphs encode relationships explicitly. "
        "The second idea is that message passing aggregates neighbour features over hops. "
        "The third idea is that attention can replace fixed aggregation when structure is a bias. "
        "The fourth idea is that scale eventually favours learned methods over heuristics."
    )
    w = wrap_long_text(prose)
    assert _maxline(prose) > THRESHOLD
    assert _maxline(w) <= THRESHOLD
    # content preserved (only newlines added)
    assert _norm(w) == _norm(prose)


def test_never_breaks_inside_math():
    s = (
        "Define the regularised objective " + ("x" * 60)
        + " as $\\sum_{i=1}^{n} (y_i - \\hat{y}_i)^2 + \\lambda \\sum_j w_j^2 "
        "\\text{ over " + ("a " * 40) + "} $ and continue with prose after it closes."
    )
    w = wrap_long_text(s)
    # every prefix ending at a newline boundary must leave math balanced
    segs = w.split("\n")
    for i in range(len(segs)):
        assert _has_unclosed_math("\n".join(segs[: i + 1])) is None
    # the $...$ region itself contains no inserted newline
    region = re.search(r"\$.*?\$", w, re.DOTALL)
    assert region and "\n" not in region.group(0)


def test_unbreakable_token_left_intact():
    url = "See https://example.com/" + ("a" * 250) + " for details"
    w = wrap_long_text(url)
    assert "https://example.com/" + ("a" * 250) in w  # URL not split/corrupted


def test_short_text_unchanged_and_idempotent():
    short = "A short card back with no long line."
    assert wrap_long_text(short) == short
    long = "Sentence one is here. " * 20
    once = wrap_long_text(long)
    assert wrap_long_text(once) == once  # idempotent


def test_wrap_card_only_touches_text_fields():
    card = {
        "id": "x-1-1-TERM-foo",
        "type": "term",
        "front": "Term",
        "back": "Definition sentence one. " * 15,
    }
    before_id = card["id"]
    changed = wrap_card(card)
    assert changed is True
    assert card["id"] == before_id  # id untouched
    assert _norm(card["back"]) == _norm("Definition sentence one. " * 15)
