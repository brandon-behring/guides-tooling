"""Fail-loud behavior of per-guide audits (gt#23).

Representative handlers per module class: an unreadable or malformed file
degrades (skip / empty result) but must announce itself on stderr with a
``[audit-error]`` line — never vanish silently from the audit's denominator.
"""

from tooling.audits.guide import (
    audit_atomicity,
    audit_box_styles,
    audit_checkpoint_bloom_verbs,
    audit_checkpoint_originality,
    audit_content_freshness,
    audit_content_substance,
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


# ── gt#33 row 8: the strict-gated guide audits must not fail OPEN ─────────────
# A directory named like a chapter makes read_text raise IsADirectoryError.

def _guide_with_unreadable_chapter(tmp_path):
    ch = tmp_path / "guide" / "chapters"
    ch.mkdir(parents=True)
    (ch / "01_m1_a.tex").write_text(
        "\\item[X-1.1] Explain the unique chapter idea in your own words without any reuse here.\n"
        "\\end{enumerate}\n"
    )
    (ch / "02_m2_b.tex").mkdir()
    return tmp_path


def test_bloom_verbs_unreadable_chapter_reported(tmp_path, capsys):
    unreadable: list[str] = []
    leaks = audit_checkpoint_bloom_verbs.find_bloom_leaks(_guide_with_unreadable_chapter(tmp_path), unreadable)
    assert leaks == []
    assert unreadable == ["02_m2_b.tex"]
    assert "[audit-error] audit_checkpoint_bloom_verbs" in capsys.readouterr().err


def test_originality_unreadable_chapter_reported(tmp_path, capsys):
    unreadable: list[str] = []
    total, templated = audit_checkpoint_originality.find_template_tails(
        _guide_with_unreadable_chapter(tmp_path), unreadable)
    assert (total, templated, unreadable) == (1, [], ["02_m2_b.tex"])
    assert "[audit-error] audit_checkpoint_originality" in capsys.readouterr().err


def test_box_styles_unreadable_chapter_reported(tmp_path, capsys):
    unreadable: list[str] = []
    audit_box_styles._used_styles(_guide_with_unreadable_chapter(tmp_path), unreadable)
    assert unreadable == ["02_m2_b.tex"]
    assert "[audit-error] audit_box_styles" in capsys.readouterr().err


def test_box_styles_absent_sty_is_silent(tmp_path, capsys):
    # An optional sty that does not exist is a legitimate no-op, not an error.
    assert audit_box_styles._read(tmp_path / "absent.sty") == ""
    assert capsys.readouterr().err == ""


def test_content_substance_unreadable_counted(tmp_path, capsys):
    s = audit_content_substance.measure(_guide_with_unreadable_chapter(tmp_path))
    assert s.unreadable == 1
    assert "[audit-error] audit_content_substance" in capsys.readouterr().err
