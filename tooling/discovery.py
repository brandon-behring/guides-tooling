"""Fleet discovery over the consuming host repo.

Filesystem-based: every directory carrying a ``guide_qa.yaml`` is a guide. The
walk is **recursive**, so it finds both flat guides (``<slug>/guide_qa.yaml``, as
in the coursera repo) and topic-nested guides (``<topic>/<slug>/guide_qa.yaml``,
as in the dlai/manning repos). The ``tooling/`` mount, ``.git``, and dotdirs are
skipped. (The registry view — slug/title/tier metadata — is :mod:`tooling.scope`.)
"""
from __future__ import annotations

from pathlib import Path

from tooling import paths

# Path components never descended into when looking for guides.
_EXCLUDE = {".git", "tooling"}


def iter_guide_dirs() -> list[Path]:
    """Every guide directory in the host repo (any dir with guide_qa.yaml)."""
    root = paths.host_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for qa in root.rglob("guide_qa.yaml"):
        rel_parents = qa.relative_to(root).parts[:-1]  # dirs above the file
        if any(p in _EXCLUDE or p.startswith(".") for p in rel_parents):
            continue
        out.append(qa.parent)
    return sorted(out)
