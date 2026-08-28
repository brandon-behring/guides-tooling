"""G7 per-item E / per-Position F citation checks (gt#33 row 7).

The 2026-08-27 gold-wave review found that no gate read Appendix E citations at
all (10 files with zero ``\\cite``) and that F's file-wide floor let 111 of 820
Position blocks ship uncited. Owner-ruled blocking on landing (2026-08-28);
``G7_CITES_STRICT = False`` turns the same counts into advisory notes.
"""
from __future__ import annotations

from datetime import datetime

from tooling.audits.fleet import audit_gold
from tooling.audits.fleet.audit_gold import (
    _e_item_spans,
    _f_position_spans,
    check_gate7_currency,
)

NOW = datetime(2026, 8, 15)

E_HEAD = "\\chapter{Post-Course Updates}\nCurrent as of 2026-07.\n\\section{Library and API Changes}\n"
E_ITEM_CITED = (
    "\\subsection*{[Official] NAME moved}\nProse about NAME.\n"
    "\\begin{sloppypar}\\footnotesize Sources: \\url{https://example.com/NAME}\\end{sloppypar}\n"
)
E_ITEM_UNCITED = "\\subsection*{[Official] NAME moved}\nProse about NAME with no source.\n"
E_TAIL = "\\section{What Still Holds}\n\\subsection*{Core ideas}\nStable material, no citation needed.\n"

F_DEBATE = (
    "\\section{Debate NUM}\n"
    "\\textbf{Position A (NUM): one side.} Argument \\parencite{aNUM}.\n\n"
    "\\textbf{Position B (NUM): other side.} Argument BCITE.\n\n"
    "\\textbf{Where the book sits.} Somewhere WCITE. \\emph{Verdict: contested.}\n\n"
)


def _item(template: str, name: str) -> str:
    return template.replace("NAME", name)


def _e(items: list[str]) -> str:
    return E_HEAD + "".join(items) + E_TAIL


def _f(n_debates: int = 3, uncited_b: set[int] = frozenset(), cite_in_verdict: bool = False) -> str:
    out = []
    for n in range(1, n_debates + 1):
        out.append(
            F_DEBATE.replace("NUM", str(n))
            .replace("BCITE", "" if n in uncited_b else f"\\parencite{{b{n}}}")
            .replace("WCITE", f"\\parencite{{w{n}}}" if cite_in_verdict else "")
        )
    return "".join(out)


def _guide(tmp_path, e_text: str, f_text: str):
    app = tmp_path / "guide" / "appendices"
    app.mkdir(parents=True)
    (app / audit_gold.E_FILENAME).write_text(e_text, encoding="utf-8")
    (app / audit_gold.F_FILENAME).write_text(f_text, encoding="utf-8")
    return tmp_path


CLEAN_E = _e([_item(E_ITEM_CITED, n) for n in ("foo", "bar", "baz")])
CLEAN_F = _f()


# ── span definitions ─────────────────────────────────────────────────────────

def test_e_item_spans_stop_at_what_still_holds():
    spans = _e_item_spans(CLEAN_E)
    assert len(spans) == 3
    assert all("Sources:" in s for s in spans)
    assert not any("Core ideas" in s for s in spans)


def test_e_item_spans_fall_back_to_items():
    text = E_HEAD + "\\begin{itemize}\n\\item one \\url{https://x}\n\\item two\n\\end{itemize}\n" + E_TAIL
    spans = _e_item_spans(text)
    assert len(spans) == 2
    assert "two" in spans[1] and "Core ideas" not in spans[1]


def test_f_position_spans_end_at_where_book_sits():
    spans = _f_position_spans(_f(n_debates=1, uncited_b={1}, cite_in_verdict=True))
    assert len(spans) == 2
    assert "Position A" in spans[0] and "parencite{a1}" in spans[0]
    assert "Position B" in spans[1]
    assert "Where the book sits" not in spans[1] and "w1" not in spans[1]


# ── gate behaviour (G7_CITES_STRICT = True by default) ───────────────────────

def test_clean_detail_shape_unchanged(tmp_path):
    g = check_gate7_currency(_guide(tmp_path, CLEAN_E, CLEAN_F), {}, NOW)
    assert g.passed
    assert g.detail == "E ok; F ok"


def test_e_uncited_item_fails_when_strict(tmp_path):
    e = _e([_item(E_ITEM_CITED, "foo"), _item(E_ITEM_UNCITED, "bar"),
            _item(E_ITEM_CITED, "baz")])
    g = check_gate7_currency(_guide(tmp_path, e, CLEAN_F), {}, NOW)
    assert not g.passed
    assert g.detail == "E: 1/3 items uncited | F: ok"


def test_e_uncited_item_is_advisory_when_switch_off(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_gold, "G7_CITES_STRICT", False)
    e = _e([_item(E_ITEM_CITED, "foo"), _item(E_ITEM_UNCITED, "bar"),
            _item(E_ITEM_CITED, "baz")])
    g = check_gate7_currency(_guide(tmp_path, e, CLEAN_F), {}, NOW)
    assert g.passed
    assert g.detail == "E: ok (1/3 items uncited, advisory) | F: ok"


def test_e_items_after_what_still_holds_not_counted(tmp_path):
    # The uncited "Core ideas" subsection lives under What Still Holds: not an item.
    g = check_gate7_currency(_guide(tmp_path, CLEAN_E, CLEAN_F), {}, NOW)
    assert g.passed


def test_e_commented_out_citation_does_not_count(tmp_path):
    e = _e([_item(E_ITEM_CITED, "foo"),
            "\\subsection*{[Official] bar moved}\nProse.\n% \\url{https://example.com/bar}\n",
            _item(E_ITEM_CITED, "baz")])
    g = check_gate7_currency(_guide(tmp_path, e, CLEAN_F), {}, NOW)
    assert not g.passed
    assert "1/3 items uncited" in g.detail


def test_f_uncited_position_fails_even_when_file_floor_is_met(tmp_path):
    # 3 debates, 6 cites total (floor met) but debate 2's Position B is uncited and the
    # verdict paragraph's citation must not credit it.
    f = _f(n_debates=3, uncited_b={2}, cite_in_verdict=True)
    g = check_gate7_currency(_guide(tmp_path, CLEAN_E, f), {}, NOW)
    assert not g.passed
    assert g.detail == "E: ok | F: 1/6 Positions uncited"


def test_f_uncited_position_advisory_when_switch_off(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_gold, "G7_CITES_STRICT", False)
    f = _f(n_debates=3, uncited_b={2}, cite_in_verdict=True)
    g = check_gate7_currency(_guide(tmp_path, CLEAN_E, f), {}, NOW)
    assert g.passed
    assert g.detail == "E: ok | F: ok (1/6 Positions uncited, advisory)"


def test_f_waiver_skips_position_rule(tmp_path):
    qa = {"gold_exceptions": {"debates_waiver": "true",
                              "debates_waiver_justification": "no live debates in this field"}}
    f = _f(n_debates=3, uncited_b={1, 2, 3})
    g = check_gate7_currency(_guide(tmp_path, CLEAN_E, f), qa, NOW)
    assert g.passed
    assert g.detail == "E ok; F waived"


def test_both_appendices_report_together(tmp_path):
    e = _e([_item(E_ITEM_UNCITED, n) for n in ("foo", "bar", "baz")])
    # verdict citations keep the file-wide floor satisfied (8 >= 6) so only the
    # per-Position rule fires on the F side
    f = _f(n_debates=3, uncited_b={1}, cite_in_verdict=True)
    g = check_gate7_currency(_guide(tmp_path, e, f), {}, NOW)
    assert not g.passed
    assert g.detail == "E: 3/3 items uncited | F: 1/6 Positions uncited"
