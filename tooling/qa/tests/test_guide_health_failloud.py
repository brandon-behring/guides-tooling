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


def test_load_cards_valid_yaml_wrong_shape_is_none(tmp_path, capsys):
    # `cards: wrong` is valid YAML but iterating the string would crash on .get
    # downstream (Codex finding #9). Must be treated as malformed, not returned.
    p = tmp_path / "all_cards.yml"
    p.write_text("cards: wrong\n")
    assert guide_health._load_cards(p) is None
    assert "[audit-error]" in capsys.readouterr().err


def test_load_cards_scalar_top_level_is_none(tmp_path, capsys):
    p = tmp_path / "all_cards.yml"
    p.write_text("just a bare string\n")
    assert guide_health._load_cards(p) is None
    assert "[audit-error]" in capsys.readouterr().err


def test_load_cards_list_of_non_dicts_is_none(tmp_path, capsys):
    p = tmp_path / "all_cards.yml"
    p.write_text("- a\n- b\n")
    assert guide_health._load_cards(p) is None
    assert "[audit-error]" in capsys.readouterr().err


def test_empty_yaml_is_empty_not_error(tmp_path, capsys):
    p = tmp_path / "all_cards.yml"
    p.write_text("")
    assert guide_health._load_cards(p) == []
    assert capsys.readouterr().err == ""


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


def test_json_mode_emits_card_error(tmp_path, monkeypatch, capsys):
    # Codex finding #8: --json hard-coded "error": None, defeating the channel.
    import json as _json

    bad = tmp_path / "all_cards.yml"
    bad.write_text("cards: [unclosed\n")
    monkeypatch.setattr(guide_health.layout, "cards_yaml", lambda gd: bad)
    monkeypatch.setattr(
        guide_health, "evaluate_metrics", lambda config, dry_run=False: []
    )

    class _Cfg:
        config_path = tmp_path / "guide_qa.yaml"
        name = "X"
        version = "1"

    monkeypatch.setattr(guide_health, "load_config", lambda c: _Cfg())
    monkeypatch.setattr("sys.argv", ["guide_health", "--json", "--no-save"])

    rc = guide_health.main()
    out = capsys.readouterr().out
    payload = _json.loads(out[out.index("[") :])
    card = next(d for d in payload if d["name"] == "card_health")
    assert card["status"] == "RED"
    assert card["error"] and "all_cards.yml" in card["error"]
    assert rc == 1


def test_card_health_markdown_renders_error_row():
    result = guide_health.CardHealthResult(
        guide="X", total_cards=0, cards_with_los=0, traceability_pct=0.0,
        presentation_issues=0, presentation_clean_pct=0.0, id_collisions=0,
        status="RED", error="unreadable or malformed all_cards.yml",
    )
    md = guide_health.card_health_markdown(result)
    assert "| Error | unreadable or malformed all_cards.yml |" in md
