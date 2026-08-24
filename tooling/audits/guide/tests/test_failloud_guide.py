"""Fail-loud behavior of per-guide audits (gt#23).

Representative handlers per module class: an unreadable or malformed file
degrades (skip / empty result) but must announce itself on stderr with a
``[audit-error]`` line — never vanish silently from the audit's denominator.
"""

from tooling.audits.guide import (
    audit_atomicity,
    audit_content_freshness,
    audit_term_consistency,
)

NON_UTF8 = b"\xff\xfe\x00 not utf-8 \x9c"


def test_atomicity_malformed_cards_warns(tmp_path, capsys):
    p = tmp_path / "all_cards.yml"
    p.write_text("cards: [unclosed\n")
    assert audit_atomicity.load_cards(p) == []
    err = capsys.readouterr().err
    assert "[audit-error] audit_atomicity" in err
    assert "all_cards.yml" in err


def test_atomicity_missing_file_is_silent_empty(tmp_path, capsys):
    # Missing is a legitimate "no cards" state, not an error.
    assert audit_atomicity.load_cards(tmp_path / "absent.yml") == []
    assert capsys.readouterr().err == ""


def test_term_consistency_unreadable_file_warns(tmp_path, capsys):
    p = tmp_path / "ch.tex"
    p.write_bytes(NON_UTF8)
    result = audit_term_consistency.extract_terms_from_file(p, "g", tmp_path)
    assert result == []
    err = capsys.readouterr().err
    assert "[audit-error] audit_term_consistency" in err


def test_freshness_unreadable_file_warns_not_fresh(tmp_path, capsys):
    p = tmp_path / "ch.tex"
    p.write_bytes(NON_UTF8)
    assert audit_content_freshness.scan_file(p, "g") == []
    err = capsys.readouterr().err
    assert "[audit-error] audit_content_freshness" in err


def test_freshness_readable_file_still_scans(tmp_path, capsys):
    p = tmp_path / "ch.tex"
    p.write_text("plain current content, nothing stale\n")
    assert audit_content_freshness.scan_file(p, "g") == []
    assert capsys.readouterr().err == ""
