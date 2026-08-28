"""Fail-loud behavior of the fleet audits (gt#23).

A malformed input must yield a visible RED / stderr ``[audit-error]`` line,
never a neutral value indistinguishable from a healthy scan.
"""

from pathlib import Path

import pytest

from tooling.audits.fleet import audit_all_courses, audit_gold, audit_silver


# ── audit_all_courses.check_bloom_levels ─────────────────────────────────────

def test_bloom_levels_malformed_yaml_is_red(tmp_path, capsys):
    (tmp_path / "guide_qa.yaml").write_text("los: [unclosed\n")
    status, detail = audit_all_courses.check_bloom_levels(tmp_path)
    assert status == "RED"
    assert "parse error" in detail
    # Codex finding #10: RED row AND the greppable stderr record.
    assert "[audit-error] audit_all_courses" in capsys.readouterr().err


def test_bloom_levels_wrong_shape_is_red(tmp_path):
    # A YAML scalar has no .get(); the handler must classify RED, not YELLOW.
    (tmp_path / "guide_qa.yaml").write_text("just a string\n")
    status, detail = audit_all_courses.check_bloom_levels(tmp_path)
    assert status == "RED"
    assert "parse error" in detail


def test_bloom_levels_valid_yaml_still_green(tmp_path):
    (tmp_path / "guide_qa.yaml").write_text(
        "los:\n  valid_levels: [Remember, Understand, Apply]\n"
    )
    status, detail = audit_all_courses.check_bloom_levels(tmp_path)
    assert status == "GREEN"
    assert "3 levels" in detail


# ── audit_silver.load_system_design_allowlist ────────────────────────────────

def _load_with(monkeypatch, capsys, path):
    monkeypatch.setattr(audit_silver, "SYSTEM_DESIGN_ALLOWLIST_PATH", path)
    result = audit_silver.load_system_design_allowlist()
    return result, capsys.readouterr().err


def test_allowlist_missing_warns(tmp_path, monkeypatch, capsys):
    result, err = _load_with(monkeypatch, capsys, tmp_path / "absent.yaml")
    assert result == set()
    assert "[audit-error]" in err and "missing" in err


def test_allowlist_unparseable_warns(tmp_path, monkeypatch, capsys):
    p = tmp_path / "a.yaml"
    p.write_text("required: [unclosed\n")
    result, err = _load_with(monkeypatch, capsys, p)
    assert result == set()
    assert "[audit-error]" in err and "unparseable" in err


def test_allowlist_not_a_mapping_warns(tmp_path, monkeypatch, capsys):
    p = tmp_path / "a.yaml"
    p.write_text("- just\n- a\n- list\n")
    result, err = _load_with(monkeypatch, capsys, p)
    assert result == set()
    assert "[audit-error]" in err and "not a mapping" in err


def test_allowlist_missing_required_key_warns(tmp_path, monkeypatch, capsys):
    p = tmp_path / "a.yaml"
    p.write_text("other_key: [x]\n")
    result, err = _load_with(monkeypatch, capsys, p)
    assert result == set()
    assert "[audit-error]" in err and "required" in err


def test_allowlist_valid_loads_silently(tmp_path, monkeypatch, capsys):
    p = tmp_path / "a.yaml"
    p.write_text("required:\n  - guide_a\n  - guide_b\n")
    result, err = _load_with(monkeypatch, capsys, p)
    assert result == {"guide_a", "guide_b"}
    assert err == ""


# ── audit_gold fail-loud (gt#33 row 8) ───────────────────────────────────────
# A directory named like a chapter makes read_text raise IsADirectoryError -- a
# portable "exists but unreadable" fixture.

def _chapters(tmp_path, files: dict[str, str]) -> Path:
    ch = tmp_path / "guide" / "chapters"
    ch.mkdir(parents=True)
    for name, body in files.items():
        (ch / name).write_text(body, encoding="utf-8")
    return ch


def test_gold_stub_counter_reports_unreadable_chapter(tmp_path, capsys):
    ch = _chapters(tmp_path, {"01_m1_a.tex": "\\item[X-1.1] a genuine prompt with more than ten words in its body\n\\end{enumerate}\n"})
    (ch / "02_m2_b.tex").mkdir()
    total, stubs, unreadable = audit_gold.count_stub_checkpoint_items(ch)
    assert (total, stubs) == (1, 0)
    assert unreadable == ["02_m2_b.tex"]
    assert "[audit-error] audit_gold.G1" in capsys.readouterr().err


def test_gold_g1_detail_names_unreadable_and_fails(tmp_path, monkeypatch, capsys):
    ch = _chapters(tmp_path, {"01_m1_a.tex": "prose\n"})
    (ch / "02_m2_b.tex").mkdir()
    monkeypatch.setattr(audit_gold, "run_guide_audit", lambda *_a, **_k: (0, "coverage 100.0%"))
    g = audit_gold.check_gate1_retrieval("x", tmp_path)
    assert not g.passed
    assert "unreadable: 02_m2_b.tex" in g.detail
    capsys.readouterr()


def test_gold_g4_unreadable_chapter_fails(tmp_path, capsys):
    ch = _chapters(tmp_path, {f"0{i}_m{i}_x.tex": "\\crossrefmargin{see the other guide}\n" for i in (1, 2, 3)})
    (ch / "04_m4_y.tex").mkdir()
    g = audit_gold.check_gate4_crossref(tmp_path)
    assert not g.passed
    assert "unreadable: 04_m4_y.tex" in g.detail
    assert "[audit-error] audit_gold.G4" in capsys.readouterr().err


def test_gold_load_guide_qa_malformed_raises(tmp_path, capsys):
    (tmp_path / "guide_qa.yaml").write_text("gold: [unclosed\n")
    with pytest.raises(ValueError, match="unreadable guide_qa.yaml"):
        audit_gold.load_guide_qa(tmp_path)
    assert "[audit-error] audit_gold.load_guide_qa" in capsys.readouterr().err


def test_gold_load_guide_qa_non_mapping_raises(tmp_path, capsys):
    (tmp_path / "guide_qa.yaml").write_text("just a string\n")
    with pytest.raises(ValueError, match="malformed guide_qa.yaml"):
        audit_gold.load_guide_qa(tmp_path)
    capsys.readouterr()


def test_gold_load_guide_qa_absent_or_empty_is_empty_dict(tmp_path):
    assert audit_gold.load_guide_qa(tmp_path) == {}
    (tmp_path / "guide_qa.yaml").write_text("")
    assert audit_gold.load_guide_qa(tmp_path) == {}


def test_gold_g5_unreadable_is_scaffold_only(tmp_path, capsys):
    review = audit_gold.layout.review_dir(tmp_path)
    review.mkdir(parents=True)
    (review / "gold_audit_20260828.md").mkdir()  # exists, cannot be read
    g, reason = audit_gold.check_gate5_fidelity(tmp_path)
    assert not g.passed and reason == "unreadable"
    r = audit_gold.HonestReport(slug="x", gates=[g], g5_reason=reason)
    assert r.classification == "SCAFFOLD-ONLY"   # exit 1, never GOLD-ELIGIBLE
    assert "[audit-error] audit_gold.G5" in capsys.readouterr().err


def test_filter_silver_pass_keeps_errored_guide(tmp_path, monkeypatch, capsys):
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir(); bad.mkdir()

    def fake_audit(gd):
        if gd.name == "bad":
            raise OSError("boom")
        return {"silver_pass": True}

    monkeypatch.setattr(audit_silver, "audit_guide", fake_audit)
    passing, errored = audit_gold.filter_silver_pass([good, bad])
    assert passing == [good]
    assert [(p.name, type(e).__name__) for p, e in errored] == [("bad", "OSError")]
    assert "[audit-error] audit_gold.filter_silver_pass" in capsys.readouterr().err
