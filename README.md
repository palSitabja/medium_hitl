# LangGraph Enterprise Human-in-the-Loop with PostgreSQL

Companion MVP repository for the Medium article:
**"LangGraph (Part-5): Enterprise Human-in-the-Loop — Surviving Restarts with PostgreSQL Persistence"**

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

## Running the MVP

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
# medium_hitl
