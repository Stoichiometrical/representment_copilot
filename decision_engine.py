"""
Chargeback Decision Engine
==========================

Purpose
-------
This module consumes the structured output produced by
evidence_engine.py and determines the recommended analyst action:

    - represent
    - accept_liability
    - request_more_evidence

Design principle
----------------
The LLM does NOT decide whether to represent a chargeback.

The actual scheme-rule decision is deterministic.

For example:

    logic = "all"
        Every applicable requirement must be satisfied.

    logic = "any", minimum-required = 2
        At least two applicable requirements must be satisfied.

    logic = "exception-only"
        Represent only if the specified exception is already proven.

    logic = "not-representable"
        Accept liability.

The LLM is used only when the current evidence does NOT satisfy
the rule, to determine whether the missing evidence is realistically
requestable from the merchant.

Example:

    Missing original subscription opt-in record
        -> potentially recoverable
        -> ask merchant for consent/signup record

    Transaction metadata says 3DS = "not_attempted"
        -> not recoverable
        -> merchant cannot retroactively perform 3DS

This keeps business-rule execution deterministic while still using
AI where interpretation is useful.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Reuse the existing evidence engine.
#
# The evidence engine remains responsible for:
#   - loading cases
#   - reading reason_codes.json
#   - document processing
#   - evidence extraction
#   - targeted retrieval
#   - requirement assessment
#   - SQLite connection
# ---------------------------------------------------------------------

from evidence_engine import (
    PROJECT_DIR,
    OPENAI_MODEL,
    assess_case,
    call_structured_llm,
    get_db,
    initialise_database,
    load_case,
    utc_now,
)


# =====================================================================
# CONFIGURATION
# =====================================================================

DECISION_ENGINE_VERSION = os.getenv(
    "DECISION_ENGINE_VERSION",
    "1.0.0",
)


def project_path_from_env(
    variable_name: str,
    default: str,
) -> Path:
    """
    Resolve a project-owned path relative to this file's project.
    """

    path = Path(
        os.getenv(
            variable_name,
            default,
        )
    ).expanduser()

    if not path.is_absolute():
        path = PROJECT_DIR / path

    return path.resolve()


DECISION_RESULTS_DIR = project_path_from_env(
    "DECISION_RESULTS_DIR",
    "data/decisions",
)

DECISION_RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# =====================================================================
# DATABASE
# =====================================================================

def initialise_decision_store() -> None:
    """
    Add a decision-results table to the same SQLite database used
    by the evidence engine.

    Evidence extraction and final recommendation therefore remain
    persisted independently.
    """

    with get_db() as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                case_id TEXT PRIMARY KEY,

                signature TEXT NOT NULL,

                recommended_action TEXT NOT NULL,

                result_json TEXT NOT NULL,

                created_at TEXT NOT NULL
            )
            """
        )


# =====================================================================
# INPUT VALIDATION
# =====================================================================

VALID_REQUIREMENT_STATUSES = {
    "satisfied",
    "partial",
    "missing",
    "not_applicable",
}

SUPPORTED_RULE_LOGIC = {
    "all",
    "any",
    "exception-only",
    "not-representable",
}


def validate_evidence_result(
    evidence_result: dict[str, Any],
) -> None:
    """
    Validate the evidence-engine result before making a decision.

    We fail explicitly rather than silently making a recommendation
    from malformed assessment data.
    """

    required_fields = {
        "case_id",
        "scheme",
        "reason_code",
        "satisfaction_criteria",
        "requirements",
    }

    missing = (
        required_fields
        - set(evidence_result.keys())
    )

    if missing:

        raise ValueError(
            "Evidence result is missing required fields: "
            f"{sorted(missing)}"
        )

    criteria = evidence_result[
        "satisfaction_criteria"
    ]

    if not isinstance(
        criteria,
        dict,
    ):
        raise ValueError(
            "satisfaction_criteria must be an object."
        )

    logic = criteria.get(
        "logic"
    )

    if logic not in SUPPORTED_RULE_LOGIC:

        raise ValueError(
            f"Unsupported satisfaction logic: {logic!r}"
        )

    requirements = evidence_result[
        "requirements"
    ]

    if not isinstance(
        requirements,
        list,
    ):
        raise ValueError(
            "requirements must be a list."
        )

    for requirement in requirements:

        status = requirement.get(
            "status"
        )

        if status not in VALID_REQUIREMENT_STATUSES:

            raise ValueError(
                "Requirement "
                f"{requirement.get('requirement_id')} "
                f"has unsupported status: {status!r}"
            )


# =====================================================================
# DETERMINISTIC RULE EVALUATION
# =====================================================================

def get_applicable_requirements(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Remove requirements classified as NOT_APPLICABLE.

    This matters for rules such as Visa 13.1 where there are
    separate goods and services requirements.

    A goods transaction should not fail because the service-specific
    requirement is not applicable.
    """

    return [
        requirement
        for requirement
        in evidence_result["requirements"]
        if requirement["status"]
        != "not_applicable"
    ]


def evaluate_rule(
    evidence_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply the reason-code satisfaction rule deterministically.

    No LLM is involved here.
    """

    criteria = evidence_result[
        "satisfaction_criteria"
    ]

    logic = criteria[
        "logic"
    ]

    minimum_required = int(
        criteria.get(
            "minimum-required",
            0,
        )
    )

    applicable = (
        get_applicable_requirements(
            evidence_result
        )
    )

    satisfied = [
        item
        for item in applicable
        if item["status"] == "satisfied"
    ]

    partial = [
        item
        for item in applicable
        if item["status"] == "partial"
    ]

    missing = [
        item
        for item in applicable
        if item["status"] == "missing"
    ]

    # --------------------------------------------------------------
    # NOT REPRESENTABLE
    #
    # Example:
    # Mastercard 4870 in the supplied exercise.
    # --------------------------------------------------------------

    if logic == "not-representable":

        return {
            "logic": logic,
            "threshold_met": False,
            "minimum_required": 0,
            "applicable_count": len(applicable),
            "satisfied_count": len(satisfied),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "deficit": 0,
            "reason": (
                "The reason-code rule is marked "
                "not-representable."
            ),
        }

    # --------------------------------------------------------------
    # ALL
    #
    # Every applicable requirement must be satisfied.
    #
    # PARTIAL does NOT count as satisfied.
    # MISSING does NOT count as satisfied.
    # --------------------------------------------------------------

    if logic == "all":

        required = len(applicable)

        threshold_met = (
            required > 0
            and len(satisfied) == required
        )

        deficit = (
            required
            - len(satisfied)
        )

        return {
            "logic": logic,
            "threshold_met": threshold_met,
            "minimum_required": required,
            "applicable_count": required,
            "satisfied_count": len(satisfied),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "deficit": max(
                0,
                deficit,
            ),
            "reason": (
                f"{len(satisfied)} of "
                f"{required} applicable "
                "requirements are satisfied."
            ),
        }

    # --------------------------------------------------------------
    # ANY
    #
    # Example:
    # Mastercard 4837 requires any 2 qualifying options.
    # --------------------------------------------------------------

    if logic == "any":

        threshold_met = (
            len(satisfied)
            >= minimum_required
        )

        deficit = max(
            0,
            minimum_required
            - len(satisfied),
        )

        return {
            "logic": logic,
            "threshold_met": threshold_met,
            "minimum_required": minimum_required,
            "applicable_count": len(applicable),
            "satisfied_count": len(satisfied),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "deficit": deficit,
            "reason": (
                f"{len(satisfied)} qualifying "
                f"requirements are satisfied; "
                f"{minimum_required} required."
            ),
        }

    # --------------------------------------------------------------
    # EXCEPTION ONLY
    #
    # Example:
    # Visa 10.5.
    #
    # The transaction should not be represented unless the specific
    # exception itself has already been proven.
    # --------------------------------------------------------------

    if logic == "exception-only":

        threshold_met = (
            len(satisfied)
            >= minimum_required
        )

        deficit = max(
            0,
            minimum_required
            - len(satisfied),
        )

        return {
            "logic": logic,
            "threshold_met": threshold_met,
            "minimum_required": minimum_required,
            "applicable_count": len(applicable),
            "satisfied_count": len(satisfied),
            "partial_count": len(partial),
            "missing_count": len(missing),
            "deficit": deficit,
            "reason": (
                "The reason code is exception-only; "
                "the exception must already be established."
            ),
        }

    # Should never be reached because validation occurs first.
    raise ValueError(
        f"Unsupported rule logic: {logic}"
    )


# =====================================================================
# GAP RECOVERABILITY
# =====================================================================
#
# The rule engine above tells us whether the merchant CURRENTLY has
# enough evidence.
#
# If they do not, we need to distinguish:
#
#     "Merchant may have the missing document"
#
# from:
#
#     "The underlying historical fact is already known to be false."
#
# Example:
#
# Recoverable:
#     No original subscription opt-in record has been uploaded.
#     We can request the signup/consent log.
#
# Not recoverable:
#     Transaction metadata explicitly says 3DS was not attempted.
#     The merchant cannot retroactively authenticate that transaction.
#
# We use an LLM only for this narrow classification.
# =====================================================================


RECOVERABILITY_SCHEMA = {
    "type": "object",

    "properties": {

        "requirements": {
            "type": "array",

            "items": {
                "type": "object",

                "properties": {

                    "requirement_id": {
                        "type": "string",
                    },

                    "recoverable": {
                        "type": "boolean",
                    },

                    "reason": {
                        "type": "string",
                    },

                    "request": {
                        "type": "string",
                    },
                },

                "required": [
                    "requirement_id",
                    "recoverable",
                    "reason",
                    "request",
                ],

                "additionalProperties": False,
            },
        },
    },

    "required": [
        "requirements",
    ],

    "additionalProperties": False,
}


RECOVERABILITY_INSTRUCTIONS = """
You are analysing evidence gaps in a chargeback case.

You are NOT deciding whether to represent the chargeback.

The requirement statuses supplied by the evidence engine are final
for this step. Do not change satisfied, partial, missing or
not_applicable classifications.

Your only job is to determine whether additional merchant evidence
could realistically close each unresolved requirement.

Definition of RECOVERABLE:

A gap is recoverable when the merchant could plausibly provide an
already-existing record or artefact that would establish the
requirement.

Examples:
- original subscription consent record
- customer communication
- prior transaction history
- signed delivery confirmation
- booking record
- cancellation log
- refund transaction record

Definition of NOT RECOVERABLE:

A gap is not recoverable when:
- known case facts directly contradict the required condition;
- the historical event did not occur;
- the merchant would need to create or alter a historical fact;
- the missing evidence cannot change the scheme-rule outcome.

Examples:
- AVS result is explicitly N when the requirement needs an AVS match;
- CVV result is explicitly N when the requirement needs a CVV match;
- 3DS status says not_attempted when successful 3DS is required;
- delivery happened after the relevant deadline;
- a known delivery address does not satisfy the required address;
- the scheme rule itself is not representable.

Important:
1. Never ask a merchant to manufacture evidence.
2. Only suggest evidence that could already exist.
3. Respect facts in the incoming case.
4. Do not overturn the evidence-engine assessment.
5. If recoverable is false, request must be an empty string.
6. If recoverable is true, request must be concrete and specific.
""".strip()


def get_unresolved_requirements(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Return requirements that currently prevent or may prevent the
    scheme threshold from being reached.
    """

    return [
        requirement
        for requirement
        in evidence_result[
            "requirements"
        ]
        if requirement["status"]
        in {
            "partial",
            "missing",
        }
    ]


def analyse_gap_recoverability(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Ask the LLM whether each unresolved evidence gap could plausibly
    be closed by requesting existing merchant evidence.

    This DOES NOT make the final chargeback decision.
    """

    unresolved = (
        get_unresolved_requirements(
            evidence_result
        )
    )

    if not unresolved:
        return []

    # Send only information needed for this narrow task.
    unresolved_payload = []

    for requirement in unresolved:

        unresolved_payload.append(
            {
                "requirement_id":
                    requirement[
                        "requirement_id"
                    ],

                "requirement":
                    requirement[
                        "requirement"
                    ],

                "current_status":
                    requirement[
                        "status"
                    ],

                "assessment":
                    requirement.get(
                        "assessment",
                        "",
                    ),

                "gaps":
                    requirement.get(
                        "gaps",
                        [],
                    ),

                "case_facts_used":
                    requirement.get(
                        "case_facts_used",
                        [],
                    ),
            }
        )

    prompt = f"""
CASE
====

{json.dumps(
    case,
    indent=2,
    ensure_ascii=False,
)}


REASON CODE
===========

Scheme:
{evidence_result["scheme"]}

Reason code:
{evidence_result["reason_code"]}

Name:
{evidence_result.get("reason_code_name", "")}

Issuer claim:
{evidence_result.get("issuer_claim", "")}


CURRENT RULE
============

{json.dumps(
    evidence_result["satisfaction_criteria"],
    indent=2,
    ensure_ascii=False,
)}


UNRESOLVED REQUIREMENTS
=======================

{json.dumps(
    unresolved_payload,
    indent=2,
    ensure_ascii=False,
)}


TASK
====

For EACH unresolved requirement:

1. Decide whether additional EXISTING merchant evidence could
   realistically satisfy it.

2. Return recoverable=true only when a specific historical record
   or artefact could plausibly close the gap.

3. Return recoverable=false when known case facts already show the
   requirement was not met.

4. If recoverable=true, write exactly what the analyst should ask
   the merchant to provide.

5. Do not decide represent / accept liability / request more evidence.
"""

    raw = call_structured_llm(
        instructions=(
            RECOVERABILITY_INSTRUCTIONS
        ),
        prompt=prompt,
        schema_name=(
            "evidence_gap_recoverability"
        ),
        schema=RECOVERABILITY_SCHEMA,
    )

    # -----------------------------------------------------------------
    # Validate returned requirement IDs.
    #
    # The LLM is only allowed to classify requirements that were
    # actually provided.
    # -----------------------------------------------------------------

    valid_ids = {
        requirement[
            "requirement_id"
        ]
        for requirement
        in unresolved
    }

    results = []

    seen_ids = set()

    for item in raw.get(
        "requirements",
        [],
    ):

        requirement_id = item.get(
            "requirement_id"
        )

        if (
            requirement_id
            not in valid_ids
        ):
            continue

        if requirement_id in seen_ids:
            continue

        seen_ids.add(
            requirement_id
        )

        recoverable = bool(
            item.get(
                "recoverable",
                False,
            )
        )

        request = (
            item.get(
                "request",
                "",
            ).strip()
        )

        # If not recoverable, prevent accidental merchant request text.
        if not recoverable:
            request = ""

        results.append(
            {
                "requirement_id":
                    requirement_id,

                "recoverable":
                    recoverable,

                "reason":
                    item.get(
                        "reason",
                        "",
                    ).strip(),

                "request":
                    request,
            }
        )

    # -----------------------------------------------------------------
    # If the LLM unexpectedly omitted a requirement, default safely to
    # NOT recoverable rather than assuming merchant evidence exists.
    # -----------------------------------------------------------------

    returned_ids = {
        item["requirement_id"]
        for item in results
    }

    for requirement in unresolved:

        requirement_id = (
            requirement[
                "requirement_id"
            ]
        )

        if requirement_id not in returned_ids:

            results.append(
                {
                    "requirement_id":
                        requirement_id,

                    "recoverable":
                        False,

                    "reason":
                        (
                            "Recoverability could not "
                            "be established."
                        ),

                    "request":
                        "",
                }
            )

    return results


# =====================================================================
# REQUEST-MORE-EVIDENCE CALCULATION
# =====================================================================

def select_required_evidence_requests(
    *,
    evidence_result: dict[str, Any],
    rule_evaluation: dict[str, Any],
    recoverability: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Determine whether recoverable gaps are sufficient to potentially
    change the final scheme outcome.

    ALL rule
    --------
    Every unresolved applicable requirement must be recoverable.

    ANY rule
    --------
    We only need enough recoverable requirements to close the
    remaining deficit.

    Example:
        ANY 2 rule
        1 already satisfied
        3 unresolved
        only 1 additional qualifying item is needed

    We therefore request only enough evidence to potentially meet
    the threshold.
    """

    logic = rule_evaluation[
        "logic"
    ]

    recoverable_map = {
        item["requirement_id"]:
            item
        for item
        in recoverability
    }

    unresolved = (
        get_unresolved_requirements(
            evidence_result
        )
    )

    recoverable_requirements = []

    for requirement in unresolved:

        requirement_id = (
            requirement[
                "requirement_id"
            ]
        )

        recovery = (
            recoverable_map.get(
                requirement_id
            )
        )

        if (
            recovery
            and recovery[
                "recoverable"
            ]
        ):

            recoverable_requirements.append(
                {
                    "requirement_id":
                        requirement_id,

                    "requirement":
                        requirement[
                            "requirement"
                        ],

                    "current_status":
                        requirement[
                            "status"
                        ],

                    "request":
                        recovery[
                            "request"
                        ],

                    "recoverability_reason":
                        recovery[
                            "reason"
                        ],
                }
            )

    # --------------------------------------------------------------
    # ALL
    #
    # Every unresolved requirement must potentially be fixable.
    # --------------------------------------------------------------

    if logic == "all":

        unresolved_ids = {
            item[
                "requirement_id"
            ]
            for item
            in unresolved
        }

        recoverable_ids = {
            item[
                "requirement_id"
            ]
            for item
            in recoverable_requirements
        }

        if (
            unresolved_ids
            and unresolved_ids
            == recoverable_ids
        ):
            return recoverable_requirements

        return []

    # --------------------------------------------------------------
    # ANY
    #
    # Only enough evidence to close the numerical deficit is needed.
    # --------------------------------------------------------------

    if logic == "any":

        deficit = int(
            rule_evaluation[
                "deficit"
            ]
        )

        if (
            deficit > 0
            and len(
                recoverable_requirements
            )
            >= deficit
        ):

            # Preserve original requirement order and request only
            # what is needed to potentially meet the scheme threshold.
            return (
                recoverable_requirements[
                    :deficit
                ]
            )

        return []

    # Exception-only and not-representable rules do not enter the
    # request-more-evidence path in this design.
    return []


# =====================================================================
# ONE-LINE JUSTIFICATIONS
# =====================================================================

def build_represent_justification(
    rule_evaluation: dict[str, Any],
) -> str:
    """Create deterministic one-line justification."""

    logic = rule_evaluation[
        "logic"
    ]

    satisfied = rule_evaluation[
        "satisfied_count"
    ]

    required = rule_evaluation[
        "minimum_required"
    ]

    if logic == "all":

        return (
            f"All {required} applicable compelling-evidence "
            "requirements are satisfied."
        )

    if logic == "any":

        return (
            f"{satisfied} qualifying compelling-evidence "
            f"requirements are satisfied; {required} are required."
        )

    if logic == "exception-only":

        return (
            "The specific exception required by this "
            "reason code has been established."
        )

    return (
        "The compelling-evidence threshold is satisfied."
    )


def build_accept_justification(
    rule_evaluation: dict[str, Any],
    recoverability: list[dict[str, Any]],
) -> str:
    """Create deterministic accept-liability justification."""

    logic = rule_evaluation[
        "logic"
    ]

    if logic == "not-representable":

        return (
            "This reason code is designated as "
            "not representable under the supplied scheme rules."
        )

    if logic == "exception-only":

        return (
            "The required exception has not been established, "
            "so the reason code should not be represented."
        )

    non_recoverable = [
        item
        for item
        in recoverability
        if not item[
            "recoverable"
        ]
    ]

    if non_recoverable:

        return (
            "The compelling-evidence threshold is not met and "
            "at least one outcome-critical gap cannot be closed "
            "with additional merchant evidence."
        )

    return (
        "The compelling-evidence threshold is not met and the "
        "available evidence does not support representment."
    )


def build_request_justification(
    requests: list[dict[str, Any]],
) -> str:
    """Create deterministic request-more-evidence justification."""

    count = len(
        requests
    )

    noun = (
        "gap"
        if count == 1
        else "gaps"
    )

    return (
        "The current evidence does not yet meet the scheme "
        f"threshold, but {count} outcome-critical evidence "
        f"{noun} appear recoverable."
    )


# =====================================================================
# DECISION SIGNATURE / CACHE
# =====================================================================

def calculate_decision_signature(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    """
    Create a hash representing the inputs to the decision engine.

    If the evidence assessment changes, the decision cache becomes
    invalid automatically.
    """

    payload = {
        "decision_engine_version":
            DECISION_ENGINE_VERSION,

        "model":
            OPENAI_MODEL,

        "case":
            case,

        "evidence_result":
            evidence_result,
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def get_cached_decision(
    *,
    case_id: str,
    signature: str,
) -> dict[str, Any] | None:
    """
    Return a stored decision only when it was produced from the same
    evidence-engine result.
    """

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT result_json
            FROM decisions
            WHERE case_id = ?
              AND signature = ?
            """,
            (
                case_id,
                signature,
            ),
        ).fetchone()

    if not row:
        return None

    return json.loads(
        row["result_json"]
    )


# =====================================================================
# DECISION ENGINE
# =====================================================================

def decide_case(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    """
    Produce the final recommendation from an evidence-engine result.

    This function follows the sequence:

        1. Validate evidence result.
        2. Apply scheme threshold deterministically.
        3. If threshold is met -> REPRESENT.
        4. If explicitly non-representable -> ACCEPT LIABILITY.
        5. If exception-only and exception missing -> ACCEPT LIABILITY.
        6. Otherwise classify unresolved evidence gaps.
        7. If enough recoverable evidence could change the outcome
           -> REQUEST MORE EVIDENCE.
        8. Otherwise -> ACCEPT LIABILITY.
    """

    validate_evidence_result(
        evidence_result
    )

    if (
        case["case_id"]
        != evidence_result["case_id"]
    ):
        raise ValueError(
            "Case ID does not match the "
            "evidence-engine result."
        )

    initialise_decision_store()

    signature = (
        calculate_decision_signature(
            case=case,
            evidence_result=evidence_result,
        )
    )

    if not force:

        cached = get_cached_decision(
            case_id=case[
                "case_id"
            ],
            signature=signature,
        )

        if cached is not None:
            return cached

    # --------------------------------------------------------------
    # Step 1:
    # Apply the actual scheme rule deterministically.
    # --------------------------------------------------------------

    rule_evaluation = evaluate_rule(
        evidence_result
    )

    logic = rule_evaluation[
        "logic"
    ]

    recoverability: list[
        dict[str, Any]
    ] = []

    evidence_requests: list[
        dict[str, Any]
    ] = []

    # --------------------------------------------------------------
    # REPRESENT
    #
    # The required scheme threshold has already been met.
    # No gap analysis or additional LLM call is necessary.
    # --------------------------------------------------------------

    if rule_evaluation[
        "threshold_met"
    ]:

        recommended_action = (
            "represent"
        )

        justification = (
            build_represent_justification(
                rule_evaluation
            )
        )

    # --------------------------------------------------------------
    # NOT REPRESENTABLE
    # --------------------------------------------------------------

    elif logic == "not-representable":

        recommended_action = (
            "accept_liability"
        )

        justification = (
            build_accept_justification(
                rule_evaluation,
                recoverability,
            )
        )

    # --------------------------------------------------------------
    # EXCEPTION ONLY
    #
    # We deliberately do not turn this into an open-ended
    # request-more-evidence path.
    #
    # If the exception was not established by the submitted evidence,
    # accept liability.
    # --------------------------------------------------------------

    elif logic == "exception-only":

        recommended_action = (
            "accept_liability"
        )

        justification = (
            build_accept_justification(
                rule_evaluation,
                recoverability,
            )
        )

    # --------------------------------------------------------------
    # ALL / ANY rule failed.
    #
    # Now, and only now, determine whether missing merchant evidence
    # could realistically change the outcome.
    # --------------------------------------------------------------

    else:

        recoverability = (
            analyse_gap_recoverability(
                case=case,
                evidence_result=(
                    evidence_result
                ),
            )
        )

        evidence_requests = (
            select_required_evidence_requests(
                evidence_result=(
                    evidence_result
                ),
                rule_evaluation=(
                    rule_evaluation
                ),
                recoverability=(
                    recoverability
                ),
            )
        )

        if evidence_requests:

            recommended_action = (
                "request_more_evidence"
            )

            justification = (
                build_request_justification(
                    evidence_requests
                )
            )

        else:

            recommended_action = (
                "accept_liability"
            )

            justification = (
                build_accept_justification(
                    rule_evaluation,
                    recoverability,
                )
            )

    # --------------------------------------------------------------
    # Prepare concise unresolved-requirement information for the UI.
    # --------------------------------------------------------------

    unresolved_requirements = []

    for requirement in (
        get_unresolved_requirements(
            evidence_result
        )
    ):

        unresolved_requirements.append(
            {
                "requirement_id":
                    requirement[
                        "requirement_id"
                    ],

                "requirement":
                    requirement[
                        "requirement"
                    ],

                "status":
                    requirement[
                        "status"
                    ],

                "gaps":
                    requirement.get(
                        "gaps",
                        [],
                    ),
            }
        )

    # --------------------------------------------------------------
    # Final structured decision result.
    # --------------------------------------------------------------

    decision_result = {
        "case_id":
            evidence_result[
                "case_id"
            ],

        "scheme":
            evidence_result[
                "scheme"
            ],

        "reason_code":
            evidence_result[
                "reason_code"
            ],

        "reason_code_name":
            evidence_result.get(
                "reason_code_name"
            ),

        "recommended_action":
            recommended_action,

        "justification":
            justification,

        "rule_evaluation":
            rule_evaluation,

        "unresolved_requirements":
            unresolved_requirements,

        "request_more_evidence":
            evidence_requests,

        "gap_recoverability":
            recoverability,

        "decision_engine": {
            "version":
                DECISION_ENGINE_VERSION,

            "decision_method":
                (
                    "deterministic rule evaluation "
                    "+ LLM gap recoverability analysis"
                ),

            "model_used_for_gap_analysis":
                (
                    OPENAI_MODEL
                    if recoverability
                    else None
                ),
        },

        "generated_at":
            utc_now(),
    }

    # --------------------------------------------------------------
    # Persist the decision in SQLite.
    # --------------------------------------------------------------

    with get_db() as conn:

        conn.execute(
            """
            INSERT INTO decisions (
                case_id,
                signature,
                recommended_action,
                result_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(case_id)
            DO UPDATE SET
                signature =
                    excluded.signature,

                recommended_action =
                    excluded.recommended_action,

                result_json =
                    excluded.result_json,

                created_at =
                    excluded.created_at
            """,
            (
                case["case_id"],
                signature,
                recommended_action,
                json.dumps(
                    decision_result,
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )

    # --------------------------------------------------------------
    # Also persist human-readable JSON.
    # --------------------------------------------------------------

    output_path = (
        DECISION_RESULTS_DIR
        / f"{case['case_id']}.json"
    )

    output_path.write_text(
        json.dumps(
            decision_result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return decision_result


# =====================================================================
# FULL PIPELINE
# =====================================================================

def run_case(
    case_id: str,
    *,
    force_decision: bool = False,
) -> dict[str, Any]:
    """
    Run:

        cases.json
            ↓
        evidence engine
            ↓
        decision engine

    The evidence engine handles its own persistence/cache.
    """

    initialise_database()

    initialise_decision_store()

    # Load original case.
    case = load_case(
        case_id
    )

    # Run/retrieve evidence assessment.
    evidence_result = assess_case(
        case
    )

    # Produce recommendation.
    decision_result = decide_case(
        case=case,
        evidence_result=evidence_result,
        force=force_decision,
    )

    return decision_result


# =====================================================================
# CLI
# =====================================================================

def main() -> None:
    """
    Usage:

        python decision_engine.py CB-2025-0001

    Force the decision step to rerun:

        python decision_engine.py CB-2025-0001 --force
    """

    parser = argparse.ArgumentParser(
        description=(
            "Chargeback recommendation "
            "decision engine"
        )
    )

    parser.add_argument(
        "case_id",
        help=(
            "Case ID from cases.json, "
            "for example CB-2025-0001."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rerun the decision step even if "
            "a matching cached decision exists."
        ),
    )

    args = parser.parse_args()

    result = run_case(
        args.case_id,
        force_decision=args.force,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":

    main()