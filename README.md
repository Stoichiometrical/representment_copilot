# Representment Desk

See [system_architecture.md](system_architecture.md) for the complete visual system, workflow, data and interface architecture.

An analyst workspace built around the supplied three-stage chargeback pipeline:

1. `evidence_engine.py` extracts and assesses evidence with validated document/page/chunk pointers.
2. `decision_engine.py` applies deterministic scheme logic and assesses whether gaps are recoverable.
3. `workup_engine.py` produces the reason-code summary, evidence matrix, editable 3–5 sentence rationale, recommended action and specific merchant requests.

## Run in under 10 minutes

Prerequisites: Python 3.11+ and Node.js 20+.

1. Copy `.env.example` to `.env` and add `OPENAI_API_KEY`. This folder already contains `.env` when delivered from the prepared workspace.
2. From this folder, run:

   **Windows**

   ```powershell
   app start
   ```

   **Linux/macOS**

   ```bash
   chmod +x app
   ./app start
   ```

3. Open <http://127.0.0.1:5173> and click **Load cases**.

Stop both services with `app stop` on Windows or `./app stop` on Linux. `status` and `restart` are also supported. The launcher creates `.venv`, installs missing Python and frontend packages, starts FastAPI on port 8000 and Vite on port 5173, and writes logs under `.runtime/logs/`.

## Analyst workflow

- **Load cases** imports the ten supplied records from `cases.json` into the local queue.
- Select a case and click **Process case**. The first run processes its evidence; unchanged inputs reuse signature-validated SQLite results.
- Review the rule, evidence status and gaps. Every citation opens the matching original document, page, extracted chunk and supporting excerpt in the source inspector.
- Edit the rationale, override the action when necessary, record an analyst note, and save the decision.
- **Add case** opens the raw intake table for transaction metadata, issuer narrative and evidence uploads.

## Link to Video Demo 
-[https://drive.google.com/drive/folders/1vfy9kADyBmLgAmabZTB-ZCJUXH6DGPHI?usp=sharing](https://drive.google.com/drive/folders/1vfy9kADyBmLgAmabZTB-ZCJUXH6DGPHI?usp=sharing)

## API

FastAPI documentation is available at <http://127.0.0.1:8000/docs>.

| Endpoint | Purpose |
|---|---|
| `POST /api/cases/load` | Import `cases.json` into the analyst queue |
| `GET /api/cases` | List loaded cases and processing state |
| `POST /api/cases/{id}/process` | Run or retrieve the three-stage pipeline |
| `GET /api/cases/{id}` | Retrieve case, evidence, decision, workup and override |
| `GET /api/cases/{id}/chunks` | Inspect extracted chunks for a document |
| `GET /api/cases/{id}/documents/{filename}` | Open an original evidence file |
| `POST /api/cases/{id}/override` | Save analyst action/rationale override |
| `POST /api/cases/manual` | Add a raw case and upload evidence |

SQLite data is stored at `data/evidence_engine.db`. Human-readable engine outputs are written under `data/results`, `data/decisions` and `data/workups`.
