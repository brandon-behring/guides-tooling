"""Fleet discovery over the consuming host repo.

Filesystem-based: every directory carrying a ``guide_qa.yaml`` is a guide. The
walk is **recursive**, so it finds both flat guides (``<slug>/guide_qa.yaml``, as
in the coursera repo) and topic-nested guides (``<topic>/<slug>/guide_qa.yaml``,
as in the dlai/manning repos). (The registry view — slug/title/tier metadata — is
:mod:`tooling.scope`.)

Two guards, both from the 2026-08-28 r2 review (DRIVER-1, gt#33):

1. **Non-guide trees are never walked.** ``_EXCLUDE`` names the top-level (and
   nested) directories that can legitimately hold a copy of a guide — ``reports/``
   above all: 36 rsync scratch copies under ``reports/_scratch/`` were discovered
   as guides on 2026-08-27 and, because slug resolution kept the *last* duplicate,
   16 of 18 ``--guide`` audits silently read the artifact-less copy. When the
   host carries a registry (``guides.yml`` with ``topic:`` fields), a nested guide
   is additionally accepted only under a registered topic dir; a flat guide is
   always accepted, and a host without a registry falls back to ``_EXCLUDE`` alone.
2. **A duplicate slug raises** :class:`DuplicateGuideSlug` instead of letting one
   copy shadow the other: every audit, report row and ``--guide`` flag resolves
   on the basename, so two dirs with one name is a fleet-level error, not a
   tie to break.
"""
from __future__ import annotations

from pathlib import Path

from tooling import paths

# Path components never descended into when looking for guides. Beyond the mount
# and VCS dirs: every non-guide top-level tree of the known hosts (reports/ for
# review scratch copies, scripts/, docs/, templates/, shared/, _archived/) and the
# curriculum / reading-list folders that are not course guides. Dotdirs are
# skipped by rule (see iter_guide_dirs).
_EXCLUDE = {
    ".git",
    "tooling",
    "reports",
    "scripts",
    "docs",
    "templates",
    "shared",
    "_archived",
    "manning_curriculum",
}


class DuplicateGuideSlug(ValueError):
    """Two discovered guide directories share a basename (slug)."""


def _registry() -> tuple[frozenset[str], dict[str, str]] | None:
    """``(topic names, {slug: its topic})`` from the host's ``guides.yml``.

    ``None`` when the host carries no registry, which drops the allowlist and
    leaves ``_EXCLUDE`` as the only filter.
    """
    from tooling import scope  # local: scope imports only layout/paths, no cycle

    try:
        guides = scope.get_all_guides()
    except FileNotFoundError:
        return None
    return (frozenset(g.topic for g in guides if g.topic),
            {g.slug: g.topic for g in guides if g.topic})


def iter_guide_dirs() -> list[Path]:
    """Every guide directory in the host repo (any dir with guide_qa.yaml), sorted.

    Raises
    ------
    DuplicateGuideSlug
        When two discovered directories share a basename.
    """
    root = paths.host_root()
    if not root.is_dir():
        return []
    reg = _registry()
    seen: dict[str, Path] = {}
    for qa in sorted(root.rglob("guide_qa.yaml")):
        rel_parents = qa.relative_to(root).parts[:-1]  # dirs above the file
        if any(p in _EXCLUDE or p.startswith(".") for p in rel_parents):
            continue
        if reg is not None and len(rel_parents) >= 2:
            topics, topic_of = reg
            expected = topic_of.get(rel_parents[-1])
            if expected is not None:
                # A REGISTERED slug must sit under its own registered topic; a copy
                # under someone else's topic is not the guide (review of #35). The
                # registry-vs-disk guard then reports it as missing, loudly.
                if rel_parents[0] != expected:
                    continue
            elif topics and rel_parents[0] not in topics:
                continue  # unregistered slug under a dir the registry does not know
        d = qa.parent
        if d.name in seen:
            raise DuplicateGuideSlug(
                f"duplicate guide slug {d.name!r}: {seen[d.name].relative_to(root)} and "
                f"{d.relative_to(root)} -- guide dirs must be unique by basename (audits, "
                "report rows and --guide all resolve on it; the later copy used to win silently)"
            )
        seen[d.name] = d
    return sorted(seen.values())
