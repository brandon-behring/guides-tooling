"""Tests for the checkpoint Bloom-verb leak detector."""
from __future__ import annotations

from tooling.audits.guide.audit_checkpoint_bloom_verbs import find_bloom_leaks


def _make_guide(tmp_path, chapter_body: str):
    ch = tmp_path / "guide" / "chapters"
    ch.mkdir(parents=True)
    (ch / "01_m1_intro.tex").write_text(chapter_body, encoding="utf-8")
    return tmp_path


CHECKPOINT = r"""
\section{Intro}
\begin{itemize}
  \item[GAA-1.1] explain Explain how graphs represent problem spaces clearly.
  \item[GAA-1.2] Identify Identify problems suited to search in a worked example.
  \item[GAA-1.3] Apply the Strategy pattern to swap algorithms at runtime here.
  \item[GAA-1.4] Compare breadth-first and depth-first search on completeness.
\end{itemize}
"""


def test_flags_only_duplicated_leading_verbs(tmp_path):
    gd = _make_guide(tmp_path, CHECKPOINT)
    leaks = find_bloom_leaks(gd)
    ids = sorted(leak.los_id for leak in leaks)
    assert ids == ["GAA-1.1", "GAA-1.2"]          # the two dup-verb items only
    assert all(leak.file == "01_m1_intro.tex" for leak in leaks)


def test_clean_guide_has_no_leaks(tmp_path):
    clean = r"""
\begin{itemize}
  \item[X-1.1] Explain how graphs represent problem spaces for search.
  \item[X-1.2] Apply DFS to explore a search tree and explain suboptimality.
\end{itemize}
"""
    gd = _make_guide(tmp_path, clean)
    assert find_bloom_leaks(gd) == []


def test_case_insensitive_same_word_dup(tmp_path):
    # "Identify Identify" (both capitalised) and "use use" both count
    body = r"""
\begin{itemize}
  \item[X-1.1] Identify Identify code that benefits from a Facade pattern.
  \item[X-1.2] use use context managers to guarantee cleanup on error paths.
\end{itemize}
"""
    gd = _make_guide(tmp_path, body)
    assert sorted(leak.los_id for leak in find_bloom_leaks(gd)) == ["X-1.1", "X-1.2"]


def test_line_numbers_reported(tmp_path):
    gd = _make_guide(tmp_path, CHECKPOINT)
    by_id = {leak.los_id: leak for leak in find_bloom_leaks(gd)}
    assert by_id["GAA-1.1"].line == 4          # 1-indexed line of the \item
