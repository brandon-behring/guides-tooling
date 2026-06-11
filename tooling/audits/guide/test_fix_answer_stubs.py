"""Unit tests for ``fix_answer_stubs.py``.

Covers the three documented bug fixes:
1. ``first_sentence`` no longer truncates on digit-period (e.g. ``1.``).
2. ``extract_inline_parts`` detects ``\\textbf{(a)}`` and ``\\textbf{1.}``
   inline patterns when there is no ``\\begin{enumerate}`` block.
3. ``has_multipart_question`` recognizes inline ``(a)~`` / ``(a)`` markers
   in problem statements, not only ``\\begin{enumerate}``.
"""

from __future__ import annotations

import unittest

from tooling.audits.guide.fix_answer_stubs import (
    _strip_nested_lists,
    extract_enumerate_items,
    extract_inline_parts,
    first_sentence,
    generate_answer,
    has_multipart_question,
)


class FirstSentenceTests(unittest.TestCase):
    """``first_sentence`` must not truncate at digit-period boundaries."""

    def test_does_not_break_on_numeric_period(self) -> None:
        text = "1. Use exhaustive grid search. Then validate."
        out = first_sentence(text)
        self.assertNotEqual(out, "1.")
        self.assertIn("grid search", out)

    def test_does_not_break_on_decimal(self) -> None:
        text = "Set $T=0.7$ as the default. Increase if std drops below 0.1."
        out = first_sentence(text)
        self.assertIn("0.7", out)
        self.assertIn("default", out)

    def test_breaks_at_real_sentence_boundary(self) -> None:
        text = (
            "The completion mask is a binary tensor of length P plus C. "
            "It zeros out prompt token gradients."
        )
        out = first_sentence(text)
        self.assertTrue(out.endswith("plus C."))

    def test_returns_full_text_when_short(self) -> None:
        text = "Brief answer here."
        self.assertEqual(first_sentence(text), text)

    def test_min_break_pos_prevents_early_truncation(self) -> None:
        text = "Foo. Bar Baz Qux."
        out = first_sentence(text, min_break_pos=30)
        self.assertNotEqual(out, "Foo.")


class ExtractInlinePartsTests(unittest.TestCase):
    """``extract_inline_parts`` must find ``(a)`` and ``1.`` inline patterns."""

    def test_lettered_inline_parts(self) -> None:
        text = (
            r"\textbf{(a) Policy ratio:} ratio = 20.09." "\n\n"
            r"\textbf{(b) Unclipped loss:} 30.13." "\n\n"
            r"\textbf{(c) Clipped loss:} 1.80."
        )
        parts = extract_inline_parts(text)
        self.assertIsNotNone(parts)
        assert parts is not None
        self.assertEqual(len(parts), 3)
        labels = [p[0] for p in parts]
        self.assertEqual(labels, ["(a)", "(b)", "(c)"])
        self.assertIn("Policy ratio", parts[0][1])
        self.assertIn("ratio = 20.09", parts[0][2])

    def test_numbered_inline_parts(self) -> None:
        text = (
            r"\textbf{1. GRPO advantage:} fresh on-policy generation." "\n\n"
            r"\textbf{2. DPO degradation:} preference style leakage." "\n\n"
            r"\textbf{3. Choose DPO when:} compute-scarce or no verifier."
        )
        parts = extract_inline_parts(text)
        self.assertIsNotNone(parts)
        assert parts is not None
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0][0], "1.")
        self.assertIn("GRPO advantage", parts[0][1])

    def test_returns_none_with_single_part(self) -> None:
        text = r"\textbf{(a) Single bullet only:} content."
        self.assertIsNone(extract_inline_parts(text))


class HasMultipartQuestionTests(unittest.TestCase):
    """``has_multipart_question`` recognizes both ``enumerate`` and inline."""

    def test_detects_enumerate(self) -> None:
        problem = r"Calculate: \begin{enumerate}\item one \item two\end{enumerate}"
        self.assertTrue(has_multipart_question(problem))

    def test_detects_tilde_letters(self) -> None:
        problem = (
            "Calculate: (a)~the policy ratio, (b)~the unclipped loss, "
            "(c)~the clipped loss."
        )
        self.assertTrue(has_multipart_question(problem))

    def test_detects_space_letters(self) -> None:
        problem = (
            "Provide: (a) a strategy, (b) a metric to monitor, "
            "(c) a fallback plan."
        )
        self.assertTrue(has_multipart_question(problem))

    def test_does_not_fire_on_single_part(self) -> None:
        problem = "What is the policy ratio for this token?"
        self.assertFalse(has_multipart_question(problem))


class GenerateAnswerIntegrationTests(unittest.TestCase):
    """End-to-end: lettered Approach with inline parts produces full enumerate."""

    def test_lettered_inline_produces_enumerate(self) -> None:
        solution = (
            r"\begin{solution}" "\n"
            r"\textbf{Approach:} \textbf{(a) Policy ratio:}" "\n"
            r"$\text{ratio} = \exp(3.0) = 20.09$." "\n\n"
            r"\textbf{(b) Unclipped loss:}" "\n"
            r"$30.13$." "\n\n"
            r"\textbf{(c) Clipped loss:}" "\n"
            r"$1.80$." "\n\n"
            r"\textbf{Key Insight:} Clipping is asymmetric." "\n"
            r"\end{solution}"
        )
        out = generate_answer(solution, has_enumerate_in_problem=True)
        self.assertIn(r"\begin{enumerate}[label=(\alph*)]", out)
        self.assertIn("Policy ratio", out)
        self.assertIn("Unclipped loss", out)
        self.assertIn("Clipped loss", out)
        self.assertNotIn(r"\textbf{1.", out)

    def test_numbered_inline_produces_enumerate(self) -> None:
        solution = (
            r"\begin{solution}" "\n"
            r"\textbf{Approach:} \textbf{1. GRPO advantage:} on-policy gen." "\n\n"
            r"\textbf{2. DPO degradation:} style leakage from pairs." "\n\n"
            r"\textbf{3. Choose DPO when:} compute scarce." "\n\n"
            r"\textbf{Key Insight:} They are complementary." "\n"
            r"\end{solution}"
        )
        out = generate_answer(solution, has_enumerate_in_problem=True)
        self.assertIn(r"\begin{enumerate}[label=(\alph*)]", out)
        self.assertIn("GRPO advantage", out)
        self.assertIn("DPO degradation", out)
        self.assertNotIn(r"\textbf{1.", out.replace(r"\textbf{1. GRPO", ""))

    def test_nested_itemize_inside_enumerate_does_not_split(self) -> None:
        approach = (
            r"\textbf{Approach:}" "\n"
            r"\begin{enumerate}" "\n"
            r"  \item \textbf{Two paths to zero gradients:}" "\n"
            r"    \begin{itemize}" "\n"
            r"      \item $T=0.3$: low diversity collapses advantage." "\n"
            r"      \item $T=1.2$: all rewards are zero." "\n"
            r"    \end{itemize}" "\n"
            r"  \item \textbf{Next temperature:} Try $T=0.7$." "\n"
            r"  \item \textbf{Temperature-G interaction:} Scale together." "\n"
            r"\end{enumerate}"
        )
        items = extract_enumerate_items(approach)
        self.assertIsNotNone(items)
        assert items is not None
        # Outer enumerate has 3 top-level items, not 5+ from nested itemize
        self.assertEqual(len(items), 3)
        self.assertIn("Two paths", items[0])
        self.assertIn("Next temperature", items[1])
        self.assertIn("interaction", items[2])

    def test_strip_nested_lists_removes_inner_blocks(self) -> None:
        text = (
            "Lead-in text. "
            r"\begin{itemize}\item one\item two\end{itemize} "
            "Trailing prose."
        )
        out = _strip_nested_lists(text)
        self.assertNotIn(r"\begin{itemize}", out)
        self.assertIn("Lead-in", out)
        self.assertIn("Trailing", out)

    def test_generate_answer_with_nested_itemize_produces_valid_latex(self) -> None:
        solution = (
            r"\begin{solution}" "\n"
            r"\textbf{Approach:}" "\n"
            r"\begin{enumerate}" "\n"
            r"  \item \textbf{First mechanism:} The model learns to game the reward." "\n"
            r"    \begin{itemize}\item sub one\item sub two\end{itemize}" "\n"
            r"  \item \textbf{Second mechanism:} Held-out tests close the loophole." "\n"
            r"  \item \textbf{Third mechanism:} KL alone cannot fix this." "\n"
            r"\end{enumerate}" "\n"
            r"\textbf{Key Insight:} Reward must match the true objective." "\n"
            r"\end{solution}"
        )
        out = generate_answer(solution, has_enumerate_in_problem=True)
        # Must produce balanced \begin/\end pairs (no unclosed nested itemize)
        self.assertEqual(
            out.count(r"\begin{enumerate}"), out.count(r"\end{enumerate}")
        )
        self.assertEqual(
            out.count(r"\begin{itemize}"), out.count(r"\end{itemize}")
        )

    def test_no_truncation_to_bullet_label(self) -> None:
        solution = (
            r"\begin{solution}" "\n"
            r"\textbf{Approach:} \textbf{1. First mechanism.} The model" "\n"
            r"learns to pattern-match on test inputs and hard-code outputs." "\n\n"
            r"\textbf{Key Insight:} Reward hacking." "\n"
            r"\end{solution}"
        )
        out = generate_answer(solution, has_enumerate_in_problem=False)
        self.assertNotEqual(out.strip(), r"\textbf{Answer:} \textbf{1.")


if __name__ == "__main__":
    unittest.main()
