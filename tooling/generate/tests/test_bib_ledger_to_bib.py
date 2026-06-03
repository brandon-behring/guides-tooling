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
    assert "code: https://github.com/tensorflow/tensor2tensor" in out
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
