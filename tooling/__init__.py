"""guides-tooling — shared QA / build / card tooling for the course-guide family.

This package is mounted as a git submodule at ``<host>/tooling/`` inside per-publisher
guide repos (guides-coursera / guides-dlai / guides-manning). It serves the **guide/**
role layout only.

Two roots, resolved in :mod:`tooling.paths`:

- ``package_root()`` — this submodule's own root (``<host>/tooling``); holds the
  tooling-internal data dirs ``latex/``, ``templates/``, ``standards/``, ``config/``.
- ``host_root()`` — the consuming repo root (``<host>``, the parent of the mount);
  where ``guides.yml`` and the ``*/guide/`` guides live.

Tools run as ``python -m tooling.<group>.<tool>``. No ``sys.path`` manipulation.
"""

__version__ = "0.1.0"
