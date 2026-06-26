"""Tests for the checkpoint template-tailing (recall-floor padding) detector."""
from __future__ import annotations

from tooling.audits.guide.audit_checkpoint_originality import find_template_tails


def _make_guide(tmp_path, chapter_body: str):
    ch = tmp_path / "guide" / "chapters"
    ch.mkdir(parents=True)
    (ch / "01_m1_intro.tex").write_text(chapter_body, encoding="utf-8")
    return tmp_path


def _flagged(gd):
    total, items = find_template_tails(gd)
    return total, sorted(t.los_id for t in items), {t.los_id: t.reason for t in items}


def test_known_tail_singleton_is_flagged(tmp_path):
    # A single appended known cross-guide tail is flagged even though it does not
    # cluster -- signal B catches singletons signal A (>=3) would miss. Also guards
    # macro stripping: \texttt{...} content must not break the suffix match.
    body = r"""
\begin{itemize}
  \item[X-1.1] Apply collective ops (\texttt{lax.psum}) to a concrete problem you construct. Show the first step, the signal that it worked, and one thing that can go wrong.
  \item[X-1.2] Describe how containers isolate processes using namespaces and cgroups in practice.
\end{itemize}
"""
    total, ids, reasons = _flagged(_make_guide(tmp_path, body))
    assert total == 2
    assert ids == ["X-1.1"]                 # the genuine X-1.2 is NOT flagged
    assert reasons["X-1.1"] == "known-tail"


def test_shared_suffix_cluster_is_flagged(tmp_path):
    # Three items in ONE guide sharing the trailing 10 words = a guide-local template
    # the cross-guide set does not know about. Signal A must catch it; the fourth,
    # distinct, item must not be flagged.
    body = r"""
\begin{itemize}
  \item[Y-1.1] Apply series indexing and explain the chapter-specific gotcha you should expect here.
  \item[Y-2.1] Apply dataframe joins and explain the chapter-specific gotcha you should expect here.
  \item[Y-3.1] Apply groupby aggregation and explain the chapter-specific gotcha you should expect here.
  \item[Y-4.1] Describe this chapter's single unique idea in your own words without any reuse.
\end{itemize}
"""
    total, ids, reasons = _flagged(_make_guide(tmp_path, body))
    assert total == 4
    assert ids == ["Y-1.1", "Y-2.1", "Y-3.1"]
    assert reasons["Y-1.1"] == "shared-suffix(x3)"


def test_two_sharing_is_below_threshold(tmp_path):
    # Only two items share the suffix (< MIN_CLUSTER) and it is not a known
    # cross-guide tail -> nothing flagged. Guards against over-aggressive clustering.
    body = r"""
\begin{itemize}
  \item[Z-1.1] Apply alpha and explain the chapter-specific gotcha you should expect here.
  \item[Z-2.1] Apply beta and explain the chapter-specific gotcha you should expect here.
  \item[Z-3.1] Describe something entirely specific to this chapter in your own distinct words.
\end{itemize}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 3
    assert ids == []


def test_clean_guide_has_no_flags(tmp_path):
    # Distinct, chapter-specific prompts: no shared 10-word suffix, no known tail.
    body = r"""
\begin{itemize}
  \item[C-1.1] Explain why JAX requires pure functions and what retracing costs you.
  \item[C-1.2] Apply vmap to batch a dot product and name the axis it maps over.
  \item[C-1.3] Compare pmap and shard_map for data-parallel training on eight devices.
\end{itemize}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 3
    assert ids == []


def test_hyphenation_insensitive_known_tail(tmp_path):
    # The source writes "trade-off"; the cross-guide suffix stores "trade off".
    # Normalization must drop the hyphen so the known tail still matches.
    body = r"""
\begin{itemize}
  \item[W-1.1] Compare A and B. Name one metric that separates them, one scenario that flips the trade-off, and the mechanism behind the flip.
  \item[W-1.2] Implement a reproducible pipeline that this chapter alone uniquely motivates and explains.
\end{itemize}
"""
    total, ids, reasons = _flagged(_make_guide(tmp_path, body))
    assert total == 2
    assert ids == ["W-1.1"]
    assert reasons["W-1.1"] == "known-tail"


def test_answer_key_items_excluded_structurally(tmp_path):
    # D1: a checkpointbox repeats \item[LOS] in a paired "Answers:" enumerate.
    # Answer-key items (after the Answers marker) must be excluded structurally so
    # the box is not double-counted.
    body = r"""
\begin{tcolorbox}[checkpointbox]
\begin{enumerate}
  \item[X-1.1] Explain the unique chapter idea in your own words without any reuse here.
  \item[X-1.2] Apply the chapter technique to a fresh dataset and report one failure mode.
\end{enumerate}
\textbf{Answers:}
\begin{enumerate}
  \item[X-1.1] The unique chapter idea is X because Y.
  \item[X-1.2] You would apply it by doing Z.
\end{enumerate}
\end{tcolorbox}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 2          # X-1.1 + X-1.2, NOT 4 (the 2 answer keys are excluded)
    assert ids == []           # genuine prompts, none templated


def test_reused_los_distinct_prompts_both_kept(tmp_path):
    # D1 fix (the bug the prior LOS-dedup introduced): a question list may legitimately
    # reuse a LOS-ID for two DISTINCT prompts (real case: grokking_ml_2e GML-7.4).
    # Structural exclusion must keep BOTH question prompts (LOS-dedup dropped the 2nd)
    # while still excluding the 3 answer keys.
    body = r"""
\begin{tcolorbox}[checkpointbox, title=Module 7 Checkpoint]
\begin{enumerate}
  \item[M-7.1] A first distinct question about precision and recall on imbalanced data.
  \item[M-7.4] Why is the harmonic mean used for F1 instead of the arithmetic mean here?
  \item[M-7.4] A spam filter with high precision but low recall: what does that mean exactly?
\end{enumerate}
\textbf{Answers:}
\begin{enumerate}
  \item[M-7.1] Because accuracy hides the minority class entirely.
  \item[M-7.4] The harmonic mean punishes imbalance between P and R.
  \item[M-7.4] It catches little spam but rarely misflags legitimate ham.
\end{enumerate}
\end{tcolorbox}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 3          # both M-7.4 prompts kept; the 3 answer keys excluded
    assert ids == []


def test_trailing_los_echo_is_stripped(tmp_path):
    # D2: a trailing \hfill\textit{(LOS)} echo must not defeat the suffix match.
    body = r"""
\begin{itemize}
  \item[X-1.1] Describe how the system traces graphs for autodiff. Give one operational example and name one signal that confirms the description applies in practice.\hfill\textit{(X-1.1)}
  \item[X-1.2] A distinct prompt unique to this chapter that shares no tail with the others.
\end{itemize}
"""
    total, ids, reasons = _flagged(_make_guide(tmp_path, body))
    assert total == 2
    assert ids == ["X-1.1"]
    assert "known-tail" in reasons["X-1.1"].split(",")


def test_combined_reasons_when_both_signals_fire(tmp_path):
    # F1: an item that is BOTH a known cross-guide tail AND in a >=3 cluster must
    # report both reasons (the old setdefault dropped one).
    tail = "Show the first step, the signal that it worked, and one thing that can go wrong."
    body = (
        "\n\\begin{itemize}\n"
        f"  \\item[X-1.1] Apply A to a problem. {tail}\n"
        f"  \\item[X-2.1] Apply B to a problem. {tail}\n"
        f"  \\item[X-3.1] Apply C to a problem. {tail}\n"
        "\\end{itemize}\n"
    )
    total, _ids, reasons = _flagged(_make_guide(tmp_path, body))
    assert total == 3
    for los in ("X-1.1", "X-2.1", "X-3.1"):
        parts = set(reasons[los].split(","))
        assert "known-tail" in parts
        assert "shared-suffix(x3)" in parts


def test_los_only_in_answer_enumerate_is_kept(tmp_path):
    # Real case (ai_agents_and_apps): plain-text questions, then Answers:, then
    # \item[LOS] items appended INSIDE the answer enumerate. Those LOS items have no
    # question-region duplicate, so they are genuine prompts and must be KEPT -- a
    # blunt "exclude everything after Answers" rule wrongly dropped them to zero.
    body = r"""
\begin{tcolorbox}[checkpointbox, title=Module 2 Checkpoint]
\begin{enumerate}
  \item What are the three elements of a well-structured prompt? Give an example.
  \item Explain zero-shot vs few-shot prompting and when each is appropriate here.
\end{enumerate}
\textbf{Answers:}
\begin{enumerate}
  \item Instruction, context, and format specification, with a worked example.
  \item Zero-shot uses no examples; few-shot supplies two to eight exemplars.
  \item[AAA-2.6] Design a FewShotPromptTemplate and name the three components you must supply.
  \item[AAA-2.8] Debug prompt-engineering failures by isolating one variable at a time.
\end{enumerate}
\end{tcolorbox}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 2          # AAA-2.6 + AAA-2.8 kept (no question-region duplicate)
    assert ids == []


def test_nested_tcolorbox_does_not_break_answer_key_exclusion(tmp_path):
    # A nested \begin{tcolorbox}..\end{tcolorbox} before the Answers marker must not
    # truncate the checkpoint box (a non-greedy box regex would stop at the nested
    # \end{tcolorbox}, letting the answer-key X-1.1 be counted as a 2nd prompt).
    body = r"""
\begin{tcolorbox}[checkpointbox]
\begin{enumerate}
  \item[X-1.1] A genuine prompt about the chapter's core idea explained in your words.
\end{enumerate}
\begin{tcolorbox}[debugbox]a nested aside\end{tcolorbox}
\textbf{Answers:}
\begin{enumerate}
  \item[X-1.1] The core idea is X because Y, shown by the worked example here.
\end{enumerate}
\end{tcolorbox}
"""
    total, ids, _ = _flagged(_make_guide(tmp_path, body))
    assert total == 1          # the answer-key X-1.1 excluded despite the nested box
    assert ids == []


def test_line_numbers_reported(tmp_path):
    body = r"""
\begin{itemize}
  \item[X-1.1] Apply a thing to a concrete problem you construct. Show the first step, the signal that it worked, and one thing that can go wrong.
\end{itemize}
"""
    _total, items = find_template_tails(_make_guide(tmp_path, body))
    assert items[0].line == 3          # 1-indexed line of the \item
