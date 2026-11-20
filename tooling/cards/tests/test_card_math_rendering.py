r"""Regression tests: card math and currency must survive the deck pipeline.

The deck exporter runs ``convert_latex_to_anki`` then ``convert_math_delimiters``
on the card YAML. Found in the DeepSeek refresh review (guides-manning#126):

- ``\%``, ``\&``, ``\texttt`` and ``\mathrm`` inside math lost their escapes or
  became HTML, because the text rewrites ran before math was protected.
- ``align*`` and ``aligned`` became a nested ``\[`` with ``<br>`` for ``\\``.
- Escaped currency ``\$`` was written to the YAML as a bare ``$`` and then paired
  as a math delimiter.
- ``\parencite`` (and other cite variants) left the raw bibkey on the card.
"""
import html
import re

import pytest

from tooling.anki.yaml_to_apkg import convert_math_delimiters
from tooling.cards.extract_cards import clean_latex
from tooling.cards.generate_anki import convert_latex_to_anki


def deck(text: str) -> str:
    """The deck exporter's chain."""
    return convert_math_delimiters(convert_latex_to_anki(text))


def math_spans(rendered: str) -> list[str]:
    """Math as MathJax will read it (HTML entities decoded)."""
    spans = re.findall(r'\\\((.*?)\\\)|\\\[(.*?)\\\]', rendered, re.DOTALL)
    return [html.unescape(a or b) for a, b in spans]


@pytest.mark.parametrize("src, expected", [
    (r"so $8/64 = 12.5\%$ of traffic", r"8/64 = 12.5\%"),
    (r"assume $F\&B = F + B = 3$ here", r"F\&B = F + B = 3"),
    # Anki's MathJax has no textmacros: text-mode arguments must be de-escaped.
    (r"set $T_d = \texttt{max\_iters}$ now", r"T_d = \texttt{max_iters}"),
    (r"so $\text{actual\%} > 5$ holds", "\\text{actual%} > 5"),
    (r"so $\text{``the''}$ word", "\\text{\u201cthe\u201d}"),
    (r"keep $\mathrm{max\_iters}$ math", r"\mathrm{max\_iters}"),
    (r"with $T_{\mathrm{FB}}$ units", r"T_{\mathrm{FB}}"),
    (r"where $\textit{n} < 5$ holds", r"\textit{n} < 5"),
])
def test_math_content_survives(src, expected):
    assert math_spans(deck(src)) == [expected]


def test_lt_inside_math_is_html_escaped():
    out = deck(r"if $a<b$ then")
    assert "a&lt;b" in out and "<b" not in out.replace("<br", "")


def test_existing_entity_inside_math_not_double_escaped():
    assert "x_{&lt;t}" in deck(r"tokens $x_{&lt;t}$ seen")


def test_align_star_becomes_one_aligned_display():
    src = "Weights:\n\\begin{align*}\n  w_5 &= 0.646,\\\\\n  w_3 &= 0.354.\n\\end{align*}\nDone."
    out = deck(src)
    assert out.count(r"\[") == 1 and out.count(r"\]") == 1
    (span,) = math_spans(out)
    assert r"\begin{aligned}" in span and r"\end{aligned}" in span
    assert r"\\" in span and "<br>" not in span


def test_extractor_aligned_display_is_kept():
    src = "Then:\n\\[\\begin{aligned}\n  a &= 1,\\\\\n  b &= 2.\n\\end{aligned}\\]\nEnd."
    out = deck(src)
    assert out.count(r"\[") == 1
    (span,) = math_spans(out)
    assert span.strip().startswith(r"\begin{aligned}") and "&= 1" in span


def test_prose_escapes_still_convert():
    out = deck(r"about 50\% of R\&D, see \texttt{train.py}")
    assert "50% of R&D" in html.unescape(out) and "<code>train.py</code>" in out


@pytest.mark.parametrize("src", [
    r"reported \$5.576M (2.788M H800 GPU-hours at an assumed \$2 per hour) rests",
    r"about \$10K for 800K traces, vs \$202K for the RL run",
    r"Ratio: $5{,}000 \times 2 = 10{,}000$ USD, about \$1.7K per student",
])
def test_currency_never_pairs_as_math(src):
    yaml_text = clean_latex(src)
    out = deck(yaml_text)
    for span in math_spans(out):
        assert not re.search(r"\b(?:hour|for|per|about|student)\b", span), span
    assert html.unescape(re.sub(r'\\\(.*?\\\)', '', out)).count("$") == src.count(r"\$")


def test_clean_latex_keeps_currency_escaped():
    out = clean_latex(r"costs \$10K and $x^2$ more")
    assert r"\$10K" in out and "$x^2$" in out


@pytest.mark.parametrize("src", [
    r"split into 16 mini-batches~\parencite{deepseekr1_2025}.",
    r"split into 16 mini-batches~\parencite{deepseekr1_2025,deepseekmath_grpo_2024}.",
    r"split into 16 mini-batches \citep[p.~3]{deepseekr1_2025}.",
    r"split into 16 mini-batches~\textcite{deepseekr1_2025}.",
    r"split into 16 mini-batches~\autocite[see][§2]{deepseekr1_2025}.",
    r"split into 16 mini-batches~\cite{deepseekr1_2025}.",
])
def test_cite_variants_leave_no_bibkey(src):
    out = clean_latex(src)
    assert "deepseek" not in out and "{" not in out
    assert out.rstrip().endswith("mini-batches.")


@pytest.mark.parametrize("src, expected", [
    (r"A variant proposed by \textcite{shazeer2019mqa} that uses", "A variant proposed by Shazeer (2019) that uses"),
    (r"refined by \textcite{hoffmann2022chinchilla} at", "refined by Hoffmann (2022) at"),
])
def test_textcite_renders_short_author_year(src, expected):
    assert clean_latex(src) == expected


@pytest.mark.parametrize("src, spans, shown", [
    (r"costs \$$0.01$/video and \$$0.10$ each", ["0.01", "0.10"], "$"),
    # a lone $\sim$ becomes the Unicode "≈" (normalize step 5), the rest pairs
    (r"L2 ($\sim$$50$\,MB, $\sim$$200$ cycles)", ["50", "200"], "\u2248"),
])
def test_currency_or_span_glued_to_math(src, spans, shown):
    out = deck(src)
    assert math_spans(out) == spans
    if shown:
        assert html.unescape(re.sub(r'\\\(.*?\\\)', '', out)).count(shown) == 2


def test_display_dollars_still_work():
    out = deck("The update:\n$$Q \\leftarrow Q + \\alpha\\delta$$\nthen more.")
    assert math_spans(out) == [r"Q \leftarrow Q + \alpha\delta"] and r"\[" in out


def test_backslash_before_currency_is_not_mangled():
    out = deck(r"the regex r'\textbackslash\$[A-Z]' matches")
    assert "&amp;#36;" not in out and "&#36;" in out


def test_currency_in_code_block_not_double_escaped():
    out = deck("Run:\n```bash\necho \\$HOME\n```\n")
    assert "&amp;#36;" not in out


def test_literal_backslash_before_escaped_dollar_yaml_form():
    # nlp_in_action ch11: \textbackslash\$ reaches the YAML as a backslash then \$
    yaml_text = "Regex:\n r'\\\\$[A-Z]{1,5}'.\n\n- Dollar amounts.\n Regex: r'\\\\$[\\d,.]+[BMK]?'."
    out = deck(yaml_text)
    assert math_spans(out) == []
    assert "&amp;#36;" not in out and out.count("&#36;") == 2


def test_display_after_opening_punctuation():
    out = deck("the norm ($$\\|x\\|_2$$) is")
    assert math_spans(out) == [r"\|x\|_2"] and out.count(r"\[") == 1


def test_texttt_keeps_double_hyphen():
    (span,) = math_spans(deck(r"run $\texttt{--lr}\ \text{--}$ now"))
    assert r"\texttt{--lr}" in span and "\\text{\u2013}" in span
