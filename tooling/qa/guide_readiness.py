#!/usr/bin/env python3
"""
Config-driven readiness checker for LaTeX course guides.

Reads readiness checks from guide_qa.yaml, runs each command, and reports
blocking vs warning issues. Generates a markdown readiness report.

Exit codes:
    0 — All checks pass (ready)
    1 — Blocking failures (not ready)
    2 — Warnings only (proceed with caution)

Usage:
    python guide_readiness.py --config guide_qa.yaml
    python guide_readiness.py                          # auto-find config
    python guide_readiness.py --skip-build             # skip build checks
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Import config loader (dual path: script vs package execution)
try:
    from _check_exec import UnvettedCommandError, run_vetted
    from guide_qa_config import GuideConfig, ReadinessCheck, load_config
except ImportError:
    from ._check_exec import UnvettedCommandError, run_vetted
    from .guide_qa_config import GuideConfig, ReadinessCheck, load_config

# lualatex recovers from many real errors and still emits a PDF, so a build check
# that only runs "test -f main.pdf" passes despite them. Scan the build log too.
#
# Match BOTH error renderings: a column-0 ``! `` line (TeX-native) and any
# ``file:line: `` message (the ``file:line:error`` style these guides compile
# with). The earlier keyword-restricted form silently missed "Misplaced
# alignment tab character &." (a raw-``&`` bib breaker) because that phrase was
# not in the keyword list -- so match any ``.tex:<n>: `` prefix instead.
# The file:line arm anchors the PATH at the start of the line (not ``.*`` before
# it) so a benign typeout/Info line that merely embeds a ``foo.tex:NN:`` location
# (e.g. ``Package x Info: chapters/01.tex:12: ...``) is NOT matched — only a true
# ``file:line:error``-style line, which lualatex emits starting with the path.
# ``^\s*`` allows an indented error line; the path arm still anchors at the path
# (after optional leading space) so a benign ``Package x Info: foo.tex:12:`` (text
# before the path) does not match. Validated: 0 false positives on clean logs.
_LATEX_ERROR_RE = re.compile(r"(?m)^\s*(?:\! .*|[^\s:]*\.tex:\d+: .*)$")


@dataclass
class CheckResult:
    """Result of a single readiness check."""

    name: str
    passed: bool
    blocking: bool
    output: str
    error: str | None = None


@dataclass
class ReadinessReport:
    """Aggregate readiness report."""

    guide_name: str
    version: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed and r.blocking]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed and not r.blocking]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.passed]

    @property
    def is_ready(self) -> bool:
        return len(self.blocking_failures) == 0

    @property
    def exit_code(self) -> int:
        if self.blocking_failures:
            return 1
        if self.warnings:
            return 2
        return 0


def run_readiness_check(check: ReadinessCheck, config: GuideConfig) -> CheckResult:
    """Run a single readiness check command.

    A check passes if the command exits with code 0. Commands run through the
    shell after ``_check_exec`` vetting (fleet commands need globs, ``;``
    sequencing, and env prefixes); an unvetted command fails its check without
    executing.
    """
    try:
        result = run_vetted(
            check.cmd,
            cwd=str(config.config_path.parent),
            timeout=120,  # Build checks can be slow
        )

        passed = result.returncode == 0
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\n[stderr] {result.stderr.strip()}"

        # A build check that produced a PDF can still hide LaTeX errors that lualatex
        # recovered from. For build/compile checks, scan the build log and fail on them.
        if passed and any(k in check.name.lower() for k in ("build", "compile")):
            guide_dir = getattr(config, "guide_dir", "guide") or "guide"
            log_path = config.config_path.parent / guide_dir / "main.log"
            if log_path.exists():
                errs = _LATEX_ERROR_RE.findall(log_path.read_text(errors="replace"))
                if errs:
                    passed = False
                    output += (
                        f"\n[build-log] {len(errs)} LaTeX error(s) despite a PDF:\n"
                        + "\n".join(errs[:8])
                    )

        return CheckResult(
            name=check.name,
            passed=passed,
            blocking=check.blocking,
            output=output,
        )

    except UnvettedCommandError as e:
        return CheckResult(
            name=check.name,
            passed=False,
            blocking=check.blocking,
            output="",
            error=f"Refused unvetted check command: {e}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=check.name,
            passed=False,
            blocking=check.blocking,
            output="",
            error="Timeout after 120 seconds",
        )
    except Exception as e:
        return CheckResult(
            name=check.name,
            passed=False,
            blocking=check.blocking,
            output="",
            error=str(e),
        )


def evaluate_readiness(
    config: GuideConfig,
    skip_build: bool = False,
) -> ReadinessReport:
    """Run all readiness checks and build report."""
    report = ReadinessReport(guide_name=config.name, version=config.version)

    for check_def in config.readiness_checks:
        # Skip build-related checks if requested
        if skip_build and ("build" in check_def.name.lower() or "compile" in check_def.name.lower()):
            print(f"  [SKIP] {check_def.name}")
            continue

        print(f"  Running: {check_def.name}...", end=" ", flush=True)
        result = run_readiness_check(check_def, config)
        status = "PASS" if result.passed else ("BLOCK" if result.blocking else "WARN")
        print(status)

        report.results.append(result)

    return report


def generate_readiness_report(report: ReadinessReport) -> str:
    """Generate markdown readiness report."""
    lines = [
        f"# Readiness Report: {report.guide_name} v{report.version}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
    ]

    # Verdict
    if report.is_ready:
        if report.warnings:
            lines.append("**READY** (with warnings)")
        else:
            lines.append("**READY** (all checks pass)")
    else:
        lines.append("**NOT READY** (blocking failures)")

    lines.extend(["", "## Checklist", ""])

    # All checks as checklist
    for r in report.results:
        check = "[x]" if r.passed else "[ ]"
        tag = ""
        if not r.passed:
            tag = " **[BLOCKING]**" if r.blocking else " *[warning]*"
        lines.append(f"- {check} {r.name}{tag}")

    # Blocking failures detail
    if report.blocking_failures:
        lines.extend(["", "## Blocking Failures", ""])
        for r in report.blocking_failures:
            lines.append(f"### {r.name}")
            if r.error:
                lines.append(f"Error: {r.error}")
            if r.output:
                # Truncate long output
                output = r.output[:500]
                if len(r.output) > 500:
                    output += "\n... (truncated)"
                lines.append(f"```\n{output}\n```")
            lines.append("")

    # Warnings detail
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        for r in report.warnings:
            lines.append(f"### {r.name}")
            if r.error:
                lines.append(f"Error: {r.error}")
            if r.output:
                output = r.output[:300]
                if len(r.output) > 300:
                    output += "\n... (truncated)"
                lines.append(f"```\n{output}\n```")
            lines.append("")

    # Remediation hints
    if not report.is_ready:
        lines.extend([
            "## Remediation",
            "",
            "Fix blocking failures before proceeding:",
        ])
        for r in report.blocking_failures:
            lines.append(f"- **{r.name}**: Check output above, fix, re-run")
        lines.append("")

    return "\n".join(lines) + "\n"


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Guide readiness checker")
    parser.add_argument("--config", help="Path to guide_qa.yaml (auto-search if omitted)")
    parser.add_argument("--skip-build", action="store_true", help="Skip LaTeX build checks")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Readiness: {config.name} v{config.version}")
    print(f"Config: {config.config_path}\n")

    report = evaluate_readiness(config, skip_build=args.skip_build)

    # Generate report
    md = generate_readiness_report(report)
    print()
    print(md)

    # Save report
    config.review_dir.mkdir(parents=True, exist_ok=True)
    safe_name = config.name.lower().replace(" ", "_")
    report_path = config.review_dir / f"readiness-{safe_name}.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"Report saved: {report_path}")

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
