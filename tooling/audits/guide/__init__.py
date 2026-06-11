"""Per-guide audit suite (Gold G1–G2).

Eleven ``audit_*`` scripts ported from the legacy ``course_learning`` monorepo onto
the ``tooling.*`` package. Each runs against a single guide (``--guide <slug>``) or
the whole fleet; the Gold runner (roadmap T2) orchestrates them.

Path/registry adaptation is centralised in :mod:`._guide_scope` (the compatibility
shim that re-implements the old ``scripts.lib.guide_scope`` API on
``tooling.discovery`` / ``tooling.scope`` / ``tooling.layout`` / ``tooling.paths``).
"""
