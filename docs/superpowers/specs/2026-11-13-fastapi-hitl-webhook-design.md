# Design Document: FastAPI Webhook & Event Bridge for LangGraph HITL

- **Date:** 2026-11-13
- **Topic:** Part 2 (Part-6 Medium Series) - Exposing Agent Approvals via FastAPI Webhooks
- **Repository:** `medium_hitl` (`/Users/sitabjapal/projects/medium_publish/langgraph_postgres_hitl`)
- **Status:** Approved

---

## 1. Context & Motivation

In Part 1 of this enterprise series, we established that LangGraph agents pause at human approval gates (`interrupt()`) and commit their state into PostgreSQL via `AsyncPostgresSaver`.

In production microservice architectures, agents cannot run as interactive CLI scripts. Upstream services (payment gateways, ERP systems, internal portals) initiate processes via HTTP, and human operators approve or modify workflows asynchronously via external webhooks or admin portals.

This design introduces an asynchronous **FastAPI Service Layer** on top of the Part 1 PostgreSQL checkpoint store. It exposes clean REST endpoints to initiate workflows, list and inspect pending approval gates, and resume paused agents via HTTP webhooks.

---

## 2. Architecture & Components

```
┌─────────────────────────────────┐
│     Client / Dashboard          │
└────┬───────────────────────▲────┘
     │ 1. POST /initiate     │ 3. POST /resume
     ▼                       │
┌────────────────────────────┴────┐
│      FastAPI Service (app.py)   │
│  - Lifespan DB Connection Pool  │
│  - Compiled LangGraph Runner    │
│  - BackgroundTasks for Start    │
└────┬───────────────────────▲────┘
     │ astream()             │ Command(resume=...)
     ▼                       │
┌────────────────────────────┴────┐
│   PostgreSQL Checkpointer       │
│   (AsyncPostgresSaver)          │
│   checkpoints, checkpoint_blobs │
└─────────────────────────────────┘
```

### Key Components

1. **FastAPI Lifespan Context (`lifespan`)**:
   - Opens an `AsyncConnectionPool` (max size 20) against `langgraph_hitl` database.
   - Instantiates `AsyncPostgresSaver(pool)` and executes `await checkpointer.setup()`.
   - Compiles `get_workflow_builder().compile(checkpointer=checkpointer)` once at startup.
   - Attaches `graph` and `pool` to `app.state`.
   - Gracefully closes the connection pool upon application shutdown.

2. **Asynchronous Initiation (`POST /api/transfer/initiate`)**:
   - Accepts payload: `recipient` (str), `amount` (float), `currency` (str).
   - Generates unique thread ID `tx-<uuid>`.
   - Dispatches graph execution as a FastAPI `BackgroundTask` so the client receives a fast `202 Accepted` response.
   - Graph streams execution until reaching `human_approval_gate` where `interrupt()` commits state to PostgreSQL and suspends.

3. **State Inspection & Pending Queue (`GET /api/reviews/pending` & `GET /api/reviews/{thread_id}`)**:
   - `GET /api/reviews/{thread_id}`: Inspects `await graph.aget_state({"configurable": {"thread_id": thread_id}})`. Returns whether the thread is paused, the node waiting, and the interrupt payload (alert type, risk score, amount, role).
   - `GET /api/reviews/pending`: Queries the PostgreSQL `checkpoints` table for recent thread IDs with active pending tasks and returns pending review items.

4. **Webhook Resumption (`POST /api/reviews/{thread_id}/resume`)**:
   - Accepts payload: `action` ("approve" | "reject"), `updated_amount` (optional float), `reason` (optional str), `reviewer` (str).
   - Validates that the thread exists and is currently waiting on `human_approval_gate`.
   - Resumes execution via `graph.astream(Command(resume=payload), config=config)`.
   - Waits for completion and returns the final settled workflow state (`SETTLED` or `REJECTED`, final approved amount, message audit trail).

---

## 3. Endpoints & Schemas

### Models (Pydantic v2)
```python
class TransferRequest(BaseModel):
    recipient: str
    amount: float
    currency: str = "USD"

class TransferResponse(BaseModel):
    thread_id: str
    status: str
    message: str

class ReviewDecision(BaseModel):
    action: Literal["approve", "reject"]
    updated_amount: float | None = None
    reason: str | None = None
    reviewer: str

class ReviewDetailResponse(BaseModel):
    thread_id: str
    is_paused: bool
    paused_at_node: list[str] | None
    review_payload: dict | None
    current_state: dict | None
```

---

## 4. Verification & Testing (`test_api.py`)

A full end-to-end integration test will be provided using `httpx.AsyncClient` that executes against the live FastAPI application:
1. `test_initiate_transfer`: Submits transfer and receives `202 Accepted` with `thread_id`.
2. `test_get_pending_and_inspect`: Verifies thread pauses at `human_approval_gate` and matches interrupt payload.
3. `test_resume_approval`: Submits `POST /api/reviews/{thread_id}/resume` with `action="approve"` and updated amount ($21,500.00). Asserts final status is `SETTLED`.
4. `test_resume_rejection`: Submits another transfer, resumes with `action="reject"`, asserts final status is `REJECTED`.
5. `test_resume_non_paused`: Asserts resuming an already completed or non-existent thread returns HTTP 400.

---

## 5. File Changes

- `requirements.txt`: Append `fastapi`, `uvicorn[standard]`, `httpx`.
- `app.py`: The FastAPI service implementation.
- `test_api.py`: Automated integration test runner.
- `README.md`: Updated to document both Part 1 (CLI worker persistence) and Part 2 (FastAPI Webhooks & REST endpoints).
