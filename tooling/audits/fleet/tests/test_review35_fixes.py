"""Regressions for the tool-confirmed findings of the PR #35 three-voice review.

Each test pins one case that was demonstrated against the branch before the fix:
the include scanner, the stub classifier, the biber/Position regexes, the registry
guard's ordering, and the discovery allowlist's per-slug topic check.
"""
from __future__ import annotations

import pytest

from tooling import discovery
from tooling.audits.fleet import audit_all_courses
from tooling.audits.fleet.audit_all_courses import (
    check_main_includes,
    classify_include_body,
)
from tooling.audits.fleet.audit_gold import _BIBER_SKIP_RE, F_POSITION_RE
from tooling.audits.guide import _guide_scope

REAL = "\\chapter{Intro}\n\\label{ch:intro}\nReal prose about the topic.\n"


def _guide(tmp_path, main_tex: str, files: dict[str, str]):
    g = tmp_path / "guide"
    g.mkdir()
    (g / "main.tex").write_text(main_tex, encoding="utf-8")
    for rel, body in files.items():
        p = g / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


# ── include scanner ──────────────────────────────────────────────────────────

def test_unbraced_input_is_scanned(tmp_path):
    # TeX accepts `\input path`; those targets used to be invisible to the check.
    gd = _guide(tmp_path, "\\input chapters/01_intro.tex\n", {"chapters/01_intro.tex": REAL})
    assert check_main_includes(gd) == ("GREEN", "1 includes resolved, stub-free")


def test_unbraced_input_stub_is_caught(tmp_path):
    gd = _guide(tmp_path, "\\input chapters/01_intro\n",
                {"chapters/01_intro.tex": "\\chapter{X}\nTODO: write me\n"})
    status, detail = check_main_includes(gd)
    assert status == "RED" and "TODO body" in detail


def test_only_extensionless_targets_get_tex_appended(tmp_path):
    # `preamble.ltx` must resolve as itself, not as `preamble.ltx.tex`.
    gd = _guide(tmp_path, "\\input{preamble.ltx}\n\\input{chapters/01_intro}\n",
                {"preamble.ltx": REAL, "chapters/01_intro.tex": REAL})
    assert check_main_includes(gd)[0] == "GREEN"


def test_zero_includes_is_yellow_not_green(tmp_path):
    # A vacuous pass hid a lost include list.
    gd = _guide(tmp_path, "\\documentclass{book}\n\\begin{document}\\end{document}\n", {})
    status, detail = check_main_includes(gd)
    assert status == "YELLOW" and "no" in detail


# ── stub classifier ──────────────────────────────────────────────────────────

def test_markup_wrapped_todo_is_a_stub():
    assert classify_include_body("\\chapter{X}\n\\textbf{TODO: write this}\n") == "stub"
    assert classify_include_body("\\chapter{X}\n\\item TODO fill in\n") == "stub"


def test_prose_sharing_a_line_with_a_heading_is_content():
    # The whole line used to be discarded, so such a body read as "empty" (false RED).
    assert classify_include_body("\\chapter{X}\n\\section{Overview} Real explanatory prose.\n") is None


def test_heading_only_body_is_still_empty():
    assert classify_include_body("\\chapter{X}\n\\label{ch:x}\n\\section{Y}\n") == "empty"


# ── audit_gold regexes ───────────────────────────────────────────────────────

def test_biber_skip_matches_capitalized_skipping():
    assert _BIBER_SKIP_RE.search("[1] Biber.pm:132> WARN - Skipping entry 'y' (missing field)")


def test_biber_info_skip_still_ignored():
    assert _BIBER_SKIP_RE.search("[1] Biber.pm:200> INFO - Skipping unreferenced entry 'z'") is None


def test_position_marker_is_case_insensitive():
    assert F_POSITION_RE.search("\\textbf{position a (x): y}")


# ── registry guard + discovery allowlist ─────────────────────────────────────

def test_registry_guard_reports_a_vanished_fleet(tmp_path, monkeypatch, capsys):
    # The guard used to sit AFTER the empty-fleet return, so a disk with zero
    # discoverable guides exited 0 under --strict.
    monkeypatch.setenv("GUIDES_HOST_ROOT", str(tmp_path))
    (tmp_path / "guides.yml").write_text("guides:\n  - slug: g1\n    topic: t\n")
    monkeypatch.setattr(audit_all_courses, "discover_courses", lambda: [])
    monkeypatch.setattr("sys.argv", ["audit_all_courses", "--strict"])
    with pytest.raises(SystemExit) as e:
        audit_all_courses.main()
    assert e.value.code == 1
    assert "REGISTRY" in capsys.readouterr().err


def test_registered_slug_under_the_wrong_topic_is_not_discovered(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIDES_HOST_ROOT", str(tmp_path))
    _guide_scope._slug_index.cache_clear()
    (tmp_path / "guides.yml").write_text(
        "guides:\n  - slug: g1\n    topic: topic-a\n  - slug: g2\n    topic: topic-b\n")
    for rel in ("topic-b/g1", "topic-b/g2"):   # g1 is registered to topic-a
        p = tmp_path / rel / "guide_qa.yaml"
        p.parent.mkdir(parents=True)
        p.write_text("guide: {}\n")
    found = [d.relative_to(tmp_path).as_posix() for d in discovery.iter_guide_dirs()]
    assert found == ["topic-b/g2"]
    _guide_scope._slug_index.cache_clear()
