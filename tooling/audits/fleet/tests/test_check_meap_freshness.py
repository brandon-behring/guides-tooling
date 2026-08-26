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
                       prior={"schema": cm.STATE_SCHEMA, "signature": live["signature"]},
                       captured=5, build_date="2026-02-11")
    assert row2["status"] == "STALE"  # sticky: prior signature match does not clear it


def test_fresh_capture_is_baseline_then_ok():
    live = _live()
    first = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior=None, captured=5, build_date="2026-05-01")
    assert first["status"] == "BASELINE"
    again = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior={"schema": cm.STATE_SCHEMA, "signature": live["signature"]},
                        captured=5, build_date="2026-05-01")
    assert again["status"] == "OK"


def test_signature_change_is_stale():
    live_old, live_new = _live(), _live(MEAP_PAGE_BUMPED)
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live_new,
                      prior={"schema": cm.STATE_SCHEMA, "signature": live_old["signature"]},
                      captured=5, build_date=None)
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


# ------------------------------------------------------------------ codex review R-1/R-2/R-3
def test_legacy_v1_state_is_migration_baseline_not_stale():
    # Prior state written by the blind-signature era must not read as "changed".
    live = _live()
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                      prior={"schema": "meap_freshness/1", "signature": "565d240f5343e625"},
                      captured=5, build_date="2026-05-01")
    assert row["status"] == "BASELINE"


def test_v2_state_still_detects_change():
    live_old, live_new = _live(), _live(MEAP_PAGE_BUMPED)
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live_new,
                      prior={"schema": cm.STATE_SCHEMA, "signature": live_old["signature"]},
                      captured=5, build_date=None)
    assert row["status"] == "STALE"


def test_bootstrap_guide_keeps_stale_debt_without_build_date():
    # No manifest date: a month bump marks STALE; the next run (same month,
    # signature now recorded) must NOT launder it into OK.
    live = _live(MEAP_PAGE_BUMPED)
    again = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior={"schema": cm.STATE_SCHEMA, "signature": live["signature"],
                               "status": "STALE", "last_updated_month": "July 2026"},
                        captured=5, build_date=None)
    assert again["status"] == "STALE" and "unrefreshed" in again["drift"]


def test_snapshot_rows_must_carry_last_updated_month():
    import tooling.audits.fleet.check_meap_freshness as m
    # The run_check snapshot validator's required-keys set includes the new field.
    src = open(m.__file__).read()
    assert '"last_updated_month"}' in src.replace("\n", "").replace(" ", "")[:0] or \
        '"last_updated_month"' in src.split("_need = ")[1].split("}")[0]


# ------------------------------------------------------------------ skeptic review MF-2..MF-5
def test_overlay_keeps_unresolved_leading_but_appends_drift():
    row = {"status": "UNRESOLVED", "drift": "no livebook slug (add to SLUG_OVERRIDES)"}
    out = cm.version_overlay(row, {"meap_version": "v4", "extracted": "2026-02-11"},
                             {"version": 7, "last_updated": "2026-07-14"})
    assert out["status"] == "UNRESOLVED"
    assert "no livebook slug" in out["drift"] and "also stale: v4 -> v7" in out["drift"]


def test_published_transition_is_sticky():
    live = cm.parse_state(PUBLISHED_PAGE)
    # First run: PUBLISHED, not BASELINE.
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                      prior=None, captured=5, build_date="2026-02-11")
    assert row["status"] == "PUBLISHED" and "status flip owed" in row["drift"]
    # Next run with the signature recorded: STILL PUBLISHED, never OK.
    again = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                        prior={"schema": cm.STATE_SCHEMA, "signature": live["signature"],
                               "status": "PUBLISHED"},
                        captured=5, build_date="2026-02-11")
    assert again["status"] == "PUBLISHED"
    # And the overlay must not overwrite it.
    out = cm.version_overlay(dict(again), {"meap_version": "v4", "extracted": "2026-02-11"},
                             {"version": 9, "last_updated": "2026-07-01"})
    assert out["status"] == "PUBLISHED" and "also stale" in out["drift"]


def test_build_month_parses_single_digit_dates():
    live = _live()  # Last updated April 2026
    row = cm.classify("g", "slug", "https://www.manning.com/books/slug", live,
                      prior=None, captured=5, build_date="2026-2-1")
    assert row["status"] == "STALE"  # '2026-02' < '2026-04' after proper padding


def test_all_empty_parse_is_flagged_degraded_not_baseline():
    st = cm.parse_state("<html><body><nav>MEAP</nav>no fields here</body></html>")
    assert st["parse_degraded"] is True
    healthy = cm.parse_state(MEAP_PAGE)
    assert healthy["parse_degraded"] is False
