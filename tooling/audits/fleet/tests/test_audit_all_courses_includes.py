"""Bronze check 10 -- stub-free includes (gt#33 row 3).

The gold-wave review of 2026-08-27 found 87 ``TODO``-body appendix files rendered
into delivered PDFs of 44 guides while every tier gate stayed green. This check
reads ``guide/main.tex`` and RED-flags any included file whose body is missing,
unreadable, empty, or a placeholder.
"""
from __future__ import annotations

from tooling.audits.fleet.audit_all_courses import (
    BRONZE_CHECKS,
    BRONZE_TOTAL,
    check_main_includes,
    classify_include_body,
)

TODO_BODY = "\\chapter{Quick Reference}\n\\label{app:quick-reference}\nTODO: Add quick reference tables.\n"
REAL_BODY = "\\chapter{Intro}\n\\label{ch:intro}\nReal prose about the topic.\n"


def _guide(tmp_path, main_tex: str, files: dict[str, str]):
    g = tmp_path / "guide"
    g.mkdir()
    (g / "main.tex").write_text(main_tex, encoding="utf-8")
    for rel, body in files.items():
        p = g / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


# ── classify_include_body ────────────────────────────────────────────────────

def test_classify_todo_body_is_stub():
    assert classify_include_body(TODO_BODY) == "stub"


def test_classify_tbd_fixme_placeholder_case_insensitive():
    for word in ("tbd", "FIXME:", "Placeholder --"):
        assert classify_include_body(f"\\chapter{{X}}\n{word} later\n") == "stub", word


def test_classify_structure_only_is_empty():
    assert classify_include_body("\\chapter{X}\n\\label{ch:x}\n\\section{Y}\n\n") == "empty"


def test_classify_comment_only_body_is_empty():
    assert classify_include_body("\\chapter{X}\n% TODO: write me\n% nothing yet\n") == "empty"


def test_classify_los_block_counts_as_content():
    # rag_seminal_papers-style chapters: no prose, but a learningoutcomes block.
    body = "\\chapter{X}\n\\begin{learningoutcomes}\n\\los{R-1.1}{Explain}{x}\n\\end{learningoutcomes}\n"
    assert classify_include_body(body) is None


def test_classify_real_prose_is_content():
    assert classify_include_body(REAL_BODY) is None
    # A TODO that is NOT the first content line is a note inside prose, not a stub.
    assert classify_include_body("\\chapter{X}\nReal prose.\nTODO tighten this.\n") is None


# ── check_main_includes ──────────────────────────────────────────────────────

def test_clean_includes_green(tmp_path):
    gd = _guide(tmp_path, "\\input{chapters/01_intro}\n\\input{appendices/C_glossary.tex}\n",
                {"chapters/01_intro.tex": REAL_BODY, "appendices/C_glossary.tex": REAL_BODY})
    status, detail = check_main_includes(gd)
    assert status == "GREEN"
    assert detail == "2 includes resolved, stub-free"


def test_todo_body_red(tmp_path):
    gd = _guide(tmp_path, "\\input{chapters/01_intro}\n\\input{appendices/A_quick_reference}\n",
                {"chapters/01_intro.tex": REAL_BODY, "appendices/A_quick_reference.tex": TODO_BODY})
    status, detail = check_main_includes(gd)
    assert status == "RED"
    assert detail == "1 include(s): TODO body: appendices/A_quick_reference.tex"


def test_empty_body_red(tmp_path):
    gd = _guide(tmp_path, "\\input{chapters/01_intro}\n",
                {"chapters/01_intro.tex": "\\chapter{Intro}\n\\label{ch:intro}\n"})
    status, detail = check_main_includes(gd)
    assert status == "RED"
    assert "empty: chapters/01_intro.tex" in detail


def test_missing_target_red(tmp_path):
    gd = _guide(tmp_path, "\\input{chapters/99_ghost}\n", {})
    status, detail = check_main_includes(gd)
    assert status == "RED"
    assert "missing: chapters/99_ghost.tex" in detail


def test_commented_input_ignored(tmp_path):
    # The gm#93 un-input form: the TODO file stays on disk but is not included.
    main = "\\input{chapters/01_intro}\n% \\input{appendices/A_quick_reference}  % gm#93: un-input until authored\n"
    gd = _guide(tmp_path, main, {"chapters/01_intro.tex": REAL_BODY,
                                 "appendices/A_quick_reference.tex": TODO_BODY})
    status, detail = check_main_includes(gd)
    assert status == "GREEN"
    assert detail.startswith("1 includes")


def test_include_form_and_explicit_tex_extension(tmp_path):
    gd = _guide(tmp_path, "\\include{chapters/01_intro.tex}\n\\input {chapters/02_next}\n",
                {"chapters/01_intro.tex": REAL_BODY, "chapters/02_next.tex": REAL_BODY})
    assert check_main_includes(gd) == ("GREEN", "2 includes resolved, stub-free")


def test_more_than_three_problems_are_summarised(tmp_path):
    main = "".join(f"\\input{{chapters/{i:02d}_x}}\n" for i in range(5))
    gd = _guide(tmp_path, main, {f"chapters/{i:02d}_x.tex": TODO_BODY for i in range(5)})
    status, detail = check_main_includes(gd)
    assert status == "RED"
    assert detail.startswith("5 include(s): ")
    assert detail.endswith("(+2 more)")


def test_main_missing_red(tmp_path):
    (tmp_path / "guide").mkdir()
    assert check_main_includes(tmp_path) == ("RED", "guide/main.tex missing")


def test_bronze_total_is_ten_and_check_is_registered():
    # Do NOT call audit_course here: it invokes the Silver auditor on the fixture.
    assert BRONZE_TOTAL == 10
    assert [name for name, _fn in BRONZE_CHECKS][-1] == "Stub-free includes"
    assert len({name for name, _fn in BRONZE_CHECKS}) == BRONZE_TOTAL
