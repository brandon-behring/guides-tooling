"""Unit tests for tooling.generate.bib_ledger_to_bib (research-gather schema → .bib)."""
from __future__ import annotations

import textwrap

import pytest
import yaml

from tooling.generate.bib_ledger_to_bib import SENTINEL, convert, render_bib, render_entry

LEDGER = {
    "entries": [
        {"bibkey": "vaswani2017attention", "title": "Attention Is All You Need",
         "primary_url": "https://arxiv.org/abs/1706.03762", "status": "verified",
         "claim_family": "transformers", "authors": "Vaswani et al. (2017)",
         "venue": "NeurIPS 2017", "code_url": "https://github.com/tensorflow/tensor2tensor"},
        {"bibkey": "chollet2017xception", "title": "Xception: Deep Learning with Depthwise Separable Convolutions",
         "primary_url": "https://openaccess.thecvf.com/x", "status": "verified",
         "claim_family": "cnn", "authors": "François Chollet", "venue": "CVPR 2017"},
        {"bibkey": "huyen2023blog", "title": "Building LLM Applications for Production",
         "primary_url": "https://huyenchip.com/blog/llm.html", "status": "unverified",
         "claim_family": "llmops", "venue": "huyenchip.com blog (2023)"},
        {"bibkey": "smith2020note", "title": "Some Note",
         "primary_url": "https://example.org/x", "status": "unverified", "claim_family": "misc"},
    ]
}


def test_entry_types():
    by_key = {e["bibkey"]: e for e in LEDGER["entries"]}
    assert render_entry(by_key["vaswani2017attention"]).startswith("@article{vaswani2017attention,")
    assert render_entry(by_key["chollet2017xception"]).startswith("@inproceedings{chollet2017xception,")
    assert render_entry(by_key["huyen2023blog"]).startswith("@online{huyen2023blog,")
    assert render_entry(by_key["smith2020note"]).startswith("@misc{smith2020note,")


def test_arxiv_note_and_authors():
    out = render_entry(LEDGER["entries"][0])
    assert "note = {arXiv:1706.03762" in out
    assert "code: \\url{https://github.com/tensorflow/tensor2tensor}" in out  # URL \url-wrapped
    assert "author = {Vaswani and others}," in out          # "et al." → "and others"
    assert "year = {2017}," in out
    assert "title = {{Attention Is All You Need}}," in out   # double brace protects case


def test_render_is_sorted_and_has_sentinel():
    out = render_bib(LEDGER["entries"])
    assert out.startswith(SENTINEL)
    keys = [ln.split("{", 1)[1].rstrip(",") for ln in out.splitlines() if ln.startswith("@")]
    assert keys == sorted(keys)                              # bibkey-sorted
    assert render_bib(LEDGER["entries"]) == out              # idempotent / deterministic


def _make_guide(tmp_path):
    gd = tmp_path / "topic" / "slug"
    (gd / "review" / "research").mkdir(parents=True)
    (gd / "guide").mkdir(parents=True)
    (gd / "review" / "research" / "bib_ledger.yml").write_text(yaml.safe_dump(LEDGER))
    return gd


def test_convert_writes_and_is_idempotent(tmp_path):
    gd = _make_guide(tmp_path)
    convert(gd)
    bib = gd / "guide" / "references.bib"
    first = bib.read_text()
    assert SENTINEL in first and first.count("@") == 4
    convert(gd)                                              # re-run
    assert bib.read_text() == first                          # byte-identical


def test_convert_refuses_handauthored_without_force(tmp_path):
    gd = _make_guide(tmp_path)
    bib = gd / "guide" / "references.bib"
    bib.write_text("@article{hand2020,\n  title = {Hand authored}\n}\n")  # no sentinel
    with pytest.raises(ValueError, match="hand-authored"):
        convert(gd)
    convert(gd, force=True)                                  # --force overwrites
    assert SENTINEL in bib.read_text()


def test_convert_overwrites_stub_without_force(tmp_path):
    gd = _make_guide(tmp_path)
    bib = gd / "guide" / "references.bib"
    bib.write_text("% Bibliography for X\n% Add entries as you work through each module.\n")  # stub, 0 @ entries
    convert(gd)  # no --force needed for a stub
    assert SENTINEL in bib.read_text() and bib.read_text().count("@") == 4


def test_convert_rejects_debate_ledger(tmp_path):
    gd = _make_guide(tmp_path)
    (gd / "review" / "research" / "bib_ledger.yml").write_text(
        yaml.safe_dump({"sources": [{"bibkey": "x", "tier": "T1", "role": "y"}]})
    )
    with pytest.raises(ValueError, match="entries"):
        convert(gd)


# ── LaTeX-safety: author '&' separators, free-text escaping, idempotency ──────
# Regression coverage for the build-breakers found in Gold-wave 2 (grokking_*):
# raw ' & ' author separators ("Misplaced alignment tab") and raw URL underscores
# in a free-text note ("Missing $ inserted").

def test_amp_author_separator_becomes_and():
    e = {"bibkey": "casella2002", "title": "Statistical Inference",
         "authors": "George Casella & Roger L. Berger (2002)",
         "primary_url": "https://example.org/x", "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "author = {George Casella and Roger L. Berger}," in out
    assert " & " not in out                                   # no raw alignment-tab survives


def test_comma_separated_author_list_becomes_and():
    # biber rejects ">=2 commas" author fields; the ledger uses comma lists.
    e = {"bibkey": "cho2014", "title": "RNN Encoder-Decoder",
         "authors": "Kyunghyun Cho, Bart van Merrienboer, Caglar Gulcehre, Yoshua Bengio",
         "primary_url": "https://example.org/x", "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "author = {Kyunghyun Cho and Bart van Merrienboer and Caglar Gulcehre and Yoshua Bengio}," in out
    assert ", " not in out.split("author = {")[1].split("}")[0]   # no comma survives in author


def test_single_last_first_author_kept():
    # exactly one comma = valid "Last, First" biblatex; must NOT be split
    e = {"bibkey": "knuth1997", "title": "TAOCP", "authors": "Knuth, Donald E.",
         "primary_url": "https://example.org/x", "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "author = {Knuth, Donald E.}," in out


# Adversarial-review regressions (comma rule must only split all-multi-word lists):

def _author(authors):
    return render_entry({"bibkey": "x", "title": "t", "authors": authors,
                         "primary_url": "https://e.org/x", "status": "v", "claim_family": "c"})


def test_last_first_multiauthor_not_shredded():
    # "Last, First, Last, First" (single-word tokens) must NOT become 4 authors
    out = _author("Vaswani, Ashish, Shazeer, Noam")
    assert " and " not in out.split("author = {")[1].split("}")[0]


def test_suffix_name_not_split():
    for nm in ("de la Cruz, Jr, Juan", "King, Martin Luther, Jr."):
        out = _author(nm)
        assert f"author = {{{nm}}}," in out          # preserved verbatim, no ' and '


def test_full_name_list_still_splits():
    out = _author("Kyunghyun Cho, Bart van Merrienboer, Caglar Gulcehre")
    assert "author = {Kyunghyun Cho and Bart van Merrienboer and Caglar Gulcehre}," in out


def test_etal_with_two_author_comma_list():
    out = _author("Kaiming He, Xiangyu Zhang, et al.")
    assert "author = {Kaiming He and Xiangyu Zhang and others}," in out


def test_escape_text_paren_math_internal_paren_preserved():
    e = {"bibkey": "x", "title": r"Use \(f(x_i)=0\) in proof", "authors": "Z",
         "primary_url": "https://e.org/x", "status": "v", "claim_family": "c"}
    out = render_entry(e)
    assert r"\(f(x_i)=0\)" in out                     # whole math span kept; x_i not escaped


def test_escape_text_lone_dollar_escaped():
    e = {"bibkey": "x", "title": "a budget of $5 per item", "authors": "Z",
         "primary_url": "https://e.org/x", "status": "v", "claim_family": "c"}
    out = render_entry(e)
    assert r"\$5" in out                              # odd $ count → literal, escaped


def test_escape_text_even_dollar_math_preserved():
    e = {"bibkey": "x", "title": r"nucleus top-$p$ sampling", "authors": "Z",
         "primary_url": "https://e.org/x", "status": "v", "claim_family": "c"}
    out = render_entry(e)
    assert "$p$" in out                               # balanced $...$ kept as math


def test_entry_blocks_brace_aware(tmp_path):
    from tooling.generate.bib_ledger_to_bib import _entry_blocks
    text = (
        "@misc{indented,\n  title = {X}\n  }\n\n"               # indented final brace
        "@book{multiline,\n  abstract = {First line\n}\n  ,\n  year = {2020}\n}\n"  # } alone on a line
    )
    blocks = dict(_entry_blocks(text))
    assert set(blocks) == {"indented", "multiline"}
    assert "year = {2020}" in blocks["multiline"]              # not truncated at the field's }-line


def test_bare_ampersand_backstop_escaped():
    # an author legitimately containing '&' (no surrounding spaces → not a separator)
    e = {"bibkey": "att1970", "title": "Unix", "authors": "AT&T Bell Labs",
         "primary_url": "https://example.org/x", "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "author = {AT\\&T Bell Labs}," in out


def test_already_escaped_venue_not_double_escaped():
    # idempotency: a ledger venue already carrying \& must stay \& (not \\&)
    e = {"bibkey": "gelman2013", "title": "Bayesian Data Analysis",
         "authors": "Gelman and Carlin",
         "venue": "Chapman \\& Hall/CRC Texts; vol_3",
         "primary_url": "https://example.org/x", "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "Chapman \\& Hall" in out and "\\\\&" not in out    # not double-escaped
    assert "vol\\_3" in out                                    # bare _ now escaped


def test_code_url_underscores_are_url_wrapped():
    e = {"bibkey": "x2013", "title": "X", "authors": "Y",
         "primary_url": "https://routledge.com/x", "status": "verified", "claim_family": "x",
         "code_url": "https://books.google.com/about/Bayesian_Data_Analysis_3e.html"}
    out = render_entry(e)
    assert "code: \\url{https://books.google.com/about/Bayesian_Data_Analysis_3e.html}" in out


def test_title_ampersand_escaped_math_preserved():
    e = {"bibkey": "x2020", "title": "Cats & Dogs: $O(n^2)$ Scaling",
         "authors": "Z", "primary_url": "https://example.org/x",
         "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "Cats \\& Dogs" in out                              # bare & escaped
    assert "$O(n^2)$" in out                                   # math left intact


def test_title_underscore_escaped_outside_math():
    # the SHUFFLE_HASH case: a literal config-name underscore in a title breaks
    # the build ("Missing $"); escape it, but keep a real math subscript intact.
    e = {"bibkey": "spark2021", "title": "Spark hints: SHUFFLE_HASH and $x_i$ scaling",
         "authors": "Z", "primary_url": "https://example.org/x",
         "status": "verified", "claim_family": "x"}
    out = render_entry(e)
    assert "SHUFFLE\\_HASH" in out                             # literal _ escaped
    assert "$x_i$" in out                                      # math subscript intact


# ── hand-appended (orphan) entry preservation ────────────────────────────────
# Guides append Gold E/F citation sources below the generated block; regenerating
# must NOT delete them (else every E/F \parencite becomes an undefined citation).

_MANUAL = (
    "\n% --- Gold appendix E/F sources (hand-added) ---\n"
    "@book{huang2026manual,\n"
    "  author = {Eli Huang},\n"
    "  title = {Some Hand-Added Book},\n"
    "  howpublished = {Manning},\n"
    "  urldate = {2026-06-22},\n"
    "}\n"
)


def test_regenerate_preserves_manual_entries(tmp_path):
    gd = _make_guide(tmp_path)
    bib = gd / "guide" / "references.bib"
    convert(gd)                                                # generate the ledger part
    bib.write_text(bib.read_text() + _MANUAL)                 # hand-append a manual entry
    convert(gd)                                                # regenerate
    out = bib.read_text()
    assert "@book{huang2026manual," in out                    # manual entry survives
    assert "howpublished = {Manning}" in out                  # incl. generator-foreign fields
    assert "PRESERVED" in out                                 # the divider is present
    assert out.count("@") == 5                                # 4 ledger + 1 manual


def test_manual_preservation_is_idempotent(tmp_path):
    gd = _make_guide(tmp_path)
    bib = gd / "guide" / "references.bib"
    convert(gd)
    bib.write_text(bib.read_text() + _MANUAL)
    convert(gd)
    once = bib.read_text()
    convert(gd)                                                # re-run
    assert bib.read_text() == once                            # byte-identical


def test_no_orphans_means_no_divider(tmp_path):
    gd = _make_guide(tmp_path)
    convert(gd)
    out = (gd / "guide" / "references.bib").read_text()
    assert "PRESERVED" not in out                             # no spurious divider
    assert out.endswith("\n")


def test_escape_text_price_beside_math():
    from tooling.generate.bib_ledger_to_bib import _escape_text
    assert _escape_text(r"\$5 and $x_i$") == r"\$5 and $x_i$"        # math preserved
    assert _escape_text("Costs $50 and $200") == r"Costs \$50 and \$200"  # both literal
    assert _escape_text("$x$ costs $5") == r"$x$ costs \$5"          # math + price


def test_authors_particle_surname_not_split():
    out = _author("van der Berg, Johann Smith")
    assert "author = {van der Berg, Johann Smith}," in out      # single author, not shredded


def test_entry_blocks_skips_commented_and_caps_unbalanced():
    from tooling.generate.bib_ledger_to_bib import _entry_blocks
    assert _entry_blocks("% @misc{old,\n  title={X}\n}\n") == []          # commented → ignored
    keys = sorted(k for k, _ in _entry_blocks("@misc{a,\n  t = {X}\n\n@book{b,\n  y={2}\n}\n"))
    assert keys == ["a", "b"]                                             # unbalanced 'a' didn't swallow 'b'
