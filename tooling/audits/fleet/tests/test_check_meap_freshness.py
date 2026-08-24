"""Tests for the MEAP freshness checker's auth-free signal (guides-tooling#20/#21).

Fixture HTML mirrors the real product pages probed 2026-08-24: the TOC is a JS
spinner (absent from static HTML), the nav bar always contains "MEAP", and the
month fields (`MEAP began` / `Last updated` / `Publication in` / ISBN / pages)
are the only auth-free values that move when a MEAP updates. No network.
"""
from __future__ import annotations

import pytest

from tooling.audits.fleet import check_meap_freshness as cm

NAV = "<nav>MEAP liveBook liveVideo liveProject free content register pBook</nav>"

MEAP_PAGE = f"""<html><body>{NAV}
<div class="toc-loading-container"></div>
<p>MEAP began September 2025 &middot; Last updated April 2026 &middot;
Publication in Early 2027 (estimated) &middot; ISBN 9781633434516 &middot;
375 pages (estimated)</p></body></html>"""

MEAP_PAGE_BUMPED = MEAP_PAGE.replace("Last updated April 2026", "Last updated July 2026")

PUBLISHED_PAGE = f"""<html><body>{NAV}
<div class="toc-loading-container"></div>
<p>by Nicole Koenigstein November 2025 ISBN 9781633437883 256 pages</p>
</body></html>"""


# ------------------------------------------------------------------ parse_state
def test_meap_page_fields_and_signature():
    st = cm.parse_state(MEAP_PAGE)
    assert st["is_meap"] is True
    assert st["meap_began"] == "September 2025"
    assert st["last_updated_month"] == "April 2026"
    assert st["publication_estimate"] == "Early 2027"
    assert st["isbn"] == "9781633434516"
    assert st["pages"] == 375
    # The blind-signature bug: sha256("||")[:16]. Must never reappear.
    assert st["signature"] != "565d240f5343e625"
    # Deterministic for identical input.
    assert st["signature"] == cm.parse_state(MEAP_PAGE)["signature"]


def test_published_page_is_not_meap_despite_nav_bar():
    st = cm.parse_state(PUBLISHED_PAGE)
    assert st["is_meap"] is False  # \bMEAP\b in the nav must not count
    assert st["meap_began"] == ""
    assert st["last_updated_month"] == ""
    assert st["isbn"] == "9781633437883"
    assert st["signature"] != cm.parse_state(MEAP_PAGE)["signature"]


def test_signature_moves_when_last_updated_moves():
    assert cm.parse_state(MEAP_PAGE)["signature"] != cm.parse_state(MEAP_PAGE_BUMPED)["signature"]


# ------------------------------------------------------------------ month_to_iso
@pytest.mark.parametrize("raw,iso", [
    ("April 2026", "2026-04"), ("September 2025", "2025-09"),
    ("Early 2027", None), ("", None), (None, None),
])
def test_month_to_iso(raw, iso):
    assert cm.month_to_iso(raw) == iso


# ------------------------------------------------------------------ classify (sticky staleness)
def _live(page=MEAP_PAGE):
    return cm.parse_state(page)


def test_sticky_stale_vs_manifest_month():
    # Guide captured 2026-02; live page says Last updated April 2026 -> STALE,
    # and STALE again on a second run even though the signature matched prior.
    live = _live()
    row1 = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                       prior=None, captured=5, build_date="2026-02-11")
    assert row1["status"] == "STALE" and "re-capture owed" in row1["drift"]
    row2 = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                       prior={"signature": live["signature"]}, captured=5,
                       build_date="2026-02-11")
    assert row2["status"] == "STALE"  # sticky: prior signature match does not clear it


def test_fresh_capture_is_baseline_then_ok():
    live = _live()
    first = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior=None, captured=5, build_date="2026-05-01")
    assert first["status"] == "BASELINE"
    again = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior={"signature": live["signature"]}, captured=5,
                        build_date="2026-05-01")
    assert again["status"] == "OK"


def test_signature_change_is_stale():
    live_old, live_new = _live(), _live(MEAP_PAGE_BUMPED)
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live_new,
                      prior={"signature": live_old["signature"]}, captured=5,
                      build_date=None)
    assert row["status"] == "STALE" and "Last updated July 2026" in row["drift"]


def test_renamed_wins_over_staleness():
    row = cm.classify("g", "old-slug", "https://www.manning.com/books/new-slug",
                      _live(), prior=None, captured=5, build_date="2026-02-11")
    assert row["status"] == "RENAMED"


# ------------------------------------------------------------------ version_overlay
def test_overlay_elevates_version_lag():
    row = {"status": "BASELINE", "drift": "baseline established"}
    out = cm.version_overlay(row, {"meap_version": "v4", "extracted": "2026-02-11"},
                             {"version": 7, "last_updated": "2026-07-14"})
    assert out["status"] == "STALE" and "v4 -> v7" in out["drift"]


def test_overlay_normalizes_string_versions():
    row = {"status": "OK", "drift": "no change"}
    out = cm.version_overlay(row, {"meap_version": 4}, {"version": "v12", "last_updated": None})
    assert out["status"] == "STALE" and out["live_version"] == 12


def test_overlay_keeps_renamed_leading_but_appends_drift():
    row = {"status": "RENAMED", "drift": "Manning renamed slug: 'a' -> 'b'"}
    out = cm.version_overlay(row, {"meap_version": "v4", "extracted": "2026-02-11"},
                             {"version": 6, "last_updated": "2026-06-01"})
    assert out["status"] == "RENAMED"
    assert "also stale: v4 -> v6" in out["drift"]


def test_overlay_uses_captured_as_build_date_alias():
    assert cm.guide_build_date({"captured": "2026-06-01"}) == "2026-06-01"
    assert cm.guide_build_date({"extracted": "2026-05-30", "captured": "2026-06-01"}) == "2026-05-30"
    assert cm.guide_build_date({}) is None


# ------------------------------------------------------------------ overrides map hygiene
def test_slug_overrides_are_hyphenated_and_unique():
    values = list(cm.SLUG_OVERRIDES.values())
    assert len(values) == len(set(values)), "duplicate live slug in SLUG_OVERRIDES"
    for internal, live in cm.SLUG_OVERRIDES.items():
        assert "_" not in live, f"{internal}: live slug '{live}' is not hyphenated"
        assert live == live.lower()


def test_overrides_win_over_inlined_map():
    # rlhf_book appears in both; the override (post-rename slug) must win.
    assert cm.resolve_slug("rlhf_book", None) == "reinforcement-learning-from-human-feedback"
    # A hand-authored manifest still outranks the override.
    assert cm.resolve_slug("rlhf_book", {"livebook_slug": "the-rlhf-book"}) == "the-rlhf-book"
    # The checker's own minimal bootstrap must NOT outrank the override.
    boot = {"livebook_slug": "the-rlhf-book",
            "_generated_by": "tooling.audits.fleet.check_meap_freshness (minimal bootstrap)"}
    assert cm.resolve_slug("rlhf_book", boot) == "reinforcement-learning-from-human-feedback"
