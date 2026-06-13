"""Guide registry — the slug/title/tier view from the host repo's ``guides.yml``.

Filesystem artifact paths live in :mod:`tooling.layout`; fleet discovery in
:mod:`tooling.discovery`. ``GuideInfo`` carries only registry metadata + a
``guide_dir()`` anchor (everything path-shaped delegates to ``layout``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from tooling import layout, paths


@dataclass(frozen=True)
class GuideInfo:
    slug: str
    title: str
    los_prefix: Optional[str]
    tier: int
    category: str
    chapters: int
    lines: int
    status: str = ""  # publication status from guides.yml ("published" | "meap" | "")

    def guide_dir(self) -> Path:
        return paths.host_root() / self.slug

    def chapter_files(self) -> list[Path]:
        return layout.chapter_files(self.guide_dir())

    def cards_yaml(self) -> Path:
        return layout.cards_yaml(self.guide_dir())


def _load_raw() -> dict:
    p = paths.guides_yml()
    if not p.exists():
        raise FileNotFoundError(
            f"guides.yml not found at {p} (host_root={paths.host_root()}). "
            "Set $GUIDES_HOST_ROOT or run from the consuming repo."
        )
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_all_guides() -> list[GuideInfo]:
    out: list[GuideInfo] = []
    for g in _load_raw().get("guides", []):
        if g.get("archived", False):
            continue
        out.append(
            GuideInfo(
                slug=g["slug"],
                title=g.get("title", g["slug"]),
                los_prefix=g.get("los_prefix"),
                tier=g.get("tier", 3),
                category=g.get("category", "other"),
                chapters=g.get("chapters", 0),
                lines=g.get("lines", 0),
                status=g.get("status", ""),
            )
        )
    return out


def get_guides_by_tier(tier: int) -> list[GuideInfo]:
    return [g for g in get_all_guides() if g.tier == tier]


def get_guide_by_slug(slug: str) -> Optional[GuideInfo]:
    return next((g for g in get_all_guides() if g.slug == slug), None)


def get_guide_slugs(tier: Optional[int] = None) -> list[str]:
    guides = get_all_guides()
    if tier is not None:
        guides = [g for g in guides if g.tier == tier]
    return sorted(g.slug for g in guides)


def resolve_guide_name(fuzzy_name: str) -> Optional[str]:
    """Resolve a fuzzy name to a slug (exact slug → substring slug → title substring)."""
    fuzzy = fuzzy_name.lower().replace("-", "_").replace(" ", "_")
    guides = get_all_guides()
    for g in guides:
        if g.slug == fuzzy:
            return g.slug
    for g in guides:
        if fuzzy in g.slug:
            return g.slug
    title_q = fuzzy_name.lower()
    for g in guides:
        if title_q in g.title.lower():
            return g.slug
    return None
