r"""Tests for the LaTeX validators (check_refs, extract_los, check_latex_warnings).

Locks in the "PR #4 review" fixes (guides-tooling#4): a commented-out \label/\ref/\los is ignored,
an explicitly-named missing file errors, and wrapped undef-refs / overfull \vbox / per-source undef
columns are detected. Runs the real scripts as subprocesses against tiny fixtures (faithful to the
CLI behaviour the course-guide repos invoke).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

VALID = Path(__file__).resolve().parents[1]  # tooling/validation/
CHECK_REFS = VALID / "check_refs.py"
EXTRACT_LOS = VALID / "extract_los.py"
CHECK_LATEX = VALID / "check_latex_warnings.py"


def _run(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)


# --------------------------------------------------------------------- check_refs.py
def test_check_refs_commented_label_does_not_satisfy_ref(tmp_path):  # p11
    f = tmp_path / "a.tex"
    f.write_text(r"\ref{ch:method}" + "\n" + r"% \label{ch:method}" + "\n")
    r = _run(CHECK_REFS, f)
    assert r.returncode == 1, r.stdout  # a commented-out \label must NOT satisfy a live \ref
    assert "Undefined reference" in r.stdout


def test_check_refs_inline_commented_ref_not_flagged(tmp_path):  # p12
    f = tmp_path / "a.tex"
    f.write_text(r"\label{good}" + "\n" + r"\ref{good}  % \ref{bogus}" + "\n")
    r = _run(CHECK_REFS, f)
    assert r.returncode == 0, r.stdout + r.stderr  # inline-commented \ref{bogus} must be ignored
    assert "valid" in r.stdout.lower()


def test_check_refs_missing_explicit_file_errors(tmp_path):  # p14
    r = _run(CHECK_REFS, tmp_path / "does_not_exist.tex")
    assert r.returncode == 1
    assert "not found" in (r.stdout + r.stderr).lower()


# --------------------------------------------------------------------- extract_los.py
def test_extract_los_missing_explicit_file_errors(tmp_path):  # p13
    r = _run(EXTRACT_LOS, tmp_path / "nope.tex", "--validate")
    assert r.returncode == 1
    assert "not found" in (r.stdout + r.stderr).lower()


def test_extract_los_ignores_commented_los(tmp_path):  # p15
    f = tmp_path / "a.tex"
    f.write_text(r"\los{PY-1.1}{define}{Real one}" + "\n"
                 + r"% \los{PY-9.9}{bogus}{Commented out}" + "\n")
    r = _run(EXTRACT_LOS, f)
    assert r.returncode == 0, r.stderr
    assert "Total LOS: 1" in r.stdout  # the commented-out \los is not counted


# --------------------------------------------------------------------- check_latex_warnings.py
def test_latex_wrapped_undef_ref_detected(tmp_path):  # p16
    log = tmp_path / "b.log"
    label = "x" * 70  # forces the warning across LaTeX's ~79-col wrap
    log.write_text(f"LaTeX Warning: Reference `{label}' on page 5\nundefined on input line 42.\n")
    r = _run(CHECK_LATEX, log, "--json")
    assert r.returncode == 1, r.stdout  # a real (wrapped) undef ref must fail the gate
    assert json.loads(r.stdout)["undef_references"] >= 1


def test_latex_vbox_detected(tmp_path):  # p27
    log = tmp_path / "b.log"
    log.write_text("Overfull \\vbox (72.0pt too high) detected has occurred\n")
    r = _run(CHECK_LATEX, log, "--json")
    assert json.loads(r.stdout)["overfull_vbox"] >= 1


def test_latex_by_source_has_undef_columns(tmp_path):  # p18
    log = tmp_path / "b.log"
    log.write_text("(./sections/intro.tex\nLaTeX Warning: Reference `foo' undefined on input line 3.\n")
    r = _run(CHECK_LATEX, log, "--by-file")
    assert "undef_ref" in r.stdout  # the gated columns are present in the per-source table


def test_latex_section_source_attribution(tmp_path):  # p17
    log = tmp_path / "b.log"
    log.write_text("(./sections/intro.tex\nOverfull \\hbox (60.0pt too wide) in paragraph\n")
    r = _run(CHECK_LATEX, log, "--json", "--by-file")
    by_source = json.loads(r.stdout)["by_source"]
    assert any("sections/intro.tex" in s for s in by_source)  # attributed to sections/, not the log
