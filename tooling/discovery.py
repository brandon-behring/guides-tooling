"""Fleet discovery over the consuming host repo.

Filesystem-based: every top-level dir in ``host_root()`` carrying a ``guide_qa.yaml``
is a guide. (The registry view — slug/title/tier metadata — is :mod:`tooling.scope`.)
"""
from __future__ import annotations

from pathlib import Path

from tooling import paths


def iter_guide_dirs() -> list[Path]:
    """Every guide directory in the host repo (top-level dir with guide_qa.yaml)."""
    root = paths.host_root()
    if not root.is_dir():
        return []
    return sorted(
        d for d in root.iterdir()
        if d.is_dir() and (d / "guide_qa.yaml").exists()
    )
