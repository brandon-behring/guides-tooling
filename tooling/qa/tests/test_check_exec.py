"""Tests for the check-command vetting layer (`tooling.qa._check_exec`).

FLEET_COMMANDS below is the complete set of distinct `check_cmd` /
`readiness_checks[].cmd` strings across all 84 guide_qa.yaml files in the
guides-manning fleet, captured verbatim 2026-08-24. Every one must vet clean:
a vetting change that rejects any of them would break a live guide.
"""

import subprocess

import pytest

from tooling.qa._check_exec import (
    ALLOWED_EXECUTABLES,
    UnvettedCommandError,
    run_vetted,
    vet_check_cmd,
)

FLEET_COMMANDS = [
    # used by 84 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -c '^@' guide/references.bib",
    # used by 83 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -rc '\\\\los{' guide/chapters/ | awk -F: '{s+=$2}END{print s}'",
    # used by 75 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -c '\\\\term\\[' guide/appendices/C_glossary.tex",
    # used by 74 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.check_latex_warnings guide/main.log --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get(\'overfull_50pt\',0))"',
    # used by 73 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 -c "import subprocess,re,shutil; pdf=\'guide/main.pdf\'; r=subprocess.run([\'pdfinfo\',pdf],capture_output=True,text=True) if shutil.which(\'pdfinfo\') else subprocess.run([\'mdls\',\'-name\',\'kMDItemNumberOfPages\',pdf],capture_output=True,text=True); m=re.search(r\'Pages:\\s*(\\d+)\',r.stdout) or re.search(r\'=\\s*(\\d+)\',r.stdout); print(m.group(1) if m else \'unknown\')"',
    # used by 10 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 -c "import subprocess,re,shutil; pdf=\'guide/main_digital.pdf\'; r=subprocess.run([\'pdfinfo\',pdf],capture_output=True,text=True) if shutil.which(\'pdfinfo\') else subprocess.run([\'mdls\',\'-name\',\'kMDItemNumberOfPages\',pdf],capture_output=True,text=True); m=re.search(r\'Pages:\\s*(\\d+)\',r.stdout) or re.search(r\'=\\s*(\\d+)\',r.stdout); print(m.group(1) if m else \'unknown\')"',
    # used by 10 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 -c "import yaml; print(len(yaml.safe_load(open(\'guide/cards/all_cards.yml\'))[\'cards\']))"',
    # used by 10 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 -c "import yaml; c=yaml.safe_load(open(\'guide/cards/all_cards.yml\'))[\'cards\']; print(round(100*sum(1 for x in c if x.get(\'los_id\'))/max(len(c),1)))"',
    # used by 9 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.check_latex_warnings guide/main_digital.log --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get(\'overfull_50pt\',0))"',
    # used by 8 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -c '\\\\term\\[' guide/glossary-local.tex 2>/dev/null || grep -c '\\\\term\\[' guide/appendices/C_glossary.tex 2>/dev/null || echo 0",
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -c '\\\\term\\[' guide/appendices/C_glossary.tex 2>/dev/null || echo 0",
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 -c "import re; t=open(\'review/supplement_coverage_audit.md\').read(); m=re.search(r\'True gaps.*?: (\\\\d+) / (\\\\d+)\', t); a,b=int(m.group(1)),int(m.group(2)); print(round(100*(1 - a/max(b,1))))"',
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    "grep -ohr '\\\\los{' guide/chapters/ | wc -l",
    # used by 84 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.check_refs guide/chapters/*.tex guide/appendices/*.tex',
    # used by 84 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.extract_los guide/chapters/*.tex --validate',
    # used by 82 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.check_latex_warnings guide/main.log --threshold-red 5',
    # used by 75 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'make -C guide pilot; test -f guide/main.pdf',
    # used by 8 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'make -C guide pdf; test -f guide/main.pdf',
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'make -C guide pilot',
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'PYTHONPATH=../../tooling python3 -m tooling.validation.check_latex_warnings guide/main_digital.log --threshold-red 5',
    # used by 1 guide_qa.yaml entries (2026-08-24 fleet snapshot)
    'python3 scripts/audit_supplement_coverage.py; python3 -c "import re; t=open(\'review/supplement_coverage_audit.md\').read(); m=re.search(r\'True gaps.*?: (\\\\d+) /\', t); assert m and int(m.group(1))==0, f\'supplement has {m.group(1) if m else \\"?\\"} true gaps\'"',
]

INJECTION_PROBES = [
    # (command, reason-substring expected in the rejection)
    ("grep -c '^@' guide/references.bib; touch /tmp/probe", "allowlist"),
    ("grep -c x f && touch /tmp/probe", "forbidden shell character"),
    ("grep -c x $(date)", "outside single quotes"),
    ("grep -c x `date`", "backtick"),
    ('python3 -c "x" > /tmp/probe', "redirect"),
    ("grep x f 2>/tmp/probe", "redirect"),
    ("perl -e 1", "allowlist"),
    ("grep x f & ", "forbidden shell character"),
    ('python3 -c "$(date)"', "outside single quotes"),
    ("PYTHONPATH=$HOME python3 -m x", "outside single quotes"),
    ("'perl' -e 1", "allowlist"),
    ("grep x f | perl -ne 1", "allowlist"),
    ("", "empty"),
    ("   ", "empty"),
    ("grep 'unterminated", "unterminated quote"),
    ("make -C guide pilot; perl payload.pl", "allowlist"),
    ("grep x f <input", "forbidden shell character"),
    ("PYTHONPATH=x", "no executable"),
    ("PATH=./bin grep -c x f", "env assignment"),
    ("LD_PRELOAD=./x.so grep -c x f", "env assignment"),
]


@pytest.mark.parametrize("cmd", FLEET_COMMANDS)
def test_every_fleet_command_vets_clean(cmd):
    assert vet_check_cmd(cmd) is None, f"fleet command rejected: {cmd!r}"


@pytest.mark.parametrize("cmd,reason_substr", INJECTION_PROBES)
def test_injection_probes_rejected(cmd, reason_substr):
    reason = vet_check_cmd(cmd)
    assert reason is not None, f"probe was accepted: {cmd!r}"
    assert reason_substr in reason, f"{cmd!r}: got reason {reason!r}"


def test_escaped_semicolon_is_literal_not_separator():
    # `echo a\;b` passes a literal `;` to echo — one segment, head allowed.
    assert vet_check_cmd(r"echo a\;b") is None


@pytest.mark.parametrize(
    "cmd",
    [
        r"\cmake --version",              # backslash-hidden head (the C1 bypass)
        r"\cmake -E touch /tmp/vet-proof",
        r"\p\e\r\l -e 1",
        r"\t\o\u\c\h /tmp/x",
    ],
)
def test_backslash_hidden_head_is_vetted_as_the_shell_runs_it(cmd):
    # Regression for C1: shlex must see the SAME head /bin/sh resolves, so a
    # non-allowlisted executable disguised with backslashes is refused.
    reason = vet_check_cmd(cmd)
    assert reason is not None, f"backslash bypass accepted: {cmd!r}"
    assert "allowlist" in reason


def test_backslash_escaped_allowlisted_head_still_accepted():
    # `\g\r\e\p` is `grep` to the shell AND to shlex — must vet clean, not be
    # rejected for the wrong reason.
    assert vet_check_cmd(r"\g\r\e\p -c x f") is None
    assert vet_check_cmd(r"gr\ep -c x f") is None


def test_quoted_metachars_are_allowed():
    # `$`, `;`, parens inside SINGLE quotes are literal for the shell.
    assert vet_check_cmd("awk -F: '{s+=$2}END{print s}' f") is None
    # `;` inside double quotes (python payloads) is fine; `$` there is not.
    assert vet_check_cmd('python3 -c "import sys; print(1)"') is None


def test_devnull_redirect_forms():
    assert vet_check_cmd("grep -c x f 2>/dev/null") is None
    assert vet_check_cmd("grep -c x f >/dev/null") is None
    assert vet_check_cmd("grep -c x f 2>/dev/nullX") is not None


def test_allowlist_is_the_fleet_set():
    # Guard against silent allowlist growth: additions need a test edit.
    assert ALLOWED_EXECUTABLES == {
        "grep", "awk", "python3", "wc", "echo", "make", "test",
        "pdfinfo", "mdls",
    }


def test_run_vetted_executes_allowed_command(tmp_path):
    result = run_vetted("echo 3", cwd=str(tmp_path), timeout=10)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.stdout.strip() == "3"
    assert result.returncode == 0


def test_run_vetted_refuses_without_executing(tmp_path):
    marker = tmp_path / "marker"
    with pytest.raises(UnvettedCommandError):
        run_vetted(f"perl -e 'open(F,\">{marker}\")'", cwd=str(tmp_path), timeout=10)
    assert not marker.exists()


def test_run_vetted_pipeline_end_to_end(tmp_path):
    (tmp_path / "f.txt").write_text("a\nb\nc\n")
    result = run_vetted("grep -c . f.txt 2>/dev/null || echo 0", cwd=str(tmp_path), timeout=10)
    assert result.stdout.strip() == "3"
