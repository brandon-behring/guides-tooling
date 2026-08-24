"""warn_audit_error must never raise (Codex finding C3).

It is a degradation-path reporter: if it raised, it would replace the very
error it exists to surface. A broken ``__str__`` or a closed stderr must be
swallowed here.
"""

import io

from tooling._fail_loud import warn_audit_error


class _ExplodingStr(Exception):
    def __str__(self):
        raise RuntimeError("secondary formatting failure")


def test_normal_exception_prints_greppable_line(capsys):
    warn_audit_error("audit_x", "path/to/f.tex", ValueError("boom"))
    err = capsys.readouterr().err
    assert err.startswith("[audit-error] audit_x: ValueError on path/to/f.tex: boom")


def test_exception_with_broken_str_does_not_raise(capsys):
    # Must not raise, and must not lose the [audit-error] marker.
    warn_audit_error("audit_x", "f.tex", _ExplodingStr())
    err = capsys.readouterr().err
    assert "[audit-error] audit_x" in err
    assert "unprintable exception" in err


def test_closed_stderr_is_swallowed(monkeypatch):
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr("sys.stderr", closed)
    # Writing to a closed stream raises ValueError; warn_audit_error must absorb it.
    warn_audit_error("audit_x", "f.tex", ValueError("boom"))
