from __future__ import annotations

import json
from typing import Any

from evidence_engine import CASES_PATH, get_db, utc_now


def initialise_app_store() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loaded_cases (
                case_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                case_json TEXT NOT NULL,
                loaded_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyst_overrides (
                case_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                rationale TEXT NOT NULL,
                analyst_note TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _invalidate_case(conn: Any, case_id: str) -> None:
    for table in ("workups", "decisions", "case_results"):
        conn.execute(
            f"DELETE FROM {table} WHERE case_id = ?",
            (case_id,),
        )


def upsert_case(
    case: dict[str, Any],
    *,
    source: str,
    force_invalidate: bool = False,
) -> bool:
    case_id = case["case_id"]
    encoded = json.dumps(case, sort_keys=True, ensure_ascii=False)

    with get_db() as conn:
        existing = conn.execute(
            "SELECT case_json FROM loaded_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        changed = bool(
            force_invalidate
            or (existing and existing["case_json"] != encoded)
        )

        if changed:
            _invalidate_case(conn, case_id)

        conn.execute(
            """
            INSERT INTO loaded_cases (case_id, source, case_json, loaded_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                source = excluded.source,
                case_json = excluded.case_json,
                loaded_at = excluded.loaded_at
            """,
            (case_id, source, encoded, utc_now()),
        )

    return changed


def import_fixture_cases() -> dict[str, int]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("cases.json must contain an array of cases.")

    changed = 0
    for case in payload:
        validate_case(case)
        changed += int(upsert_case(case, source="cases.json"))
    return {"loaded": len(payload), "changed": changed}


def validate_case(case: dict[str, Any]) -> None:
    required = {
        "case_id",
        "scheme",
        "reason_code",
        "chargeback_date",
        "chargeback_amount",
        "transaction",
        "issuer_narrative",
        "merchant_evidence_documents",
    }
    missing = required - set(case)
    if missing:
        raise ValueError(f"Case is missing required fields: {sorted(missing)}")
    if not isinstance(case["merchant_evidence_documents"], list):
        raise ValueError("merchant_evidence_documents must be an array.")
    if not case["transaction"].get("merchant_name"):
        raise ValueError("transaction.merchant_name is required.")


def get_case(case_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT case_json FROM loaded_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return json.loads(row["case_json"]) if row else None


def _json_or_none(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


def list_cases() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                c.case_id,
                c.source,
                c.case_json,
                w.recommended_action,
                w.created_at AS processed_at,
                o.action AS override_action
            FROM loaded_cases c
            LEFT JOIN workups w ON w.case_id = c.case_id
            LEFT JOIN analyst_overrides o ON o.case_id = c.case_id
            ORDER BY c.loaded_at, c.case_id
            """
        ).fetchall()

    summaries = []
    for row in rows:
        case = json.loads(row["case_json"])
        amount = case.get("chargeback_amount", {})
        summaries.append(
            {
                "case_id": case["case_id"],
                "merchant": case.get("transaction", {}).get("merchant_name", ""),
                "scheme": case.get("scheme"),
                "reason_code": case.get("reason_code"),
                "reason_code_label": case.get("reason_code_label", ""),
                "amount": amount.get("value"),
                "currency": amount.get("currency"),
                "document_count": len(case.get("merchant_evidence_documents", [])),
                "source": row["source"],
                "status": "processed" if row["processed_at"] else "ready",
                "recommended_action": row["override_action"] or row["recommended_action"],
                "processed_at": row["processed_at"],
            }
        )
    return summaries


def get_stored_json(table: str, case_id: str) -> dict[str, Any] | None:
    allowed = {"case_results", "decisions", "workups"}
    if table not in allowed:
        raise ValueError("Unsupported result table.")
    with get_db() as conn:
        row = conn.execute(
            f"SELECT result_json FROM {table} WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return _json_or_none(row["result_json"]) if row else None


def get_override(case_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM analyst_overrides WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return dict(row) if row else None


def save_override(
    case_id: str,
    *,
    action: str,
    rationale: str,
    analyst_note: str,
) -> dict[str, Any]:
    timestamp = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO analyst_overrides
                (case_id, action, rationale, analyst_note, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                action = excluded.action,
                rationale = excluded.rationale,
                analyst_note = excluded.analyst_note,
                updated_at = excluded.updated_at
            """,
            (case_id, action, rationale, analyst_note, timestamp),
        )
    return get_override(case_id) or {}


def get_documents(case: dict[str, Any]) -> list[dict[str, Any]]:
    case_id = case["case_id"]
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.filename, d.source_type, d.processed_at,
                   COUNT(DISTINCT p.id) AS page_count,
                   COUNT(DISTINCT c.id) AS chunk_count
            FROM documents d
            LEFT JOIN pages p ON p.document_id = d.id
            LEFT JOIN chunks c ON c.document_id = d.id
            WHERE d.case_id = ?
            GROUP BY d.id
            """,
            (case_id,),
        ).fetchall()
    indexed = {row["filename"]: dict(row) for row in rows}
    return [
        indexed.get(
            name,
            {
                "filename": name,
                "source_type": name.rsplit(".", 1)[-1].lower(),
                "processed_at": None,
                "page_count": 0,
                "chunk_count": 0,
            },
        )
        for name in case.get("merchant_evidence_documents", [])
    ]


def get_chunks(case_id: str, filename: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, page_number, chunk_index,
                   extraction_method, text
            FROM chunks
            WHERE case_id = ? AND filename = ?
            ORDER BY page_number, chunk_index
            """,
            (case_id, filename),
        ).fetchall()
    return [
        {
            "chunk_id": f"chunk_{row['id']}",
            "filename": row["filename"],
            "page": row["page_number"],
            "chunk_index": row["chunk_index"],
            "extraction_method": row["extraction_method"],
            "text": row["text"],
        }
        for row in rows
    ]

