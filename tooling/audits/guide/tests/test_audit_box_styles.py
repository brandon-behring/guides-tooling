"""Tests for the undefined-tcolorbox-style detector."""
from __future__ import annotations

import tooling.audits.guide.audit_box_styles as m


def _mk(tmp_path, chapter: str, sty: str = ""):
    g = tmp_path / "guide"
    (g / "chapters").mkdir(parents=True)
    (g / "chapters" / "01_m1.tex").write_text(chapter, encoding="utf-8")
    (g / "notebook-extensions.sty").write_text(sty, encoding="utf-8")
    return tmp_path


def test_styles_in_parses_both_def_forms():
    assert m._styles_in(r"\tcbset{narrativebox/.style={colback=white}}") == {"narrativebox"}
    assert m._styles_in(r"\newtcolorbox{warnbox}{...}") == {"warnbox"}


def test_used_styles_extracts_bare_tokens_only(tmp_path):
    gd = _mk(tmp_path, r"\begin{tcolorbox}[breakable, checkpointbox, title=Hi]x\end{tcolorbox}")
    assert m._used_styles(gd) == {"breakable", "checkpointbox"}   # title=Hi (key=value) ignored


def test_undefined_used_style_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "_shared_styles", lambda: frozenset())
    monkeypatch.setattr(m, "_universe", lambda: frozenset({"narrativebox", "checkpointbox"}))
    gd = _mk(tmp_path,
             r"\begin{tcolorbox}[narrativebox, title=X]y\end{tcolorbox}",
             sty=r"\tcbset{checkpointbox/.style={}}")        # defines checkpointbox, NOT narrativebox
    assert m.find_undefined_box_styles(gd) == ["narrativebox"]


def test_defined_style_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "_shared_styles", lambda: frozenset())
    monkeypatch.setattr(m, "_universe", lambda: frozenset({"narrativebox"}))
    gd = _mk(tmp_path, r"\begin{tcolorbox}[narrativebox]z\end{tcolorbox}",
             sty=r"\tcbset{narrativebox/.style={}}")
    assert m.find_undefined_box_styles(gd) == []


def test_builtin_bare_key_ignored(tmp_path, monkeypatch):
    # 'breakable' is a tcolorbox built-in (not in the custom-style universe) → never flagged,
    # even when it leads the option list before the real custom style.
    monkeypatch.setattr(m, "_shared_styles", lambda: frozenset())
    monkeypatch.setattr(m, "_universe", lambda: frozenset({"narrativebox"}))
    gd = _mk(tmp_path, r"\begin{tcolorbox}[breakable, narrativebox]q\end{tcolorbox}",
             sty=r"\tcbset{narrativebox/.style={}}")
    assert m.find_undefined_box_styles(gd) == []
