"""Tests for the brace-balanced macro-argument scanner (gt#33 row 9)."""
from __future__ import annotations

from tooling.validation._latex import iter_macro_args

MARGINS = ("interviewmargin", "patternmargin", "formulamargin", "warningmargin")


def _payloads(text: str, names=MARGINS) -> list[str]:
    return [p for _m, p, _o in iter_macro_args(text, names)]


def test_wrapped_payload_spans_lines():
    text = (
        "\\interviewmargin{``What types of tools does an agent need?'' ---\n"
        "information, action, and domain-specialized.}\n"
    )
    assert _payloads(text) == [
        "``What types of tools does an agent need?'' ---\ninformation, action, and domain-specialized."
    ]


def test_nested_textbf_kept_whole():
    text = r"\patternmargin{Tool taxonomy: \textbf{information} (temporal gap), action.}"
    assert _payloads(text) == [r"Tool taxonomy: \textbf{information} (temporal gap), action."]


def test_math_braces_kept_whole():
    text = r"\formulamargin{Beta posterior after 3 wins, 1 loss: $\mathrm{Beta}(4,2)$}"
    assert _payloads(text) == [r"Beta posterior after 3 wins, 1 loss: $\mathrm{Beta}(4,2)$"]


def test_escaped_braces_do_not_close():
    text = r"\warningmargin{a literal \} brace and a \{ set\} inside} trailing"
    assert _payloads(text) == [r"a literal \} brace and a \{ set\} inside"]


def test_two_margins_on_one_line():
    text = r"\patternmargin{first} and \warningmargin{second}"
    hits = list(iter_macro_args(text, MARGINS))
    assert [(m, p) for m, p, _o in hits] == [("patternmargin", "first"), ("warningmargin", "second")]
    assert hits[0][2] == 0 and hits[1][2] == text.index(r"\warningmargin")


def test_unterminated_arg_skipped_later_macros_still_found():
    text = r"\patternmargin{never closes \textbf{x}" + "\n" + r"\warningmargin{ok}"
    # The unterminated first macro is not yielded (depth never returns to 0), but the
    # scan resumes at the next macro head so one broken macro cannot hide the rest.
    assert _payloads(text) == ["ok"]


def test_unlisted_macro_and_name_prefix_ignored():
    text = r"\crossrefmargin{not requested} \interviewmarginx{prefix, not a hit} \interviewmargin{hit}"
    assert _payloads(text, ("interviewmargin",)) == ["hit"]


def test_empty_name_list_yields_nothing():
    assert list(iter_macro_args(r"\patternmargin{x}", ())) == []
