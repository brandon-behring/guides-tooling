"""Shared fail-loud reporting for scan/parse errors in audits and tooling.

The fleet's audits scan hundreds of files; one unreadable or malformed file
must not abort a sweep, but it must never disappear silently either — a
skipped chapter makes G1/G2/G4/G6 pass over content they never saw, and
retrieval coverage can read 100% while a defective chapter is excluded.

Every handler that degrades (skip a file, fall back to a default) calls
:func:`warn_audit_error` so the failure is visible on stderr in a stable,
greppable format. Modules whose result type has an error channel (issues
list, error field, status tuple) should surface the failure there as well.
"""

from __future__ import annotations

import sys
from pathlib import Path


def warn_audit_error(module: str, path: Path | str, exc: Exception) -> None:
    """Print a standardized ``[audit-error]`` line to stderr.

    ``module`` names the audit (e.g. ``"audit_crossref_quality"``) so fleet
    logs can be grepped per audit; ``path`` is the file that failed.

    This is a degradation-path reporter, so it must NEVER raise and mask the
    original failure: a custom exception whose ``__str__`` raises, or a closed
    stderr, is swallowed here rather than replacing the error it describes.
    """
    try:
        detail = str(exc)
    except Exception:  # noqa: BLE001 — a broken __str__ must not eat the real error
        detail = "<unprintable exception>"
    try:
        print(
            f"[audit-error] {module}: {type(exc).__name__} on {path}: {detail}",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 — broken/closed stderr must not abort the scan
        pass


def read_text_or_warn(
    module: str, path: Path, *, encoding: str = "utf-8", errors: str = "ignore"
) -> str | None:
    """Read *path* as text, or warn via :func:`warn_audit_error` and return ``None``.

    The fail-loud replacement for the ``except OSError: continue`` idiom (gt#33 row 8):
    a caller that gets ``None`` must record the path as *unreadable* in its result (so
    the gate FAILs) rather than skip it as if the file did not exist.

    Parameters
    ----------
    module : str
        Audit name for the ``[audit-error]`` line, e.g. ``"audit_gold.G1"``.
    path : Path
        The file to read.
    encoding, errors : str
        Passed to :meth:`pathlib.Path.read_text`.
    """
    try:
        return path.read_text(encoding=encoding, errors=errors)
    except OSError as exc:
        warn_audit_error(module, path, exc)
        return None
