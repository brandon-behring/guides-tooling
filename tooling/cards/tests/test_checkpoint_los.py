"""Regression test: checkpoint LOS capture must accept digit-containing prefixes (e.g. DLP2).

The original regex used ``[A-Z]+-[\\d.]+``, which stopped at the digit in a prefix
like ``DLP2`` and returned los_id=None for every checkpoint in such guides — silently
capping their card LOS-traceability. Fixed to ``[A-Z0-9]+`` (matching the canonical LOS
grammar in tooling.validation.extract_los).
"""
from tooling.cards.extract_cards import extract_checkpoints

CONTENT = r"""
\begin{tcolorbox}[checkpointbox, title={Self-Check: M2}]
\begin{enumerate}
\item What is a tensor's rank, shape, and dtype? \hfill\textit{(DLP2-2.1)}
\item Explain how a dense layer computes its output. \hfill\textit{(DLP2-2.3)}
\item A non-digit prefix must still work. \hfill\textit{(TA-1.1)}
\end{enumerate}
\end{tcolorbox}
"""


def test_checkpoint_captures_digit_prefix_los():
    cards = extract_checkpoints(CONTENT, "02_m2.tex", "vol0", "2", set())
    los = [c["los_id"] for c in cards]
    assert "DLP2-2.1" in los, f"digit-prefix LOS not captured: {los}"
    assert "DLP2-2.3" in los
    assert "TA-1.1" in los  # non-digit prefix still works
    assert all(c["los_id"] for c in cards), f"some checkpoint lost its los_id: {los}"
