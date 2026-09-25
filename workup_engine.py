"""
Chargeback Analyst Workup Generator
===================================

Purpose
-------
This module takes:

    1. The original chargeback case
    2. The Evidence Engine result
    3. The Decision Engine result

and produces the final analyst-ready chargeback workup required by
the case study.

Output
------
The workup contains:

    - Reason code summary
    - Requirement-by-requirement evidence assessment
    - Evidence document/page pointers
    - 3-5 sentence analyst rationale
    - Recommended action
    - One-line justification
    - Specific evidence requests when applicable

Important design principle
--------------------------
This component does NOT re-read PDFs or images.

The Evidence Engine has already:
    - processed the documents
    - extracted facts
    - assessed requirements
    - validated evidence pointers

The Decision Engine has already:
    - applied the scheme rule
    - chosen the recommended action
    - determined whether missing evidence is recoverable

This component only turns those structured outputs into a concise,
analyst-friendly workup.
"""



import argparse
import hashlib
import json
import os

from pathlib import Path
from typing import Any


# =====================================================================
# IMPORT EXISTING PIPELINE COMPONENTS
# =====================================================================

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

from decision_engine import (
    decide_case,
    initialise_decision_store,
)


# =====================================================================
# CONFIGURATION
# =====================================================================

WORKUP_ENGINE_VERSION = os.getenv(
    "WORKUP_ENGINE_VERSION",
    "2.0.0",
)


def project_path_from_env(
    variable_name: str,
    default: str,
) -> Path:
    """
    Resolve output paths relative to the project directory.
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


WORKUP_RESULTS_DIR = project_path_from_env(
    "WORKUP_RESULTS_DIR",
    "data/workups",
)

WORKUP_RESULTS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# =====================================================================
# DATABASE
# =====================================================================

def initialise_workup_store() -> None:
    """
    Store completed analyst workups in the same SQLite database.

    This allows the UI/API to retrieve a complete prior workup
    without regenerating the rationale unnecessarily.
    """

    with get_db() as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workups (
                case_id TEXT PRIMARY KEY,

                signature TEXT NOT NULL,

                recommended_action TEXT NOT NULL,

                result_json TEXT NOT NULL,

                created_at TEXT NOT NULL
            )
            """
        )


# =====================================================================
# REASON-CODE SUMMARY
# =====================================================================

def build_reason_code_summary(
    evidence_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the reason-code explanation deterministically.

    We do not need an LLM for this because reason_codes.json already
    contains:

        - reason-code name
        - issuer claim
        - satisfaction criteria

    This keeps the scheme-rule explanation grounded in the supplied
    rules rather than allowing an LLM to invent scheme guidance.
    """

    criteria = evidence_result[
        "satisfaction_criteria"
    ]

    return {
        "scheme":
            evidence_result["scheme"],

        "code":
            evidence_result["reason_code"],

        "name":
            evidence_result.get(
                "reason_code_name",
                "",
            ),

        "issuer_allegation":
            evidence_result.get(
                "issuer_claim",
                "",
            ),

        "evidence_standard":
            criteria.get(
                "description",
                "",
            ),

        "compelling_evidence": [
            requirement.get(
                "requirement",
                "",
            )
            for requirement in evidence_result.get(
                "requirements",
                [],
            )
        ],

        "logic":
            criteria.get(
                "logic",
            ),

        "minimum_required":
            criteria.get(
                "minimum-required",
            ),
    }


# =====================================================================
# ANALYST EVIDENCE CHECKLIST
# =====================================================================

def build_evidence_assessment(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Transform the Evidence Engine result into the simpler format
    required by the analyst UI.

    No LLM call is used here.

    Evidence citations are copied from the validated evidence-engine
    output.
    """

    assessments = []

    for requirement in evidence_result[
        "requirements"
    ]:

        evidence_pointers = []

        for evidence in requirement.get(
            "evidence",
            [],
        ):

            evidence_pointers.append(
                {
                    "document":
                        evidence.get(
                            "document"
                        ),

                    "page":
                        evidence.get(
                            "page"
                        ),

                    "location":
                        evidence.get(
                            "location"
                        ),

                    "chunk_id":
                        evidence.get(
                            "chunk_id"
                        ),

                    "snippet":
                        evidence.get(
                            "snippet"
                        ),

                    "supports":
                        evidence.get(
                            "supports"
                        ),
                }
            )

        assessments.append(
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

                "assessment":
                    requirement.get(
                        "assessment",
                        "",
                    ),

                "evidence":
                    evidence_pointers,

                "case_facts_used":
                    requirement.get(
                        "case_facts_used",
                        [],
                    ),

                "gaps":
                    requirement.get(
                        "gaps",
                        [],
                    ),
            }
        )

    return assessments


# =====================================================================
# RATIONALE GENERATION
# =====================================================================

RATIONALE_SCHEMA = {
    "type": "object",

    "properties": {

        "rationale": {
            "type": "string",
        },
    },

    "required": [
        "rationale",
    ],

    "additionalProperties": False,
}


RATIONALE_INSTRUCTIONS = """
You write concise chargeback analyst rationales.

You are NOT deciding the outcome.

The recommendation has already been determined by a deterministic
decision engine and must not be changed.

Use only the supplied structured evidence assessment.

Rules:

1. Write exactly 3 to 5 sentences.

2. Explain why the evidence does or does not meet the relevant
   compelling-evidence requirements.

3. Do not invent facts.

4. Do not introduce scheme rules that are not provided.

5. Do not claim that a missing or partial requirement is satisfied.

6. Do not treat merchant assertions as independently verified facts.

7. If the action is request_more_evidence, explain the important
   evidence gap and why additional evidence is required.

8. If the action is accept_liability, explain the evidence deficiency
   rather than making broad claims such as "the merchant is wrong."

9. If the action is represent, make the rationale suitable for an
   analyst to edit and include in the representment file.

10. Keep the writing factual, concise and professional.

11. Do not mention AI, models, confidence scores, retrieval systems,
    chunks or internal implementation details.
""".strip()


def build_rationale_context(
    evidence_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build a concise evidence representation for rationale generation.

    We deliberately do not send:
        - raw PDFs
        - raw chunks
        - complete OCR output

    The rationale model only sees validated requirement assessments.
    """

    context = []

    for requirement in evidence_result[
        "requirements"
    ]:

        sources = []

        for item in requirement.get(
            "evidence",
            [],
        ):

            source = {
                "document":
                    item.get(
                        "document"
                    ),

                "location":
                    item.get(
                        "location"
                    ),

                "supports":
                    item.get(
                        "supports"
                    ),
            }

            sources.append(source)

        context.append(
            {
                "requirement":
                    requirement[
                        "requirement"
                    ],

                "status":
                    requirement[
                        "status"
                    ],

                "assessment":
                    requirement.get(
                        "assessment",
                        "",
                    ),

                "supporting_sources":
                    sources,

                "gaps":
                    requirement.get(
                        "gaps",
                        [],
                    ),
            }
        )

    return context


def generate_analyst_rationale(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
    decision_result: dict[str, Any],
) -> str:
    """
    Generate the required 3-5 sentence analyst rationale.

    The recommendation is already fixed before this LLM call.
    """

    rationale_context = (
        build_rationale_context(
            evidence_result
        )
    )

    prompt = f"""
CASE
====

Case ID:
{case["case_id"]}

Merchant:
{case["transaction"]["merchant_name"]}

Amount:
{case["chargeback_amount"]["value"]}
{case["chargeback_amount"]["currency"]}

Scheme:
{evidence_result["scheme"]}

Reason code:
{evidence_result["reason_code"]}

Reason-code name:
{evidence_result.get("reason_code_name", "")}

Issuer allegation:
{evidence_result.get("issuer_claim", "")}


SCHEME EVIDENCE STANDARD
========================

{json.dumps(
    evidence_result["satisfaction_criteria"],
    indent=2,
    ensure_ascii=False,
)}


EVIDENCE ASSESSMENT
===================

{json.dumps(
    rationale_context,
    indent=2,
    ensure_ascii=False,
)}


FINAL RECOMMENDATION
====================

Action:
{decision_result["recommended_action"]}

Decision justification:
{decision_result["justification"]}


ADDITIONAL EVIDENCE REQUESTS
============================

{json.dumps(
    decision_result.get(
        "request_more_evidence",
        [],
    ),
    indent=2,
    ensure_ascii=False,
)}


TASK
====

Write the analyst rationale.

Remember:

- Exactly 3 to 5 sentences.
- Do not change the recommendation.
- Do not invent evidence.
- Base every substantive statement on the structured assessment above.
"""

    response = call_structured_llm(
        instructions=(
            RATIONALE_INSTRUCTIONS
        ),
        prompt=prompt,
        schema_name=(
            "analyst_chargeback_rationale"
        ),
        schema=RATIONALE_SCHEMA,
    )

    return response[
        "rationale"
    ].strip()


# =====================================================================
# REQUEST-MORE-EVIDENCE OUTPUT
# =====================================================================

def build_merchant_requests(
    decision_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Convert Decision Engine evidence requests into the final
    analyst-facing format.

    For represent / accept_liability cases this will normally
    return an empty list.
    """

    if (
        decision_result[
            "recommended_action"
        ]
        != "request_more_evidence"
    ):
        return []

    output = []

    for item in decision_result.get(
        "request_more_evidence",
        [],
    ):

        output.append(
            {
                "requirement_id":
                    item.get(
                        "requirement_id"
                    ),

                "missing_requirement":
                    item.get(
                        "requirement"
                    ),

                "current_status":
                    item.get(
                        "current_status"
                    ),

                "request_to_merchant":
                    item.get(
                        "request"
                    ),

                "why_needed":
                    item.get(
                        "recoverability_reason"
                    ),
            }
        )

    return output


# =====================================================================
# WORKUP CACHE
# =====================================================================

def calculate_workup_signature(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
    decision_result: dict[str, Any],
) -> str:
    """
    Hash all inputs that affect the analyst workup.

    If evidence or the recommendation changes, the workup is
    regenerated automatically.
    """

    payload = {
        "workup_engine_version":
            WORKUP_ENGINE_VERSION,

        "model":
            OPENAI_MODEL,

        "case":
            case,

        "evidence_result":
            evidence_result,

        "decision_result":
            decision_result,
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


def get_cached_workup(
    *,
    case_id: str,
    signature: str,
) -> dict[str, Any] | None:
    """
    Return the cached workup only if its upstream inputs are unchanged.
    """

    with get_db() as conn:

        row = conn.execute(
            """
            SELECT result_json
            FROM workups
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
# WORKUP GENERATION
# =====================================================================

def generate_workup(
    *,
    case: dict[str, Any],
    evidence_result: dict[str, Any],
    decision_result: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    """
    Produce the complete analyst-ready workup.
    """

    initialise_workup_store()

    case_id = case[
        "case_id"
    ]

    # --------------------------------------------------------------
    # Basic integrity checks.
    # --------------------------------------------------------------

    if (
        evidence_result[
            "case_id"
        ]
        != case_id
    ):
        raise ValueError(
            "Evidence result case ID "
            "does not match the case."
        )

    if (
        decision_result[
            "case_id"
        ]
        != case_id
    ):
        raise ValueError(
            "Decision result case ID "
            "does not match the case."
        )

    # --------------------------------------------------------------
    # Cache signature.
    # --------------------------------------------------------------

    signature = (
        calculate_workup_signature(
            case=case,
            evidence_result=(
                evidence_result
            ),
            decision_result=(
                decision_result
            ),
        )
    )

    if not force:

        cached = get_cached_workup(
            case_id=case_id,
            signature=signature,
        )

        if cached is not None:

            output_path = (
                WORKUP_RESULTS_DIR
                / f"{case_id}.json"
            )

            if not output_path.exists():

                output_path.write_text(
                    json.dumps(
                        cached,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            return cached

    # --------------------------------------------------------------
    # Reason-code summary.
    # --------------------------------------------------------------

    reason_code_summary = (
        build_reason_code_summary(
            evidence_result
        )
    )

    # --------------------------------------------------------------
    # Requirement checklist.
    # --------------------------------------------------------------

    evidence_assessment = (
        build_evidence_assessment(
            evidence_result
        )
    )

    # --------------------------------------------------------------
    # LLM-written rationale.
    # --------------------------------------------------------------

    rationale = (
        generate_analyst_rationale(
            case=case,
            evidence_result=(
                evidence_result
            ),
            decision_result=(
                decision_result
            ),
        )
    )

    # --------------------------------------------------------------
    # Merchant evidence requests.
    # --------------------------------------------------------------

    merchant_requests = (
        build_merchant_requests(
            decision_result
        )
    )

    # --------------------------------------------------------------
    # Build final analyst-facing result.
    # --------------------------------------------------------------

    workup = {

        "case_id":
            case_id,

        "merchant":
            case[
                "transaction"
            ][
                "merchant_name"
            ],

        "chargeback": {
            "amount":
                case[
                    "chargeback_amount"
                ][
                    "value"
                ],

            "currency":
                case[
                    "chargeback_amount"
                ][
                    "currency"
                ],

            "chargeback_date":
                case[
                    "chargeback_date"
                ],
        },

        "reason_code_summary":
            reason_code_summary,

        "issuer_narrative":
            case.get(
                "issuer_narrative",
                "",
            ),

        "evidence_assessment":
            evidence_assessment,

        "analyst_rationale":
            rationale,

        "recommended_action":
            decision_result[
                "recommended_action"
            ],

        "action_justification":
            decision_result[
                "justification"
            ],

        "request_more_evidence":
            merchant_requests,

        # Useful for a UI but not necessarily displayed by default.
        "decision_details":
            decision_result.get(
                "rule_evaluation",
                {},
            ),

        "generated_at":
            utc_now(),

        "engine": {
            "version":
                WORKUP_ENGINE_VERSION,

            "rationale_model":
                OPENAI_MODEL,
        },
    }

    # --------------------------------------------------------------
    # Save to SQLite.
    # --------------------------------------------------------------

    with get_db() as conn:

        conn.execute(
            """
            INSERT INTO workups (
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
                case_id,
                signature,
                workup[
                    "recommended_action"
                ],
                json.dumps(
                    workup,
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )

    # --------------------------------------------------------------
    # Save human-readable JSON.
    # --------------------------------------------------------------

    output_path = (
        WORKUP_RESULTS_DIR
        / f"{case_id}.json"
    )

    output_path.write_text(
        json.dumps(
            workup,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return workup


# =====================================================================
# COMPLETE PIPELINE
# =====================================================================

def run_full_workup(
    case_id: str,
    *,
    force_workup: bool = False,
) -> dict[str, Any]:
    """
    Run the complete chargeback-analysis pipeline:

        cases.json
            ↓
        evidence_engine.py
            ↓
        decision_engine.py
            ↓
        workup_engine.py

    The returned object is what your API/UI should consume.
    """

    initialise_database()

    initialise_decision_store()

    initialise_workup_store()

    # --------------------------------------------------------------
    # Load original case.
    # --------------------------------------------------------------

    case = load_case(
        case_id
    )

    # --------------------------------------------------------------
    # Evidence assessment.
    # --------------------------------------------------------------

    evidence_result = assess_case(
        case
    )

    # --------------------------------------------------------------
    # Final decision.
    # --------------------------------------------------------------

    decision_result = decide_case(
        case=case,
        evidence_result=evidence_result,
    )

    # --------------------------------------------------------------
    # Analyst-ready workup.
    # --------------------------------------------------------------

    return generate_workup(
        case=case,
        evidence_result=evidence_result,
        decision_result=decision_result,
        force=force_workup,
    )


# =====================================================================
# CLI
# =====================================================================

def main() -> None:
    """
    Example:

        python workup_engine.py CB-2025-0001

    Force only the workup/rationale layer to regenerate:

        python workup_engine.py CB-2025-0001 --force
    """

    parser = argparse.ArgumentParser(
        description=(
            "Generate analyst-ready "
            "chargeback workup"
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
            "Regenerate the analyst workup "
            "even if a matching cached version exists."
        ),
    )

    args = parser.parse_args()

    result = run_full_workup(
        args.case_id,
        force_workup=args.force,
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
