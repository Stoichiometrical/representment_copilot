# Architecture and design decisions

## System boundary

```mermaid
flowchart LR
    A[React analyst workspace] -->|JSON / multipart| B[FastAPI orchestration API]
    B --> C[Evidence Engine]
    C --> D[Decision Engine]
    D --> E[Workup Engine]
    C --> F[(SQLite)]
    D --> F
    E --> F
    B --> F
    C --> G[Merchant documents]
    C --> H[OpenAI gpt-6-sol]
    D --> H
    E --> H
    B -->|inline PDF/image + chunks| A
```

The three supplied engines remain separate modules. FastAPI coordinates them rather than duplicating their logic. This keeps evidence interpretation, deterministic decision policy, and analyst-facing writing independently testable.

## Case processing sequence

```mermaid
sequenceDiagram
    actor Analyst
    participant UI as React UI
    participant API as FastAPI
    participant EE as Evidence Engine
    participant DE as Decision Engine
    participant WE as Workup Engine
    participant DB as SQLite

    Analyst->>UI: Select case and Process
    UI->>API: POST /api/cases/{id}/process
    API->>EE: assess_case(case)
    EE->>EE: Hash case, rule, model, engine and evidence files
    EE->>DB: Retrieve exact-signature result
    alt evidence cache miss
        EE->>EE: Extract pages/images, chunk and retrieve
        EE->>DB: Store documents, pages, chunks and assessments
    end
    API->>DE: decide_case(case, evidence)
    DE->>DE: Apply deterministic satisfaction rule
    DE->>DB: Store signature-scoped decision
    API->>WE: generate_workup(case, evidence, decision)
    WE->>DB: Store signature-scoped workup
    API-->>UI: Case + evidence + decision + workup + documents
    Analyst->>UI: Open citation / edit action and rationale
    UI->>API: Source request or analyst override
```

## Why the UI is queue-first

An analyst working roughly 80 cases per day needs to answer four questions quickly:

1. What is the allegation and applicable defense standard?
2. Which requirements are satisfied, partial or missing?
3. Where can I verify each claimed fact?
4. What should I file or ask the merchant for?

The left queue keeps merchant, amount, scheme/code, document count and current action visible. The center column follows the analyst's decision sequence: issuer allegation, reason-code standard, transaction facts, evidence matrix, then editable decision. The right source inspector remains visible while the analyst reads the matrix. Clicking a citation selects the original file, PDF page, validated excerpt and exact extracted chunk.

The system recommendation is deliberately editable. The override stores the action, edited rationale, analyst note and timestamp separately from engine output, preserving both machine recommendation and human accountability.

## Persistence and cache validity

SQLite contains loaded cases, document/page/chunk extraction, requirement assessments, decisions, workups and analyst overrides. Evidence cache reuse requires both `case_id` and a signature covering:

- the complete current case;
- the applicable reason-code rule;
- checksums of every currently referenced evidence file;
- the model; and
- the engine version.

This permits fast repeat review while detecting a replaced, added or removed merchant document. Removed document records cascade to their pages and chunks on the next cache miss.

## Manual intake

The Add Case dialog exposes the raw transaction fields used by the engines and accepts PDF, PNG, JPG and WebP evidence. The API normalizes uploaded names under the case ID, limits individual files to 20 MB, stores the case in the same local queue and invalidates any older result for that case ID.

## Scope and limitations

- The API is intentionally synchronous because this case study has ten small cases. Production should use a durable job queue and expose progress events.
- SQLite is appropriate for a single analyst demo. A multi-user service should use a managed relational database and object storage.
- Authentication, authorization, malware scanning and scheme-rule update operations are outside this assignment.
- The Vite server is used for simple local execution. Production should serve the built frontend behind the application gateway.
