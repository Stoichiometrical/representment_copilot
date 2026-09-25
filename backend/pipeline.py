from __future__ import annotations

from typing import Any

from decision_engine import decide_case
from evidence_engine import assess_case
from workup_engine import generate_workup


def process_case(case: dict[str, Any]) -> dict[str, Any]:
    evidence = assess_case(case)
    decision = decide_case(case=case, evidence_result=evidence)
    workup = generate_workup(
        case=case,
        evidence_result=evidence,
        decision_result=decision,
    )
    return {
        "case": case,
        "evidence": evidence,
        "decision": decision,
        "workup": workup,
    }

