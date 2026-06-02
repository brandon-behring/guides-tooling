"""guide/ role-layout artifact paths for a single guide directory.

guide/-ONLY: this package serves the migrated role layout, so there is no
``notes/notebook/`` fallback (that dual-layout code lived in the monorepo during
the R-layout migration and is intentionally dropped here).

Each resolver takes the guide's top-level dir (e.g. ``<host>/manning_rlhf_book``)
and returns the artifact path under ``guide/`` (or the sibling ``review/``).
"""
from __future__ import annotations

from pathlib import Path


def guide_root(guide_dir: Path) -> Path:
    return guide_dir / "guide"


def makefile(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "Makefile"


def chapters_dir(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "chapters"


def chapter_files(guide_dir: Path) -> list[Path]:
    """Sorted authored chapter .tex files (excludes 00_* by caller if needed)."""
    return sorted(chapters_dir(guide_dir).glob("*.tex"))


def appendices_dir(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "appendices"


def appendix_d(guide_dir: Path) -> Path:
    """Interview-prep appendix D (prefer ``_prep``, else ``_practice``)."""
    ap = appendices_dir(guide_dir)
    prep = ap / "D_interview_prep.tex"
    return prep if prep.exists() else ap / "D_interview_practice.tex"


def cards_dir(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "cards"


def cards_yaml(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "cards" / "all_cards.yml"


def decks_dir(guide_dir: Path) -> Path:
    return guide_dir / "guide" / "decks"


# ── review/ (QA + research metadata; sibling of guide/) ──────────────────────
def review_dir(guide_dir: Path) -> Path:
    return guide_dir / "review"


def dashboard(guide_dir: Path) -> Path:
    return guide_dir / "review" / "dashboard.md"


def source_manifest(guide_dir: Path) -> Path:
    return guide_dir / "review" / "source_manifest.md"


def ic_md(guide_dir: Path) -> Path:
    return guide_dir / "review" / "interview_connections.md"
