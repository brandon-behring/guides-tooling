"""The guide -> liveBook slug map behind check_meap_freshness.resolve_slug.

Every slug must be well formed, and no two guides may resolve to the same book:
a collision makes one guide's freshness and cache rows silently report the other's.
"""

import re

from tooling.audits.fleet import check_meap_freshness as F

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _effective() -> dict[str, str]:
    return {k: F.resolve_slug(k, None) for k in set(F.SLUG_OVERRIDES) | set(F.LIVEBOOK_SLUGS)}


def test_slugs_are_well_formed():
    bad = {k: v for k, v in {**F.LIVEBOOK_SLUGS, **F.SLUG_OVERRIDES}.items() if not SLUG.match(v)}
    assert not bad


def test_no_two_guides_share_a_book():
    seen: dict[str, str] = {}
    dupes = []
    for k, v in sorted(_effective().items()):
        if v in seen:
            dupes.append((seen[v], k, v))
        seen[v] = k
    assert not dupes


def test_override_wins_and_hand_manifest_wins_over_both():
    assert F.resolve_slug("cuda_deep_learning", None) == "cuda-for-llms"
    assert F.resolve_slug("cuda_deep_learning", {"livebook_slug": "hand-set"}) == "hand-set"
    bootstrap = {"livebook_slug": "stale-slug", "_generated_by": "checker (minimal bootstrap)"}
    assert F.resolve_slug("cuda_deep_learning", bootstrap) == "cuda-for-llms"


def test_book_without_a_livebook_edition_is_unresolved():
    assert F.resolve_slug("grokking_deep_learning", None) is None
