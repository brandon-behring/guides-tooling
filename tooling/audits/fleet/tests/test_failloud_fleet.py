"""Fail-loud behavior of the fleet audits (gt#23).

A malformed input must yield a visible RED / stderr ``[audit-error]`` line,
never a neutral value indistinguishable from a healthy scan.
"""

from tooling.audits.fleet import audit_all_courses, audit_silver


# ── audit_all_courses.check_bloom_levels ─────────────────────────────────────

def test_bloom_levels_malformed_yaml_is_red(tmp_path):
    (tmp_path / "guide_qa.yaml").write_text("los: [unclosed\n")
    status, detail = audit_all_courses.check_bloom_levels(tmp_path)
    assert status == "RED"
    assert "parse error" in detail


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
