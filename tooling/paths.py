"""The single mount-relative path resolver for guides-tooling.

This package is always mounted as a git submodule at ``<host>/tooling/``. So:

- ``package_root()`` → ``<host>/tooling``  (this submodule; tooling-internal data:
  ``latex/`` ``templates/`` ``standards/`` ``config/``).
- ``host_root()``    → ``<host>``          (the consuming repo; ``guides.yml`` and the
  ``*/guide/`` guides live here). Override with ``$GUIDES_HOST_ROOT``.

Every "where is the host repo?" question goes through ``host_root()``; every
"where is a tooling-internal data file?" goes through ``package_root()``. No module
recomputes a root from its own ``__file__``.
"""
from __future__ import annotations

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent   # <host>/tooling/tooling  (this package)
_MOUNT = _PKG_DIR.parent                     # <host>/tooling          (the submodule mount)


def package_root() -> Path:
    """The tooling submodule's own root (holds latex/ templates/ standards/ config/)."""
    return _MOUNT


def host_root() -> Path:
    """The consuming repo root = the parent of the tooling mount.

    ``$GUIDES_HOST_ROOT`` overrides (tests / non-standard checkouts).
    """
    env = os.environ.get("GUIDES_HOST_ROOT")
    return Path(env).resolve() if env else _MOUNT.parent


# ── host-repo paths ──────────────────────────────────────────────────────────
def guides_yml() -> Path:
    return host_root() / "guides.yml"


# ── tooling-internal data paths ──────────────────────────────────────────────
def latex_dir() -> Path:
    return package_root() / "latex"


def templates_dir() -> Path:
    return package_root() / "templates"


def standards_dir() -> Path:
    return package_root() / "standards"


def config_dir() -> Path:
    return package_root() / "config"


def system_design_allowlist() -> Path:
    """Allowlist required by the Silver auditor (degrades silently if missing)."""
    return standards_dir() / "system_design_allowlist.yaml"
