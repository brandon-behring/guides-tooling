#!/usr/bin/env python3
r"""Repair drifted ``guide_qa.yaml`` metric/readiness check commands fleet-wide.

Import-era drift left two broken command families in every consuming guide's
``guide_qa.yaml``:

* ``page_count`` calls macOS ``mdls`` (returns null on freshly-built PDFs in CI
  / non-Spotlight contexts) instead of ``pdfinfo``.
* ``latex_overflow_visible`` (a metric) **and** the ``check_refs`` /
  ``extract_los`` / ``check_latex_warnings`` readiness checks invoke a validator
  by an absolute ``~/Claude/lever_of_archimedes/...`` path or a missing local
  ``scripts/validation/...`` path, instead of the canonical in-repo
  ``python -m tooling.validation.*`` module.

This rewrites **only** those five command lines, in place, via targeted
line replacement — every other line (targets, yellow, anki, comments,
formatting) is left byte-identical. Each guide's own PDF/log artifact
(``main`` vs ``main_digital``) is preserved. The new commands are rendered
through ``yaml.dump`` so escaping is always correct, and each rewritten file is
re-parsed to assert the five commands decode to the intended shell strings.

Run from the consuming host repo root::

    python -m tooling.generate.fix_qa_check_cmds --dry-run   # unified diffs, no writes
    python -m tooling.generate.fix_qa_check_cmds             # apply
    python -m tooling.generate.fix_qa_check_cmds --check     # CI: exit 1 if any drift remains

Idempotent: re-running after a successful apply is a no-op.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from pathlib import Path

import yaml

from tooling import discovery, paths

# ── Canonical command templates (real shell strings; {…} filled per guide) ──

# Robust page count: prefer the multi-pass main_digital.pdf, else main.pdf (mirrors
# scripts/fleet/aggregate.py:pdf_pages); pdfinfo primary, mdls fallback per file.
# Trying both PDFs is what makes it resilient: a guide whose page_count was set to
# main_digital.pdf but only has a pilot-built main.pdf still reports a real count
# instead of 'unknown' (the bug that false-RED'd 9 guides on G6).
PAGE_TMPL = (
    "python3 -c \"import subprocess,re,pathlib,shutil; ex=shutil.which('pdfinfo'); "
    "g=lambda f: (re.search(r'Pages:\\s*(\\d+)',subprocess.run(['pdfinfo',f],capture_output=True,text=True).stdout) "
    "if ex else re.search(r'=\\s*(\\d+)',subprocess.run(['mdls','-name','kMDItemNumberOfPages',f],capture_output=True,text=True).stdout)); "
    "v=next((m.group(1) for f in ('guide/main_digital.pdf','guide/main.pdf') if pathlib.Path(f).exists() and (m:=g(f))), 'unknown'); "
    "print(v)\""
)
# Overflow metric: canonical tooling validator + the CORRECT json key (overfull_50pt).
OVERFLOW_TMPL = (
    "PYTHONPATH={rel} python3 -m tooling.validation.check_latex_warnings {log} --json 2>/dev/null "
    "| python3 -c \"import sys,json; print(json.load(sys.stdin).get('overfull_50pt',0))\""
)
REFS_TMPL = "PYTHONPATH={rel} python3 -m tooling.validation.check_refs guide/chapters/*.tex guide/appendices/*.tex"
LOS_TMPL = "PYTHONPATH={rel} python3 -m tooling.validation.extract_los guide/chapters/*.tex --validate"
PRES_TMPL = "PYTHONPATH={rel} python3 -m tooling.validation.check_latex_warnings {log} --threshold-red 5"

_LOG_RE = re.compile(r"main(?:_digital)?\.log")


def _emit(key: str, shell: str, indent: int) -> str:
    """Render ``<indent><key>: "<shell>"`` as a YAML double-quoted scalar.

    Escapes backslash then double-quote (order matters) so the file matches the
    repo's existing double-quoted check_cmd style and round-trips exactly
    (e.g. a regex ``\\s`` is written ``\\\\s`` and parses back to ``\\s``).
    """
    esc = shell.replace("\\", "\\\\").replace('"', '\\"')
    return f'{" " * indent}{key}: "{esc}"'


def _log_path(old: str) -> str:
    m = _LOG_RE.search(old)
    return "guide/" + (m.group(0) if m else "main.log")


def rewrite(text: str, rel: str) -> tuple[str, bool]:
    """Return (new_text, changed). Replaces only the five drifted command lines."""
    out: list[str] = []
    section: str | None = None
    metric: str | None = None
    changed = False

    for line in text.split("\n"):
        top = re.match(r"^([A-Za-z][\w-]*):", line)
        if top:
            section = top.group(1)
            metric = None
        elif section == "metrics":
            mm = re.match(r"^  ([A-Za-z_]+):\s*$", line)
            if mm:
                metric = mm.group(1)

        new = line
        if section == "metrics" and re.match(r"^    check_cmd:", line):
            if metric == "page_count":
                new = _emit("check_cmd", PAGE_TMPL, 4)
            elif metric == "latex_overflow_visible":
                new = _emit("check_cmd", OVERFLOW_TMPL.format(rel=rel, log=_log_path(line)), 4)
        elif section == "readiness_checks" and re.match(r"^    cmd:", line):
            if "check_refs" in line:
                new = _emit("cmd", REFS_TMPL.format(rel=rel), 4)
            elif "extract_los" in line:
                new = _emit("cmd", LOS_TMPL.format(rel=rel), 4)
            elif "check_latex_warnings" in line:
                new = _emit("cmd", PRES_TMPL.format(rel=rel, log=_log_path(line)), 4)

        if new != line:
            changed = True
        out.append(new)

    return "\n".join(out), changed


def _verify(new_text: str, rel: str) -> None:
    """Re-parse the rewritten YAML and assert the COMMAND VALUES decode as intended.

    Checks parsed command strings only (comments mentioning 'mdls fallback' etc.
    are irrelevant).
    """
    cfg = yaml.safe_load(new_text)  # raises on malformed YAML
    metrics = cfg.get("metrics") or {}
    pc = (metrics.get("page_count") or {}).get("check_cmd")
    if pc is not None:
        assert "pdfinfo" in pc, "page_count not repaired (no pdfinfo)"
        assert "main_digital.pdf" in pc and "guide/main.pdf" in pc, \
            "page_count must try both main_digital.pdf and main.pdf"
    ov = (metrics.get("latex_overflow_visible") or {}).get("check_cmd")
    if ov is not None:
        assert "tooling.validation.check_latex_warnings" in ov and "overfull_50pt" in ov, "overflow not repaired"

    cmds = [m.get("check_cmd", "") for m in metrics.values()]
    cmds += [c.get("cmd", "") for c in (cfg.get("readiness_checks") or [])]
    for c in cmds:
        assert "~/Claude" not in c, f"stray ~/Claude path: {c}"
        assert "scripts/validation/" not in c, f"stray local scripts/validation path: {c}"
        if "mdls" in c:
            assert c == pc, f"stray mdls outside page_count fallback: {c}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="show unified diffs, write nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 if any guide still has drift (no writes)")
    args = ap.parse_args()

    tooling_mount = paths.host_root() / "tooling"
    changed_files = 0
    for guide_dir in discovery.iter_guide_dirs():
        qa = guide_dir / "guide_qa.yaml"
        if not qa.exists():
            continue
        rel = os.path.relpath(tooling_mount, guide_dir)
        old = qa.read_text(encoding="utf-8")
        new, changed = rewrite(old, rel)
        if not changed:
            continue
        changed_files += 1
        _verify(new, rel)
        label = qa.relative_to(paths.host_root())
        if args.check:
            print(f"  DRIFT  {label}")
        elif args.dry_run:
            diff = difflib.unified_diff(
                old.splitlines(), new.splitlines(), f"a/{label}", f"b/{label}", lineterm=""
            )
            print("\n".join(diff))
        else:
            qa.write_text(new, encoding="utf-8")
            print(f"  FIXED  {label}")

    verb = "have drift" if args.check else ("would change" if args.dry_run else "fixed")
    print(f"\n{changed_files} guide_qa.yaml {verb}.")
    if args.check and changed_files:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
