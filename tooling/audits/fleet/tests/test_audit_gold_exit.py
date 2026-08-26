"""Exit-code contract for audit_gold (gt#27).

The defect: ``--guide`` runs exited 0 even on FAIL, so automation reading
exit codes could not tell a failed guide from a Gold one. The contract now
lives in ``exit_code_for`` and applies to fleet and single-guide mode alike.
"""

from types import SimpleNamespace

from tooling.audits.fleet.audit_gold import exit_code_for


def _r(classification: str) -> SimpleNamespace:
    return SimpleNamespace(classification=classification)


def test_pass_and_gold_eligible_exit_zero():
    assert exit_code_for([_r("PASS")]) == 0
    assert exit_code_for([_r("GOLD-ELIGIBLE")]) == 0
    assert exit_code_for([_r("PASS"), _r("GOLD-ELIGIBLE")]) == 0


def test_single_guide_fail_exits_one():
    assert exit_code_for([_r("FAIL")]) == 1


def test_single_guide_scaffold_only_exits_one():
    assert exit_code_for([_r("SCAFFOLD-ONLY")]) == 1


def test_fleet_with_one_fail_exits_one():
    assert exit_code_for([_r("PASS")] * 40 + [_r("FAIL")]) == 1


def test_empty_report_list_exits_zero():
    # An unresolvable slug exits 1 earlier, before reports exist.
    assert exit_code_for([]) == 0
