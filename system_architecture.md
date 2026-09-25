# Representment Desk — System Architecture

## 1. What the system does

Representment Desk turns a raw chargeback case and its merchant evidence into an analyst-ready workup. It separates the work into three stages so that evidence interpretation, scheme-rule execution and analyst writing can be inspected independently.

```mermaid
flowchart LR
    classDef input fill:#EAF1FF,stroke:#3568B8,color:#13233A
    classDef engine fill:#13253A,stroke:#13253A,color:#FFFFFF
    classDef decision fill:#FFF2D8,stroke:#C57A11,color:#432A08
    classDef output fill:#E5F5EE,stroke:#19815F,color:#123D30
    classDef store fill:#F0EBFF,stroke:#7457B5,color:#2E2150

    A[Chargeback case<br/>transaction and issuer claim]:::input
    B[Merchant evidence<br/>PDFs and images]:::input
    C[Evidence Engine<br/>extract, retrieve, assess]:::engine
    D[Decision Engine<br/>apply rule deterministically]:::decision
    E[Workup Engine<br/>compose analyst output]:::engine
    F[Analyst workspace<br/>review, verify, override]:::output
    G[(SQLite<br/>results and audit state)]:::store

    A --> C
    B --> C
    C --> D
    D --> E
    E --> F
    C <--> G
    D <--> G
    E <--> G
    F <--> G
```

The Evidence Engine answers **what the submission proves**. The Decision Engine answers **what action the rule permits**. The Workup Engine answers **how the conclusion should be presented to an analyst**. The React interface keeps the human analyst in control of the final filed decision.

## 2. System topology

```mermaid
flowchart TB
    subgraph Browser[Analyst browser]
        UI[React and Vite interface]
        Queue[Case queue and filters]
        Matrix[Evidence matrix]
        Inspector[PDF, image and chunk inspector]
        Editor[Rationale and action editor]
        UI --- Queue
        UI --- Matrix
        UI --- Inspector
        UI --- Editor
    end

    subgraph API[FastAPI orchestration layer]
        Routes[Case and workup routes]
        Intake[Manual intake and uploads]
        Sources[Document and chunk routes]
        Overrides[Analyst override routes]
        Repository[SQLite repository]
    end

    subgraph Pipeline[Analysis pipeline]
        Evidence[evidence_engine.py]
        Decision[decision_engine.py]
        Workup[workup_engine.py]
    end

    subgraph LocalData[Local data boundary]
        Cases[cases.json]
        Rules[reason_codes.json]
        Docs[documents folder]
        DB[(evidence_engine.db)]
        Results[data results, decisions and workups]
    end

    subgraph External[External service]
        LLM[OpenAI gpt-6-sol]
    end

    UI <-->|JSON and multipart| Routes
    Routes --> Intake
    Routes --> Sources
    Routes --> Overrides
    Routes --> Repository
    Routes --> Evidence
    Evidence --> Decision
    Decision --> Workup
    Cases --> Intake
    Rules --> Evidence
    Docs --> Evidence
    Sources --> Docs
    Sources --> DB
    Repository <--> DB
    Evidence <--> DB
    Decision <--> DB
    Workup <--> DB
    Evidence --> Results
    Decision --> Results
    Workup --> Results
    Evidence <-->|vision and structured assessment| LLM
    Decision <-->|gap recoverability only| LLM
    Workup <-->|rationale writing only| LLM
```

### Component responsibilities

| Component | Owns | Does not own |
|---|---|---|
| React interface | Queue navigation, evidence verification, manual intake, analyst edits and overrides | Scheme-rule execution or evidence interpretation |
| FastAPI | HTTP contracts, uploads, orchestration and response assembly | Duplicated decision logic |
| Evidence Engine | Extraction, chunking, retrieval, requirement assessment and citations | Final represent/accept decision |
| Decision Engine | Satisfaction threshold, recommended action and recoverable-gap analysis | Re-reading source documents |
| Workup Engine | Reason summary, evidence checklist, rationale and merchant request presentation | Changing the deterministic recommendation |
| SQLite | Persistent extraction, results, loaded cases and analyst overrides | Original evidence binaries |
| Documents folder | Original PDF and image evidence | Derived assessment state |

This division reduces hidden coupling. A reviewer can inspect a citation without trusting the decision layer, and can inspect the decision rule without asking the model to reproduce document extraction.

## 3. End-to-end analyst flow

```mermaid
sequenceDiagram
    autonumber
    actor Analyst
    participant UI as React UI
    participant API as FastAPI
    participant EE as Evidence Engine
    participant DE as Decision Engine
    participant WE as Workup Engine
    participant DB as SQLite
    participant AI as gpt-6-sol

    Analyst->>UI: Click Load cases
    UI->>API: POST /api/cases/load
    API->>DB: Upsert cases from cases.json
    API-->>UI: Queue summaries

    Analyst->>UI: Select case and Process
    UI->>API: POST /api/cases/{id}/process
    API->>EE: assess_case(case)
    EE->>EE: Validate rule and calculate input signature
    EE->>DB: Find case result by case ID and signature

    alt Exact signature cache hit
        DB-->>EE: Stored evidence result
    else New or changed input
        EE->>EE: Extract PDF text and inspect images
        EE->>EE: Split text into page-bound chunks
        EE->>EE: Retrieve requirement-specific chunks
        EE->>AI: Assess one requirement at a time
        AI-->>EE: Status, support and gaps
        EE->>EE: Validate returned chunk and fact IDs
        EE->>DB: Store documents, pages, chunks and assessment
    end

    EE-->>API: Structured evidence assessment
    API->>DE: decide_case(case, evidence)
    DE->>DE: Apply all, any, exception or blocked rule

    opt Missing evidence may be recoverable
        DE->>AI: Classify whether the gap can be requested
        AI-->>DE: Recoverability and specific request
    end

    DE->>DB: Store signed decision
    DE-->>API: Recommended action and justification
    API->>WE: generate_workup(case, evidence, decision)
    WE->>AI: Write grounded 3 to 5 sentence rationale
    AI-->>WE: Editable rationale
    WE->>DB: Store signed analyst workup
    WE-->>API: Complete workup
    API-->>UI: Case, evidence, decision, workup and sources

    Analyst->>UI: Verify citation and edit conclusion
    UI->>API: Open original or retrieve chunks
    API-->>UI: PDF, image or extracted text
    Analyst->>UI: Save action, rationale and note
    UI->>API: POST /api/cases/{id}/override
    API->>DB: Store human decision separately
```

### Why the engines run in this order

1. **Evidence comes first.** A decision should be based on validated facts and source pointers, not on an unconstrained reading of the entire submission.
2. **The rule is applied after evidence classification.** This makes the final action reproducible from requirement statuses and the reason-code threshold.
3. **The rationale is written last.** The writing model receives structured findings and a fixed recommendation, reducing the chance that persuasive wording changes the actual decision.
4. **The analyst reviews the combined workup.** Automation reduces document handling and drafting time while preserving human accountability for the filed response.

## 4. Evidence processing and citation integrity

```mermaid
flowchart TD
    classDef source fill:#EAF1FF,stroke:#3568B8
    classDef process fill:#F5F7FA,stroke:#65778B
    classDef ai fill:#13253A,stroke:#13253A,color:#FFF
    classDef safe fill:#E5F5EE,stroke:#19815F

    F[Referenced evidence filename]:::source --> S{Supported type?}
    S -->|PDF| P[Native page text extraction]:::process
    S -->|PNG, JPG or WebP| V[Vision transcription]:::ai
    P --> Q{Text sparse or<br/>large image present?}
    Q -->|Yes| R[Render page and supplement with vision]:::ai
    Q -->|No| T[Use native page text]:::process
    R --> U[Persist page with extraction method]:::safe
    T --> U
    V --> U
    U --> C[Create overlapping chunks<br/>that never cross page boundaries]:::process
    C --> I[(Persist filename, page,<br/>chunk ID and text)]:::safe
    I --> BM[BM25 requirement retrieval<br/>plus exact fact boosts]:::process
    BM --> L[LLM assesses one requirement]:::ai
    L --> X{Returned IDs exist?}
    X -->|Yes| Y[Resolve citation from database]:::safe
    X -->|No| Z[Discard invented pointer]:::safe
    Y --> O[Satisfied, partial, missing<br/>or not applicable]:::safe
    Z --> O
```

The model never supplies an authoritative filename or page number. It may select only chunk IDs and case-fact keys that were included in its prompt. The engine resolves those identifiers back to database records and silently drops unknown IDs. This makes every displayed citation traceable to a stored source.

### Retrieval choice

The current evidence script uses BM25 with exact transaction-field boosts. That choice is appropriate for the small case-local corpus because chargeback evidence often turns on exact values such as tracking numbers, dates, postcodes, transaction IDs and authorization codes. Requirement-specific retrieval also prevents unrelated pages from consuming the assessment context.

The tradeoff is weaker semantic matching for heavily paraphrased evidence. A production extension could add BGE Large embeddings and combine semantic and lexical scores while retaining the same chunk IDs and citation validation boundary.

## 5. Decision policy

```mermaid
flowchart TD
    A[Requirement assessments] --> B{Rule logic}
    B -->|not-representable| C[accept_liability]
    B -->|exception-only| D{Exception satisfied?}
    D -->|Yes| E[represent]
    D -->|No| C
    B -->|all| F{All applicable<br/>requirements satisfied?}
    B -->|any N| G{At least N<br/>requirements satisfied?}
    F -->|Yes| E
    G -->|Yes| E
    F -->|No| H[Inspect unresolved gaps]
    G -->|No| H
    H --> I{At least one gap<br/>realistically recoverable?}
    I -->|Yes| J[request_more_evidence]
    I -->|No| C
    J --> K[Specific merchant requests]
    E --> L[One-line justification]
    C --> L
    K --> L
```

The LLM does not choose between represent and accept liability. The Decision Engine applies the structured `satisfaction-criteria` from `reason_codes.json`. AI is used only after the rule is not met, to determine whether a missing item can realistically be supplied by the merchant. For example, an existing signed delivery record may be requestable, while retroactively performing 3-D Secure is not.

This hybrid design combines consistent policy execution with useful interpretation of ambiguous evidence gaps.

## 6. Cache validation and change detection

```mermaid
flowchart LR
    A[Current case JSON] --> H[Canonical signature payload]
    B[Current reason-code rule] --> H
    C[Current evidence filenames<br/>and SHA-256 checksums] --> H
    D[OpenAI model] --> H
    E[Engine version] --> H
    H --> S[SHA-256 signature]
    S --> Q{case ID and signature<br/>match SQLite?}
    Q -->|Yes| R[Return stored result]
    Q -->|No| P[Reprocess changed inputs]
    P --> U[Replace result and signature]
```

Using only `case_id` would be unsafe because a merchant could upload new evidence under an existing case. The signature is calculated from the current files before a cached result is accepted. Therefore:

- a changed case narrative invalidates the cache;
- a changed rule invalidates the cache;
- an added, removed or replaced document invalidates the cache;
- a model or engine-version change invalidates the cache; and
- an unchanged case returns quickly without repeating extraction or LLM calls.

The Evidence, Decision and Workup Engines have separate signatures. A presentation-layer change can regenerate the workup while retaining valid evidence extraction and deterministic decision results.

## 7. Persistent data model

```mermaid
erDiagram
    LOADED_CASES ||--o{ DOCUMENTS : references
    DOCUMENTS ||--o{ PAGES : contains
    DOCUMENTS ||--o{ CHUNKS : contains
    PAGES ||--o{ CHUNKS : split_into
    LOADED_CASES ||--o{ ASSESSMENTS : receives
    LOADED_CASES ||--o| CASE_RESULTS : produces
    LOADED_CASES ||--o| DECISIONS : produces
    LOADED_CASES ||--o| WORKUPS : produces
    LOADED_CASES ||--o| ANALYST_OVERRIDES : may_have

    LOADED_CASES {
        string case_id PK
        string source
        json case_json
        datetime loaded_at
    }
    DOCUMENTS {
        int id PK
        string case_id FK
        string filename
        string checksum
        string source_type
    }
    PAGES {
        int id PK
        int document_id FK
        int page_number
        string extraction_method
        text extracted_text
    }
    CHUNKS {
        int id PK
        int document_id FK
        int page_id FK
        int chunk_index
        text text
    }
    ASSESSMENTS {
        int id PK
        string case_id FK
        string requirement_id
        string status
        json result_json
    }
    CASE_RESULTS {
        string case_id PK
        string signature
        json result_json
    }
    DECISIONS {
        string case_id PK
        string signature
        string recommended_action
        json result_json
    }
    WORKUPS {
        string case_id PK
        string signature
        string recommended_action
        json result_json
    }
    ANALYST_OVERRIDES {
        string case_id PK
        string action
        text rationale
        text analyst_note
        datetime updated_at
    }
```

Original documents stay in the `documents` folder. SQLite stores their hashes and derived searchable content. Keeping original and derived data separate lets the interface show both the source file and the exact text used during assessment.

## 8. Interface architecture

```mermaid
flowchart LR
    subgraph Left[Queue panel]
        L1[Search and filters]
        L2[Case ID and merchant]
        L3[Amount, scheme and code]
        L4[Document count and action]
    end

    subgraph Center[Decision workspace]
        C1[Issuer allegation]
        C2[Reason-code standard]
        C3[Transaction facts]
        C4[Evidence requirement matrix]
        C5[Merchant evidence request]
        C6[Editable rationale and action]
    end

    subgraph Right[Source inspector]
        R1[Document tabs]
        R2[Inline PDF or image]
        R3[Cited excerpt]
        R4[Page-bound extracted chunks]
    end

    L2 --> C1
    C4 -->|click citation| R1
    R1 --> R2
    R1 --> R4
    R3 --> C4
    C4 --> C6
```

### Why a three-column layout

The layout keeps the analyst's three working contexts visible at once:

- **Queue context:** what case is next and how urgent or complete it appears.
- **Decision context:** what the rule requires and which requirements are met.
- **Verification context:** where the supporting fact appears in the original submission.

Opening evidence in a separate screen would create repeated context switching. A persistent source inspector lets the analyst verify a citation while keeping the requirement and proposed rationale visible.

### Information hierarchy

| UI decision | Reason |
|---|---|
| Issuer allegation appears first | It frames the actual dispute before the analyst reads merchant evidence. |
| Reason-code standard precedes the evidence matrix | The analyst sees what must be proven before judging individual documents. |
| Status uses text, color and icon | The interface remains readable without relying only on color. |
| Gaps appear directly under the affected requirement | The analyst does not need to infer why a requirement is partial or missing. |
| Citations sit inside each requirement row | Source provenance stays attached to the claim it supports. |
| Merchant requests are highlighted above the editor | A `request_more_evidence` case immediately tells the analyst what to ask for. |
| Rationale and action are editable | The analyst owns the filed response and can correct context the system missed. |
| Override note is stored separately | Human changes remain explainable during review or quality assurance. |

### Supporting an 80-case day

The interface minimizes repeated navigation and writing:

1. Load the fixture queue once.
2. Search or filter without leaving the queue.
3. Read the recommendation and coverage count immediately.
4. Expand verification only when a fact needs confirmation.
5. Edit an already-grounded rationale rather than drafting from scratch.
6. Save an override without destroying the original machine recommendation.

## 9. Manual case intake

```mermaid
flowchart LR
    A[Raw case intake table] --> V[Validate required case fields]
    B[PDF and image uploads] --> T[Validate type and 20 MB limit]
    T --> N[Normalize filename under case ID]
    V --> Q[Persist loaded case]
    N --> Q
    Q --> I[Invalidate earlier results for same case ID]
    I --> C[Place case in analyst queue]
    C --> P[Use the same three-engine pipeline]
```

Manual cases do not use a separate analysis path. They are normalized into the same case shape and then processed by the same engines, cache rules and analyst interface. This prevents the demo-data workflow and real intake workflow from drifting apart.

## 10. API surface

| Method and route | Role in the workflow |
|---|---|
| `POST /api/cases/load` | Import the supplied `cases.json` records into the local queue. |
| `GET /api/cases` | Return compact queue summaries and processing state. |
| `GET /api/cases/{id}` | Return the raw case, engine outputs, document summary and human override. |
| `POST /api/cases/{id}/process` | Run or retrieve the complete three-engine workup. |
| `GET /api/cases/{id}/chunks` | Return extracted chunks for a selected case document. |
| `GET /api/cases/{id}/documents/{filename}` | Stream an authorized case document inline. |
| `POST /api/cases/{id}/override` | Persist the analyst's final action, rationale and note. |
| `POST /api/cases/manual` | Create a raw case and upload its evidence. |

The frontend consumes a single case bundle rather than making separate calls for every engine result. This makes case switching predictable. Original documents and chunks remain separate endpoints because they can be larger and are needed only when the analyst verifies a source.

## 11. Reliability and trust boundaries

```mermaid
flowchart TB
    U[Untrusted issuer and merchant content] --> E[Extraction boundary]
    E --> V[Validated pages, chunks and case facts]
    V --> A[Requirement assessment]
    A --> R[Deterministic rule evaluation]
    R --> W[Grounded rationale]
    W --> H[Human review and override]

    E -. never follow document instructions .-> U
    A -. cannot invent source IDs .-> V
    W -. cannot change recommendation .-> R
```

The system treats document content as data, not instructions. Structured model outputs are constrained by schemas, and evidence pointers are resolved against known database identifiers. The rationale model cannot change the Decision Engine's recommendation. The final human override is stored separately so that the original automated result remains available.

## 12. Key architectural tradeoffs

| Decision | Why it fits this case study | Production evolution |
|---|---|---|
| React plus FastAPI | Clear separation between analyst experience and Python engines. | Serve the built frontend behind an API gateway. |
| SQLite | Simple persistence with no external service for a ten-case local demo. | Move to PostgreSQL for concurrent analysts and stronger migrations. |
| Local documents folder | Easy source inspection and checksum validation. | Move to encrypted object storage with signed URLs and malware scanning. |
| Synchronous processing endpoint | Simple end-to-end execution and clear demo behavior. | Use a job queue, idempotency keys and progress events for long-running cases. |
| Deterministic decision engine | Reproducible recommendations and easier audit. | Add versioned policy deployment and formal rule tests. |
| LLM per requirement | Focused prompts and requirement-level citations. | Batch safe operations where latency and cost measurements justify it. |
| Separate machine result and analyst override | Preserves accountability and supports quality review. | Add roles, approvals, immutable audit events and reason taxonomies. |

## 13. Operational flow

```mermaid
flowchart LR
    A[app start] --> B{Python environment exists?}
    B -->|No| C[Create .venv]
    B -->|Yes| D[Check Python packages]
    C --> D
    D --> E{Frontend packages exist?}
    E -->|No| F[npm install]
    E -->|Yes| G[Start services]
    F --> G
    G --> H[FastAPI at 127.0.0.1:8000]
    G --> I[React at 127.0.0.1:5173]
    J[app stop] --> K[Stop frontend PID]
    J --> L[Stop backend PID]
```

Windows uses `app.cmd` and `app.ps1`; Linux uses `app`. Both launchers maintain separate backend and frontend PID files and logs under `.runtime`, allowing `start`, `stop`, `status` and `restart` without requiring the analyst to manage two terminals.

## 14. Practical evaluation criteria

The architecture should be evaluated on more than whether it produces a plausible recommendation:

- **Traceability:** Can every material claim be opened at its source?
- **Rule fidelity:** Does the action follow the configured satisfaction threshold?
- **Change sensitivity:** Does new evidence invalidate stale analysis?
- **Analyst efficiency:** Can the analyst reach the relevant page or chunk in one click?
- **Human control:** Can the analyst edit and override without losing the automated recommendation?
- **Reproducibility:** Can the same unchanged case reuse the same stored result?
- **Separation of concerns:** Can extraction, policy and writing be reviewed independently?

These criteria guided both the system boundaries and the interface hierarchy.
