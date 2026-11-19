# LangGraph Enterprise Human-in-the-Loop with PostgreSQL

Companion MVP repository for the Medium articles:
- **Part 1 (Part-5):** Enterprise Human-in-the-Loop — Surviving Restarts with PostgreSQL Persistence
- **Part 2 (Part-6):** Enterprise Human-in-the-Loop — Exposing Agent Approvals via FastAPI Webhooks

---

## Architecture Overview

```
[Worker 1]                                [PostgreSQL]                               [Worker 2]
Parse Transaction                               │                                         │
       │                                        │                                         │
       ▼                                        │                                         │
human_approval_gate (interrupt) ───────> Save Checkpoint                                  │
       │                                        │                                         │
[Worker 1 Exits]                                │                                         │
                                                │ <────── Inspect State                   │
                                                │ <────── Resume via Command(resume=...)──┘
                                                │                 │
                                                │                 ▼
                                         Update Checkpoint ──> execute_transfer
                                                               (Settled)
```

---

## Quickstart

### 1. Environment Setup

Activate the virtual environment:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Ensure PostgreSQL is running and update `.env` (a working local config is provided by default):
```bash
POSTGRES_DB_URI=postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable
```

*(Optional: If you need a fresh PostgreSQL instance, run `docker compose up -d`)*

---

## Part 1: CLI Worker Persistence

### Option A: Run the End-to-End Demo (1-Click)
```bash
python run_all_demo.py
```
This script runs the initiator worker, inspects the saved checkpoints in PostgreSQL, simulates worker restart, and executes the resume worker.

---

### Option B: Step-by-Step Manual Testing

#### Step 1: Initiate Transaction (Worker 1)
```bash
python step1_initiate.py
```
* **What happens:** The workflow starts, extracts wire transfer details ($25,000 to ACME Corp), reaches `human_approval_gate`, hits `interrupt()`, saves the checkpoint to PostgreSQL, and exits.

#### Step 2: Inspect State from PostgreSQL
```bash
python inspect_state.py tx-10029
```
* **What happens:** Inspects the pending thread without modifying it. Shows the interrupt alert and the raw checkpoint records saved in the database.

#### Step 3: Resume as Reviewer (Worker 2)
```bash
# Approve with modified amount ($20,000)
python step2_resume.py approve 20000.0

# Or reject:
python step2_resume.py reject 0.0
```
* **What happens:** Worker 2 starts fresh, connects to PostgreSQL, loads the paused thread `tx-10029`, injects the manager's decision with `Command(resume=...)`, and finishes execution.

---

## Part 2: FastAPI Webhook Service

### Starting the API Server

```bash
source .venv/bin/activate
uvicorn app:app --reload --port 8000
```

The service will be available at `http://localhost:8000`.

### API Endpoints

#### 1. Initiate Transfer
```bash
curl -X POST "http://localhost:8000/api/transfer/initiate" \
     -H "Content-Type: application/json" \
     -d '{"recipient": "Vendor-ACME-Corp", "amount": 25000.0, "currency": "USD"}'
```

Returns: `202 Accepted` with `thread_id`

#### 2. List Pending Approvals
```bash
curl -X GET "http://localhost:8000/api/reviews/pending"
```

Returns: Array of pending review threads

#### 3. Inspect Thread State
```bash
curl -X GET "http://localhost:8000/api/reviews/{thread_id}"
```

Returns: Thread state with interrupt payload and paused node

#### 4. Resume Workflow (Webhook)
```bash
curl -X POST "http://localhost:8000/api/reviews/{thread_id}/resume" \
     -H "Content-Type: application/json" \
     -d '{
       "action": "approve",
       "updated_amount": 21000.0,
       "reviewer": "Finance Director"
     }'
```

Returns: Final settled workflow state

### Running API Tests

```bash
pytest test_api.py -v
```
