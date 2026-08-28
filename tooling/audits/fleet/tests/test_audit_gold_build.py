"""GB (opt-in --build gate): biber "skipping" warnings fail the build gate (gt#33 row 4).

Live evidence (2026-08-27 review, A6): two Gold guides' ``main_digital.blg`` carried
``> WARN - Duplicate entry key: '...' ... skipping ...`` -- biber dropped the entry --
while GB reported "biber clean" because it matched only ``> ERROR -`` / ``> FATAL -``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tooling.audits.fleet import audit_gold
from tooling.audits.fleet.audit_gold import _BIBER_ERR_RE, _BIBER_SKIP_RE, check_gate_build

# A bib entry key, not a credential: gitleaks' generic-api-key rule matches "key: '...'".
DUP_KEY_WARN = ("[622] Biber.pm:132> WARN - Duplicate entry key: 'verma2015borg' in file "  # gitleaks:allow
                "'references.bib', skipping ...")
NAME_COMMA_WARN = ("[210] Utils.pm:410> WARN - BibTeX subsystem: warning: comma(s) at end of "
                   "name (removing)")
INFO_SKIP = "[300] Biber.pm:200> INFO - Skipping unreferenced entry 'unused2020'"
HARD_ERROR = "[400] Biber.pm:99> ERROR - Too many commas in name, skipping entry 'x'"


# ── regex contract ───────────────────────────────────────────────────────────

def test_duplicate_key_warn_matches_with_message():
    m = _BIBER_SKIP_RE.search(DUP_KEY_WARN)
    assert m is not None
    assert m.group("msg").startswith("Duplicate entry key: 'verma2015borg'")  # gitleaks:allow


def test_name_comma_warn_is_benign():
    assert _BIBER_SKIP_RE.search(NAME_COMMA_WARN) is None


def test_info_skip_line_ignored():
    assert _BIBER_SKIP_RE.search(INFO_SKIP) is None
    assert _BIBER_ERR_RE.search(INFO_SKIP) is None


def test_error_line_still_matches_error_re():
    assert _BIBER_ERR_RE.search(HARD_ERROR) is not None


# ── gate behaviour with a stubbed build ──────────────────────────────────────
# check_gate_build unlinks stale .blg/.log before building, so the stub writes
# THIS build's logs during the fake `make`.

def _stub_make(monkeypatch, files: dict[str, str]):
    def run(cmd, **_kw):
        guide_sub = Path(cmd[2])
        for name, text in files.items():
            (guide_sub / name).write_text(text, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(audit_gold.subprocess, "run", run)


def _buildable_guide(tmp_path):
    g = tmp_path / "guide"
    g.mkdir()
    (g / "Makefile").write_text("digital:\n\ttrue\n")
    (g / "main.tex").write_text("\\documentclass{article}\n")
    return tmp_path


def test_gb_fails_on_biber_skip_warn(tmp_path, monkeypatch):
    _stub_make(monkeypatch, {"main_digital.log": "", "main_digital.blg": DUP_KEY_WARN + "\n"})
    g = check_gate_build(_buildable_guide(tmp_path))
    assert not g.passed
    assert "biber WARN skipped entry in .blg: Duplicate entry key: 'verma2015borg'" in g.detail  # gitleaks:allow


def test_gb_passes_with_benign_name_warn(tmp_path, monkeypatch):
    _stub_make(monkeypatch, {"main_digital.log": "", "main_digital.blg": NAME_COMMA_WARN + "\n"})
    g = check_gate_build(_buildable_guide(tmp_path))
    assert g.passed
    assert g.detail == "rc=0; 0 LaTeX errors; cites + biber clean"


def test_gb_fails_on_biber_hard_error(tmp_path, monkeypatch):
    _stub_make(monkeypatch, {"main_digital.log": "", "main_digital.blg": HARD_ERROR + "\n"})
    g = check_gate_build(_buildable_guide(tmp_path))
    assert not g.passed
    assert "biber ERROR in .blg" in g.detail
