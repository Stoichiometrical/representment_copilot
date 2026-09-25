from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from decision_engine import initialise_decision_store
from evidence_engine import (
    DOCUMENTS_DIR,
    OPENAI_MODEL,
    get_db,
    initialise_database,
    resolve_evidence_path,
)
from workup_engine import initialise_workup_store

from .pipeline import process_case
from .repository import (
    get_case,
    get_chunks,
    get_documents,
    get_override,
    get_stored_json,
    import_fixture_cases,
    initialise_app_store,
    list_cases,
    save_override,
    upsert_case,
    validate_case,
)
from .schemas import AnalystOverride


app = FastAPI(title="Chargeback Representment Copilot", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    initialise_database()
    initialise_decision_store()
    initialise_workup_store()
    initialise_app_store()


def require_case(case_id: str) -> dict:
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} was not loaded.")
    return case


def case_bundle(case_id: str) -> dict:
    case = require_case(case_id)
    return {
        "case": case,
        "workup": get_stored_json("workups", case_id),
        "decision": get_stored_json("decisions", case_id),
        "evidence": get_stored_json("case_results", case_id),
        "override": get_override(case_id),
        "documents": get_documents(case),
    }


@app.get("/api/health")
def health() -> dict:
    with get_db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "version": "2.0.0", "model": OPENAI_MODEL}


@app.post("/api/cases/load")
def load_demo_cases() -> dict:
    try:
        result = import_fixture_cases()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "cases": list_cases()}


@app.get("/api/cases")
def cases() -> list[dict]:
    return list_cases()


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict:
    return case_bundle(case_id)


@app.post("/api/cases/{case_id}/process")
async def run_case(case_id: str) -> dict:
    case = require_case(case_id)
    try:
        await run_in_threadpool(process_case, case)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc
    return case_bundle(case_id)


@app.post("/api/cases/{case_id}/override")
def override(case_id: str, payload: AnalystOverride) -> dict:
    require_case(case_id)
    return save_override(case_id, **payload.model_dump())


@app.get("/api/cases/{case_id}/chunks")
def chunks(case_id: str, filename: str) -> list[dict]:
    case = require_case(case_id)
    if filename not in case.get("merchant_evidence_documents", []):
        raise HTTPException(status_code=404, detail="Document is not part of this case.")
    return get_chunks(case_id, filename)


@app.get("/api/cases/{case_id}/documents/{filename}")
def document(case_id: str, filename: str) -> FileResponse:
    case = require_case(case_id)
    if filename not in case.get("merchant_evidence_documents", []):
        raise HTTPException(status_code=404, detail="Document is not part of this case.")
    try:
        path = resolve_evidence_path(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=filename, content_disposition_type="inline")


def safe_case_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}", value):
        raise ValueError("case_id may contain letters, numbers, dots, underscores and hyphens.")
    return value


@app.post("/api/cases/manual")
async def create_manual_case(
    case_json: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()] = [],
) -> dict:
    try:
        case = json.loads(case_json)
        validate_case(case)
        case_id = safe_case_id(case["case_id"])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stored_names: list[str] = []
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

    for upload in files:
        original = Path(upload.filename or "evidence").name
        suffix = Path(original).suffix.lower()
        if suffix not in allowed:
            raise HTTPException(status_code=400, detail=f"Unsupported evidence type: {suffix}")
        stored_name = f"{case_id}_{original}"
        content = await upload.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"{original} exceeds 20 MB.")
        (DOCUMENTS_DIR / stored_name).write_bytes(content)
        stored_names.append(stored_name)

    case["merchant_evidence_documents"] = stored_names
    upsert_case(case, source="manual", force_invalidate=True)
    return case_bundle(case_id)

