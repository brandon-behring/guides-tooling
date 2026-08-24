"""Vetted execution for guide_qa.yaml check commands.

`guide_health.run_metric_check` and `guide_readiness.run_readiness_check` run
command strings taken from a repo's ``guide_qa.yaml`` through the shell (the
fleet's commands genuinely need pipes, ``||`` fallback chains, ``2>/dev/null``,
``NAME=value`` prefixes, globs, and ``;`` sequencing — list-form execution
cannot express them). This module bounds what that shell invocation can do.

Threat model: ``guide_qa.yaml`` is repo-controlled, the same trust level as a
Makefile — a reviewer can see a ``python3 -c "…"`` payload plainly, and such
payloads stay arbitrary code by design. What vetting removes is *shell-syntax*
injection smuggled into an otherwise innocuous-looking command on an untrusted
branch: command substitution, backticks, background ``&``, redirects to files,
here-docs, and pipeline heads outside a small executable allowlist.

Rules enforced by :func:`vet_check_cmd`:

- backticks are refused anywhere; ``$`` is refused outside single quotes
  (double quotes do not stop the shell from expanding either);
- outside quotes, ``& < ( ) ~ #`` and newlines are refused; ``>`` is allowed
  only as the exact redirect ``2>/dev/null`` / ``>/dev/null``;
- the command splits on unquoted ``|`` / ``;`` into segments; after optional
  ``NAME=value`` assignments, each segment's head executable must be in
  :data:`ALLOWED_EXECUTABLES`.
"""

from __future__ import annotations

import re
import shlex
import subprocess

#: Pipeline-head executables the fleet's check commands actually use.
ALLOWED_EXECUTABLES = frozenset(
    {"grep", "awk", "python3", "wc", "echo", "make", "test", "pdfinfo", "mdls"}
)

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# The lookahead pins the target: `2>/dev/nullX` must not pass as a prefix match.
_REDIRECT_RE = re.compile(r"2?>/dev/null(?=[\s|;]|$)")

#: Characters refused in unquoted text (beyond the specially-handled > | ;).
_FORBIDDEN_UNQUOTED = frozenset("&<()~#\n\r")


class UnvettedCommandError(RuntimeError):
    """A check command failed vetting and was not executed."""


def _spans(cmd: str):
    """Yield (context, char, index) with context in {"plain", "single", "double"}.

    Tracks POSIX quoting: backslash escapes the next char outside quotes and
    inside double quotes; inside single quotes everything is literal. Raises
    UnvettedCommandError on an unterminated quote or trailing backslash.
    """
    ctx = "plain"
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ctx == "plain":
            if ch == "\\":
                if i + 1 >= n:
                    raise UnvettedCommandError("trailing backslash")
                i += 2
                continue
            if ch == "'":
                ctx = "single"
            elif ch == '"':
                ctx = "double"
            else:
                yield ctx, ch, i
        elif ctx == "single":
            if ch == "'":
                ctx = "plain"
            else:
                yield ctx, ch, i
        else:  # double
            if ch == "\\":
                if i + 1 >= n:
                    raise UnvettedCommandError("trailing backslash")
                yield ctx, cmd[i + 1], i + 1
                i += 2
                continue
            if ch == '"':
                ctx = "plain"
            else:
                yield ctx, ch, i
        i += 1
    if ctx != "plain":
        raise UnvettedCommandError("unterminated quote")


def vet_check_cmd(cmd: str) -> str | None:
    """Return None when *cmd* is safe to run through the shell, else a reason.

    Never raises for ordinary rejections — parse problems (unterminated
    quotes) are folded into the returned reason string.
    """
    if not cmd or not cmd.strip():
        return "empty command"
    if "`" in cmd:
        return "backtick"

    segments: list[list[int]] = [[]]  # unquoted char indices per segment
    try:
        for ctx, ch, i in _spans(cmd):
            if ctx == "single":
                continue
            if ch == "$":
                return "'$' outside single quotes (shell would expand it)"
            if ctx == "double":
                continue
            if ch in _FORBIDDEN_UNQUOTED:
                return f"forbidden shell character {ch!r}"
            if ch == ">":
                # Only the literal 2>/dev/null or >/dev/null redirect.
                start = i - 1 if i > 0 and cmd[i - 1] == "2" else i
                if not _REDIRECT_RE.match(cmd, start):
                    return "redirect other than [2]>/dev/null"
                continue
            if ch in "|;":
                segments.append([])
                continue
            segments[-1].append(i)
    except UnvettedCommandError as exc:
        return str(exc)

    seen_head = False
    for seg_indices in segments:
        segment = _segment_text(cmd, seg_indices)
        if not segment.strip():
            continue  # the empty span inside "||"
        reason = _vet_segment_head(segment)
        if reason:
            return reason
        seen_head = True
    if not seen_head:
        return "no command found"
    return None


def _segment_text(cmd: str, indices: list[int]) -> str:
    """Rebuild a segment from the original string, spanning min..max index.

    Using the original span (not just unquoted chars) keeps quoted arguments
    intact for shlex tokenization below.
    """
    if not indices:
        return ""
    return cmd[indices[0] : indices[-1] + 1]


def _vet_segment_head(segment: str) -> str | None:
    """Check one pipeline/sequence segment's head executable."""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError as exc:
        return f"unparseable segment: {exc}"
    for tok in tokens:
        if _ASSIGNMENT_RE.match(tok):
            continue  # NAME=value prefix; its value already passed the char scan
        if tok in ALLOWED_EXECUTABLES:
            return None
        return f"executable {tok!r} not in the check-command allowlist"
    return "segment has no executable"


def run_vetted(
    cmd: str, *, cwd: str, timeout: int
) -> subprocess.CompletedProcess:
    """Vet *cmd*, then run it through the shell exactly as before.

    Raises UnvettedCommandError instead of executing when vetting fails.
    """
    reason = vet_check_cmd(cmd)
    if reason is not None:
        raise UnvettedCommandError(f"{reason} in: {cmd}")
    return subprocess.run(
        cmd,
        shell=True,  # noqa: S602 — vetted above; fleet commands need shell syntax
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )
