"""guide_health fail-loud behavior (gt#23).

The defect: a malformed ``all_cards.yml`` returned ``[]`` — indistinguishable
from "this guide has no cards", so card health silently disappeared from the
dashboard. Now a parse error is a distinct ``None`` that surfaces as a RED
card-health row with an error message.
"""

from types import SimpleNamespace

from tooling.qa import guide_health


def test_load_cards_missing_file_is_empty(tmp_path, capsys):
    assert guide_health._load_cards(tmp_path / "absent.yml") == []
    assert capsys.readouterr().err == ""


def test_load_cards_valid_file_loads(tmp_path):
    p = tmp_path / "all_cards.yml"
    p.write_text("cards:\n  - id: a\n    back: x\n")
    cards = guide_health._load_cards(p)
    assert isinstance(cards, list) and cards[0]["id"] == "a"


def test_load_cards_malformed_is_none_and_warns(tmp_path, capsys):
    p = tmp_path / "all_cards.yml"
    p.write_text("cards: [unclosed\n")
    assert guide_health._load_cards(p) is None
    assert "[audit-error] guide_health.cards" in capsys.readouterr().err


def test_evaluate_card_health_malformed_is_red_error(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "all_cards.yml"
    bad.write_text("cards: [unclosed\n")
    monkeypatch.setattr(guide_health.layout, "cards_yaml", lambda gd: bad)
    config = SimpleNamespace(config_path=tmp_path / "guide_qa.yaml", name="X")

    result = guide_health.evaluate_card_health(config)

    assert result is not None
    assert result.status == "RED"
    assert result.error and "all_cards.yml" in result.error
    assert result.total_cards == 0
    capsys.readouterr()  # drain the [audit-error] line


def test_card_health_markdown_renders_error_row():
    result = guide_health.CardHealthResult(
        guide="X", total_cards=0, cards_with_los=0, traceability_pct=0.0,
        presentation_issues=0, presentation_clean_pct=0.0, id_collisions=0,
        status="RED", error="unreadable or malformed all_cards.yml",
    )
    md = guide_health.card_health_markdown(result)
    assert "| Error | unreadable or malformed all_cards.yml |" in md
