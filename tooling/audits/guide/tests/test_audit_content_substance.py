"""Tests for the cloned-margin / absent-retrieval content-substance detector."""
from __future__ import annotations

from tooling.audits.guide.audit_content_substance import measure


def _make_guide(tmp_path, chapters: dict[str, str]):
    ch = tmp_path / "guide" / "chapters"
    ch.mkdir(parents=True)
    for name, body in chapters.items():
        (ch / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_hand_authored_margins_are_not_flagged(tmp_path):
    # Distinct per-chapter margins plus real retrieval practice: clean on both signals.
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": (
            r"\formulamargin{UCB bonus at $t=100$, $N_t=4$: $2\sqrt{\ln 100/4}\approx 2.15$}"
            "\n" r"\begin{problem}[Bandits][X-1.1]" "\n" r"\end{problem}" "\n"
        ),
        "02_m2_b.tex": (
            r"\formulamargin{Beta posterior after 3 wins, 1 loss: $\mathrm{Beta}(4,2)$}" "\n"
            r"\begin{vignette}[Rollout][X-2.1]" "\n" r"\end{vignette}" "\n"
        ),
    })
    s = measure(gd)
    assert s.margins == 2
    assert s.duplicated == 0
    assert s.dup_rate == 0.0
    assert (s.problems, s.vignettes) == (1, 1)
    assert not s.margins_flagged
    assert not s.retrieval_flagged
    assert not s.flagged


def test_margin_pasted_into_every_chapter_is_flagged(tmp_path):
    # The real fleet defect: one payload repeated verbatim across chapters it does
    # not belong to. Retrieval practice is present, so ONLY the margin signal fires.
    cloned = r"\formulamargin{Bloom FP rate: $(1-e^{-kn/m})^k$}"
    body = "\n".join([cloned, r"\begin{problem}[P][X-1.1]", r"\end{problem}"])
    gd = _make_guide(tmp_path, {
        "01_m1_hashing.tex": body,
        "02_m2_external_sorting.tex": body,
        "03_m3_quantiles.tex": body,
    })
    s = measure(gd)
    assert s.margins == 3
    assert s.duplicated == 3
    assert s.dup_rate == 1.0
    assert s.margins_flagged
    assert not s.retrieval_flagged      # 3 problems present
    assert s.flagged
    assert s.clones[0].count == 3
    assert len(s.clones[0].files) == 3


def test_shell_chapters_flag_absent_retrieval(tmp_path):
    # Distinct margins (so the clone signal stays quiet) but no problems and no
    # vignettes anywhere -- the 15-guide shell cohort.
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": r"\patternmargin{Message passing aggregates neighbour states}",
        "02_m2_b.tex": r"\patternmargin{Attention weights edges by learned scores}",
    })
    s = measure(gd)
    assert s.duplicated == 0
    assert not s.margins_flagged
    assert (s.problems, s.vignettes) == (0, 0)
    assert s.retrieval_flagged
    assert s.flagged


def test_whitespace_variants_count_as_the_same_clone(tmp_path):
    # Re-wrapped copies of one note are still one note; normalisation must catch it
    # or a reflow would silently defeat the detector.
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": r"\warningmargin{Graph data quality determines GNN performance}",
        "02_m2_b.tex": "\\warningmargin{Graph data  quality   determines GNN performance}",
    })
    s = measure(gd)
    assert s.duplicated == 2
    assert s.margins_flagged


def test_guide_with_no_margins_is_not_divided_by_zero(tmp_path):
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": "\\begin{problem}[P][X-1.1]\n\\end{problem}\n",
    })
    s = measure(gd)
    assert s.margins == 0
    assert s.dup_rate == 0.0
    assert not s.margins_flagged
    assert not s.retrieval_flagged


# ── gt#33 row 9: brace-balanced margin scanner ───────────────────────────────

def test_wrapped_margin_counted_and_normalized(tmp_path):
    # The same note, wrapped differently in two chapters: the old end-of-line-anchored
    # regex saw NEITHER (fleet-wide 1823 of 8215 margins were invisible); both must
    # count, and whitespace normalisation must make them ONE clone.
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": (
            "\\interviewmargin{``What types of tools does an agent need?'' ---\n"
            "information, action, and domain-specialized.}\n"
        ),
        "02_m2_b.tex": (
            "\\interviewmargin{``What types of tools does an agent need?''\n"
            "--- information, action,\n"
            "and domain-specialized.}\n"
        ),
    })
    s = measure(gd)
    assert s.margins == 2
    assert s.duplicated == 2
    assert s.clones[0].count == 2


def test_nested_brace_margin_not_truncated(tmp_path):
    # A payload with a nested group must be captured whole: two notes that differ
    # only AFTER the nested \textbf{} are distinct, not clones of a truncated prefix.
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": r"\patternmargin{Tool taxonomy: \textbf{information} (temporal gap).}",
        "02_m2_b.tex": r"\patternmargin{Tool taxonomy: \textbf{information} (functional gap).}",
    })
    s = measure(gd)
    assert s.margins == 2
    assert s.duplicated == 0
    assert s.clones == []


def test_two_margins_one_line_both_counted(tmp_path):
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": r"\formulamargin{$a^2$} text \warningmargin{b} more",
    })
    s = measure(gd)
    assert s.margins == 2


def test_commented_out_margin_not_counted(tmp_path):
    gd = _make_guide(tmp_path, {
        "01_m1_a.tex": "% \\warningmargin{draft note, commented out}\n\\warningmargin{live note}\n",
    })
    s = measure(gd)
    assert s.margins == 1
