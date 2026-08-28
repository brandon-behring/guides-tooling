"""Compatibility shim: the legacy ``scripts.lib.guide_scope`` API, re-implemented
on tooling primitives so the ported per-guide audits keep their original call
sites with only the import path changed.

Two adaptations are concentrated here:

1. **Flat → topic-nested layout.** ``course_learning`` was flat
   (``repo_root/<slug>``); guides-manning is topic-nested
   (``<topic>/<slug>``, found via :func:`tooling.discovery.iter_guide_dirs`).
   Slug → directory resolution goes through a discovery-built index, never
   ``host_root()/slug``.
2. **One path resolver.** ``guide/``-only artifact paths come from
   :mod:`tooling.layout`; ``chapter_files`` / ``cards_dir`` are re-exported here
   so the old ``from _layout import ...`` call sites repoint as a drop-in.

The Gold runner (T2) decides *which* guides to audit (Silver-PASS only); these
helpers default to the whole fleet.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tooling import discovery, layout, paths, scope

# Re-export the guide/-layout resolvers so modules that used to do
# ``from _layout import chapter_files, cards_dir`` can import them from here.
from tooling.layout import cards_dir, chapter_files  # noqa: F401


@lru_cache(maxsize=1)
def _slug_index() -> dict[str, Path]:
    """slug (directory name) → its actual (possibly topic-nested) guide dir.

    Uniqueness is enforced upstream: :func:`tooling.discovery.iter_guide_dirs`
    raises :class:`tooling.discovery.DuplicateGuideSlug` on a basename collision,
    so this comprehension can never silently keep the last duplicate (DRIVER-1).
    """
    return {d.name: d for d in discovery.iter_guide_dirs()}


def get_repo_root() -> Path:
    """The consuming host repo root (``guides.yml`` + the guide slug dirs)."""
    return paths.host_root()


def guide_dirs() -> list[Path]:
    """Every guide directory in the fleet (topic-nested), filesystem-discovered."""
    return discovery.iter_guide_dirs()


def guide_dir_for_slug(slug: str) -> Optional[Path]:
    """Resolve a slug to its on-disk guide dir, or ``None`` if absent."""
    return _slug_index().get(slug)


@dataclass
class GuideInfo:
    """Registry metadata for one guide + on-disk artifact resolution.

    Mirrors the legacy ``guide_scope.GuideInfo`` surface the audits depend on
    (``slug``, ``los_prefix``, ``resolve_chapters_dir``, ``resolve_cards_dir``,
    ``has_chapters``), but resolves the *nested* dir via discovery rather than
    the old flat ``repo_root/slug`` assumption. ``repo_root`` args are accepted
    for signature compatibility and otherwise ignored.
    """

    slug: str
    title: str
    los_prefix: Optional[str]
    tier: int
    category: str
    chapters: int
    lines: int
    _dir: Optional[Path] = None

    def guide_dir(self) -> Optional[Path]:
        return self._dir if self._dir is not None else guide_dir_for_slug(self.slug)

    def resolve_chapters_dir(self, repo_root: Optional[Path] = None) -> Path:
        d = self.guide_dir()
        if d is None:  # well-formed "missing" path so callers can report it
            return (repo_root or get_repo_root()) / self.slug / "guide" / "chapters"
        return layout.chapters_dir(d)

    def resolve_cards_dir(self, repo_root: Optional[Path] = None) -> Path:
        d = self.guide_dir()
        if d is None:
            return (repo_root or get_repo_root()) / self.slug / "guide" / "cards"
        return layout.cards_dir(d)

    def has_chapters(self, repo_root: Optional[Path] = None) -> bool:
        return self.resolve_chapters_dir(repo_root).is_dir()

    @property
    def chapters_path(self) -> str:
        return "guide/chapters"


def _wrap(g: "scope.GuideInfo") -> GuideInfo:
    return GuideInfo(
        slug=g.slug,
        title=g.title,
        los_prefix=g.los_prefix,
        tier=g.tier,
        category=g.category,
        chapters=g.chapters,
        lines=g.lines,
        _dir=guide_dir_for_slug(g.slug),
    )


def get_all_guides() -> list[GuideInfo]:
    return [_wrap(g) for g in scope.get_all_guides()]


def get_guides_by_tier(tier: int) -> list[GuideInfo]:
    return [g for g in get_all_guides() if g.tier == tier]


def get_tier1_guides() -> list[GuideInfo]:
    """The fleet the per-guide audits default to.

    In the all-Manning fleet, the old "Tier 1 = fully authored (>=1400 lines)"
    notion no longer maps to a ``guides.yml`` tier value (here tier means
    Gold/Silver/Bronze), so the per-guide audits default to the WHOLE fleet; the
    Gold runner (T2) is what restricts a run to Silver-PASS guides.
    """
    return get_all_guides()


def get_guide_by_slug(slug: str) -> Optional[GuideInfo]:
    g = scope.get_guide_by_slug(slug)
    if g is not None:
        return _wrap(g)
    # On disk but absent from guides.yml → still auditable.
    d = guide_dir_for_slug(slug)
    if d is not None:
        return GuideInfo(
            slug=slug, title=slug, los_prefix=None, tier=3,
            category="other", chapters=0, lines=0, _dir=d,
        )
    return None


def get_guide_slugs(tier: Optional[int] = None) -> list[str]:
    return scope.get_guide_slugs(tier)


def resolve_guide_name(fuzzy_name: str) -> Optional[str]:
    return scope.resolve_guide_name(fuzzy_name)
