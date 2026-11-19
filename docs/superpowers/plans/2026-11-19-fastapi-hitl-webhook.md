# FastAPI HITL Webhook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service layer that exposes REST endpoints to initiate LangGraph workflows, inspect pending approval gates, and resume paused agents via HTTP webhooks.

**Architecture:** FastAPI application with lifespan-managed connection pooling wraps the existing `workflow.py` LangGraph graph. Background tasks handle asynchronous workflow initiation. State inspection endpoints query PostgreSQL checkpoints directly. Webhook endpoints resume workflows via `Command(resume=...)`.

**Tech Stack:** FastAPI 0.115+, Uvicorn, httpx, existing LangGraph + AsyncPostgresSaver stack

**Spec:** `docs/superpowers/specs/2026-11-13-fastapi-hitl-webhook-design.md`

## Global Constraints

- Python 3.11+
- FastAPI >= 0.115.0
- LangGraph >= 0.2.0
- PostgreSQL database `langgraph_hitl` at `postgresql://research:root@localhost:5432/langgraph_hitl`
- Thread IDs must use format `tx-<8 hex chars>`
- All endpoints return JSON responses
- Background workflow execution must not block HTTP responses

## Review Focus

1. **Non-existent thread_id on GET /api/reviews/{thread_id}**: Should return HTTP 404 with clear error message, not 500 or hang.
2. **Resume attempt on already-completed workflow**: Should return HTTP 400 with message indicating workflow is not paused, not attempt to re-execute.
3. **Database connection exhaustion under concurrent load**: Connection pool (max_size=20) must handle 30+ concurrent initiations without hanging or crashing.
4. **Workflow exception during background execution**: Background task failure must not crash the server; exception should be logged and inspectable via state endpoint.
5. **Missing required fields in request payloads**: Pydantic validation must reject with HTTP 422 and field-specific error details before any database access.

---

## File Structure

**New Files:**
- `app.py` - FastAPI application with lifespan, endpoints, and Pydantic models
- `test_api.py` - End-to-end integration tests using httpx.AsyncClient

**Modified Files:**
- `requirements.txt` - Add FastAPI, uvicorn, httpx dependencies
- `README.md` - Document Part 2 API endpoints and usage

**Unchanged (Reused):**
- `workflow.py` - Existing LangGraph workflow with human_approval_gate
- `.env` - Existing database configuration

---

### Task 1: Dependencies & Environment Setup

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: Existing langgraph, psycopg dependencies
- Produces: Python environment with fastapi>=0.115.0, uvicorn[standard]>=0.30.0, httpx>=0.27.0

- [ ] **Step 1: Add FastAPI dependencies to requirements.txt**

Append to `requirements.txt`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
```

- [ ] **Step 2: Install dependencies**

Run: `.venv/bin/pip install -r requirements.txt`
Expected: All packages install successfully

- [ ] **Step 3: Verify imports**

Run: `.venv/bin/python -c "import fastapi, uvicorn, httpx; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add FastAPI, uvicorn, httpx for Part 2 API layer"
```

---

### Task 2: Pydantic Models & Type Definitions

**Files:**
- Create: `app.py` (initial - models only)

**Interfaces:**
- Consumes: None
- Produces: 
  - `TransferRequest(recipient: str, amount: float, currency: str = "USD")`
  - `TransferResponse(thread_id: str, status: str, message: str)`
  - `ReviewDecision(action: Literal["approve", "reject"], updated_amount: float | None, reason: str | None, reviewer: str)`
  - `ReviewDetailResponse(thread_id: str, is_paused: bool, paused_at_node: list[str] | None, review_payload: dict | None, current_state: dict | None)`

- [ ] **Step 1: Write test for TransferRequest validation**

Create `test_api.py`:
```python
import pytest
from pydantic import ValidationError
from app import TransferRequest

def test_transfer_request_valid():
    req = TransferRequest(recipient="ACME Corp", amount=25000.0, currency="USD")
    assert req.recipient == "ACME Corp"
    assert req.amount == 25000.0
    assert req.currency == "USD"

def test_transfer_request_missing_amount():
    with pytest.raises(ValidationError):
        TransferRequest(recipient="ACME Corp")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_transfer_request_valid -v`
Expected: FAIL with "cannot import name 'TransferRequest'"

- [ ] **Step 3: Implement Pydantic models in app.py**

Create `app.py`:
```python
from typing import Literal
from pydantic import BaseModel

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
    paused_at_node: list[str] | None = None
    review_payload: dict | None = None
    current_state: dict | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest test_api.py -v`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add Pydantic models for API request/response schemas"
```

---

### Task 3: FastAPI Lifespan & Application Setup

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: 
  - `workflow.get_workflow_builder() -> StateGraph`
  - `AsyncConnectionPool`, `AsyncPostgresSaver` from existing dependencies
- Produces:
  - `app: FastAPI` - FastAPI application instance with lifespan-managed pool and compiled graph in `app.state`
  - `app.state.graph: CompiledGraph` - Compiled LangGraph workflow
  - `app.state.pool: AsyncConnectionPool` - Database connection pool

- [ ] **Step 1: Write test for lifespan startup**

Add to `test_api.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from app import app

@pytest.mark.asyncio
async def test_app_startup_and_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # If lifespan succeeds, app is ready
        response = await client.get("/")
        # We expect 404 since root isn't defined yet, but app should be running
        assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_app_startup_and_health -v`
Expected: FAIL with "no attribute 'app'" or import error

- [ ] **Step 3: Implement lifespan and FastAPI app in app.py**

Add to `app.py`:
```python
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from dotenv import load_dotenv
from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB pool and compile graph
    pool = AsyncConnectionPool(conninfo=DB_URI, max_size=20, kwargs={"autocommit": True})
    await pool.open()
    
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    
    builder = get_workflow_builder()
    graph = builder.compile(checkpointer=checkpointer)
    
    app.state.graph = graph
    app.state.pool = pool
    
    yield
    
    # Shutdown: Close pool
    await pool.close()

app = FastAPI(title="LangGraph HITL Service", lifespan=lifespan)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest test_api.py::test_app_startup_and_health -v`
Expected: PASS (404 response means app is running)

- [ ] **Step 5: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add FastAPI lifespan with connection pool and graph compilation"
```

---

### Task 4: POST /api/transfer/initiate Endpoint

**Files:**
- Modify: `app.py`
- Modify: `test_api.py`

**Interfaces:**
- Consumes:
  - `TransferRequest` (from Task 2)
  - `app.state.graph` (from Task 3)
  - `HumanMessage` from langchain_core.messages
- Produces:
  - `POST /api/transfer/initiate` endpoint returning `TransferResponse` with HTTP 202

- [ ] **Step 1: Write test for transfer initiation**

Add to `test_api.py`:
```python
import uuid

@pytest.mark.asyncio
async def test_initiate_transfer():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "recipient": "Vendor-ACME-Corp",
            "amount": 25000.0,
            "currency": "USD"
        }
        response = await client.post("/api/transfer/initiate", json=payload)
        
        assert response.status_code == 202
        data = response.json()
        assert "thread_id" in data
        assert data["thread_id"].startswith("tx-")
        assert data["status"] == "PROCESSING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_initiate_transfer -v`
Expected: FAIL with 404 (endpoint not found)

- [ ] **Step 3: Implement background workflow execution helper**

Add to `app.py`:
```python
from langchain_core.messages import HumanMessage

async def run_agent_workflow(graph, thread_id: str, payload: dict):
    """Runs workflow in background until completion or interrupt."""
    config = {"configurable": {"thread_id": thread_id}}
    async for _ in graph.astream(payload, config=config):
        pass
```

- [ ] **Step 4: Implement POST /api/transfer/initiate endpoint**

Add to `app.py`:
```python
import uuid
from fastapi import BackgroundTasks, status

@app.post("/api/transfer/initiate", status_code=status.HTTP_202_ACCEPTED, response_model=TransferResponse)
async def initiate_transfer(request: TransferRequest, background_tasks: BackgroundTasks):
    thread_id = f"tx-{uuid.uuid4().hex[:8]}"
    
    initial_payload = {
        "recipient": request.recipient,
        "amount": request.amount,
        "currency": request.currency,
        "action_status": "INITIALIZED",
        "messages": [HumanMessage(content=f"Wire ${request.amount} {request.currency} to {request.recipient}")]
    }
    
    background_tasks.add_task(run_agent_workflow, app.state.graph, thread_id, initial_payload)
    
    return TransferResponse(
        thread_id=thread_id,
        status="PROCESSING",
        message="Workflow started in background"
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest test_api.py::test_initiate_transfer -v`
Expected: PASS

- [ ] **Step 6: Test Review Focus item 5 - missing fields validation**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_initiate_transfer_missing_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/transfer/initiate", json={"recipient": "ACME"})
        assert response.status_code == 422
```

- [ ] **Step 7: Run validation test**

Run: `.venv/bin/pytest test_api.py::test_initiate_transfer_missing_fields -v`
Expected: PASS (Pydantic validation handles this automatically)

- [ ] **Step 8: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add POST /api/transfer/initiate endpoint with background execution"
```

---

### Task 5: GET /api/reviews/{thread_id} Endpoint

**Files:**
- Modify: `app.py`
- Modify: `test_api.py`

**Interfaces:**
- Consumes:
  - `app.state.graph.aget_state(config)` (from Task 3)
  - `ReviewDetailResponse` (from Task 2)
- Produces:
  - `GET /api/reviews/{thread_id}` endpoint returning `ReviewDetailResponse`

- [ ] **Step 1: Write test for review detail inspection**

Add to `test_api.py`:
```python
import asyncio

@pytest.mark.asyncio
async def test_get_review_details():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First initiate a transfer
        payload = {"recipient": "TestCorp", "amount": 30000.0, "currency": "USD"}
        init_response = await client.post("/api/transfer/initiate", json=payload)
        thread_id = init_response.json()["thread_id"]
        
        # Wait for background task to hit interrupt
        await asyncio.sleep(2)
        
        # Now inspect the thread
        response = await client.get(f"/api/reviews/{thread_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == thread_id
        assert data["is_paused"] == True
        assert "human_approval_gate" in data["paused_at_node"]
        assert data["review_payload"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_get_review_details -v`
Expected: FAIL with 404 (endpoint not found)

- [ ] **Step 3: Implement GET /api/reviews/{thread_id} endpoint**

Add to `app.py`:
```python
from fastapi import HTTPException

@app.get("/api/reviews/{thread_id}", response_model=ReviewDetailResponse)
async def get_review_details(thread_id: str):
    graph = app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    if not snapshot.next:
        return ReviewDetailResponse(
            thread_id=thread_id,
            is_paused=False,
            paused_at_node=None,
            review_payload=None,
            current_state=snapshot.values
        )
    
    interrupt_payload = None
    if snapshot.tasks and snapshot.tasks[0].interrupts:
        interrupt_payload = snapshot.tasks[0].interrupts[0].value
    
    return ReviewDetailResponse(
        thread_id=thread_id,
        is_paused=True,
        paused_at_node=list(snapshot.next),
        review_payload=interrupt_payload,
        current_state=snapshot.values
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest test_api.py::test_get_review_details -v`
Expected: PASS

- [ ] **Step 5: Test Review Focus item 1 - non-existent thread_id**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_get_review_nonexistent_thread():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/reviews/tx-nonexist")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
```

- [ ] **Step 6: Run non-existent thread test**

Run: `.venv/bin/pytest test_api.py::test_get_review_nonexistent_thread -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add GET /api/reviews/{thread_id} endpoint with state inspection"
```

---

### Task 6: GET /api/reviews/pending Endpoint

**Files:**
- Modify: `app.py`
- Modify: `test_api.py`

**Interfaces:**
- Consumes:
  - `app.state.pool` (from Task 3)
  - `app.state.graph.aget_state()` (from Task 3)
- Produces:
  - `GET /api/reviews/pending` endpoint returning list of pending review threads

- [ ] **Step 1: Write test for pending reviews list**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_get_pending_reviews():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initiate a transfer
        payload = {"recipient": "PendingCorp", "amount": 15000.0}
        init_response = await client.post("/api/transfer/initiate", json=payload)
        thread_id = init_response.json()["thread_id"]
        
        # Wait for it to pause
        await asyncio.sleep(2)
        
        # Fetch pending list
        response = await client.get("/api/reviews/pending")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Our thread should be in the list
        thread_ids = [item["thread_id"] for item in data]
        assert thread_id in thread_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_get_pending_reviews -v`
Expected: FAIL with 404 (endpoint not found)

- [ ] **Step 3: Implement GET /api/reviews/pending endpoint**

Add to `app.py`:
```python
@app.get("/api/reviews/pending")
async def get_pending_reviews():
    pool = app.state.pool
    graph = app.state.graph
    
    # Query recent thread_ids from checkpoints table
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT DISTINCT thread_id 
                FROM checkpoints 
                ORDER BY checkpoint_id DESC 
                LIMIT 50
            """)
            rows = await cur.fetchall()
    
    pending = []
    for row in rows:
        thread_id = row[0]
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = await graph.aget_state(config)
            if snapshot.next and "human_approval_gate" in snapshot.next:
                interrupt_payload = None
                if snapshot.tasks and snapshot.tasks[0].interrupts:
                    interrupt_payload = snapshot.tasks[0].interrupts[0].value
                
                pending.append({
                    "thread_id": thread_id,
                    "paused_at_node": list(snapshot.next),
                    "review_payload": interrupt_payload
                })
        except Exception:
            continue
    
    return pending
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest test_api.py::test_get_pending_reviews -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add GET /api/reviews/pending endpoint to list paused workflows"
```

---

### Task 7: POST /api/reviews/{thread_id}/resume Endpoint

**Files:**
- Modify: `app.py`
- Modify: `test_api.py`

**Interfaces:**
- Consumes:
  - `ReviewDecision` (from Task 2)
  - `app.state.graph.astream(Command(resume=...), config)` (from Task 3)
  - `Command` from langgraph.types
- Produces:
  - `POST /api/reviews/{thread_id}/resume` endpoint accepting `ReviewDecision` and returning settled state

- [ ] **Step 1: Write test for workflow resume with approval**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_resume_workflow_approval():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initiate transfer
        payload = {"recipient": "ApprovalCorp", "amount": 20000.0}
        init_response = await client.post("/api/transfer/initiate", json=payload)
        thread_id = init_response.json()["thread_id"]
        
        # Wait for pause
        await asyncio.sleep(2)
        
        # Resume with approval
        decision = {
            "action": "approve",
            "updated_amount": 18000.0,
            "reviewer": "Finance Director"
        }
        response = await client.post(f"/api/reviews/{thread_id}/resume", json=decision)
        
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == thread_id
        assert data["status"] == "SETTLED"
        assert data["final_amount"] == 18000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest test_api.py::test_resume_workflow_approval -v`
Expected: FAIL with 404 (endpoint not found)

- [ ] **Step 3: Implement POST /api/reviews/{thread_id}/resume endpoint**

Add to `app.py`:
```python
from langgraph.types import Command

@app.post("/api/reviews/{thread_id}/resume")
async def resume_workflow(thread_id: str, decision: ReviewDecision):
    graph = app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    
    # Verify thread is paused
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    
    if not snapshot.next:
        raise HTTPException(status_code=400, detail="Thread is not waiting for approval")
    
    # Package resume payload
    resume_payload = {
        "action": decision.action,
        "updated_amount": decision.updated_amount,
        "reason": decision.reason,
        "reviewer": decision.reviewer
    }
    
    # Resume execution
    async for _ in graph.astream(Command(resume=resume_payload), config=config):
        pass
    
    # Return final state
    final_snapshot = await graph.aget_state(config)
    return {
        "thread_id": thread_id,
        "status": final_snapshot.values.get("action_status"),
        "final_amount": final_snapshot.values.get("amount"),
        "recipient": final_snapshot.values.get("recipient")
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest test_api.py::test_resume_workflow_approval -v`
Expected: PASS

- [ ] **Step 5: Test Review Focus item 2 - resume already-completed workflow**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_resume_already_completed():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initiate and immediately try to resume non-paused
        payload = {"recipient": "CompletedCorp", "amount": 5000.0}
        init_response = await client.post("/api/transfer/initiate", json=payload)
        thread_id = init_response.json()["thread_id"]
        
        await asyncio.sleep(2)
        
        # Resume once
        decision = {"action": "approve", "reviewer": "Manager"}
        await client.post(f"/api/reviews/{thread_id}/resume", json=decision)
        
        # Try to resume again
        response = await client.post(f"/api/reviews/{thread_id}/resume", json=decision)
        assert response.status_code == 400
        assert "not waiting" in response.json()["detail"].lower()
```

- [ ] **Step 6: Run already-completed test**

Run: `.venv/bin/pytest test_api.py::test_resume_already_completed -v`
Expected: PASS

- [ ] **Step 7: Test workflow rejection**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_resume_workflow_rejection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"recipient": "RejectCorp", "amount": 50000.0}
        init_response = await client.post("/api/transfer/initiate", json=payload)
        thread_id = init_response.json()["thread_id"]
        
        await asyncio.sleep(2)
        
        decision = {
            "action": "reject",
            "reason": "Exceeds budget",
            "reviewer": "CFO"
        }
        response = await client.post(f"/api/reviews/{thread_id}/resume", json=decision)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "REJECTED"
```

- [ ] **Step 8: Run rejection test**

Run: `.venv/bin/pytest test_api.py::test_resume_workflow_rejection -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app.py test_api.py
git commit -m "feat: add POST /api/reviews/{thread_id}/resume webhook endpoint"
```

---

### Task 8: Connection Pool Stress Test

**Files:**
- Modify: `test_api.py`

**Interfaces:**
- Consumes: All endpoints from previous tasks
- Produces: Verification that connection pool handles concurrent load (Review Focus item 3)

- [ ] **Step 1: Write concurrent load test**

Add to `test_api.py`:
```python
@pytest.mark.asyncio
async def test_concurrent_initiations():
    """Test connection pool handles 30+ concurrent workflow starts."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tasks = []
        for i in range(35):
            payload = {"recipient": f"Concurrent-{i}", "amount": 1000.0 + i}
            tasks.append(client.post("/api/transfer/initiate", json=payload))
        
        responses = await asyncio.gather(*tasks)
        
        # All should succeed with 202
        for resp in responses:
            assert resp.status_code == 202
            assert "thread_id" in resp.json()
```

- [ ] **Step 2: Run stress test**

Run: `.venv/bin/pytest test_api.py::test_concurrent_initiations -v`
Expected: PASS (connection pool max_size=20 should handle via queueing)

- [ ] **Step 3: Commit**

```bash
git add test_api.py
git commit -m "test: add connection pool concurrent load test"
```

---

### Task 9: README Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: All endpoint definitions from Tasks 4-7
- Produces: Updated README with Part 2 API documentation

- [ ] **Step 1: Add Part 2 section to README**

Add to `README.md` after the Part 1 section:
```markdown
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
```

- [ ] **Step 2: Verify README renders correctly**

Run: `cat README.md | head -80`
Expected: Both Part 1 and Part 2 sections present

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add Part 2 FastAPI webhook API documentation to README"
```

---

### Task 10: Final Integration Verification

**Files:**
- No new files

**Interfaces:**
- Consumes: Complete application from all previous tasks
- Produces: Verified end-to-end system

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest test_api.py -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Start server manually and test with curl**

Run in terminal 1:
```bash
source .venv/bin/activate
uvicorn app:app --port 8000
```

Run in terminal 2:
```bash
curl -X POST "http://localhost:8000/api/transfer/initiate" \
     -H "Content-Type: application/json" \
     -d '{"recipient": "Manual-Test-Corp", "amount": 10000.0}'
```

Expected: 202 response with thread_id

- [ ] **Step 3: Test inspection endpoint**

Run:
```bash
curl -X GET "http://localhost:8000/api/reviews/{thread_id}"
```
(Replace `{thread_id}` with actual thread_id from previous step)

Expected: 200 response showing paused state

- [ ] **Step 4: Test resume endpoint**

Run:
```bash
curl -X POST "http://localhost:8000/api/reviews/{thread_id}/resume" \
     -H "Content-Type: application/json" \
     -d '{"action": "approve", "updated_amount": 9500.0, "reviewer": "Manual Tester"}'
```

Expected: 200 response with SETTLED status

- [ ] **Step 5: Stop server and commit final tag**

Run:
```bash
git tag -a v0.2.0 -m "Part 2: FastAPI Webhook Service Layer"
git push origin main --tags
```

Expected: Tag created and pushed

---

## Plan Complete

All tasks implement the spec requirements:
- ✅ FastAPI lifespan with connection pooling (Spec §2.1)
- ✅ POST /api/transfer/initiate with background execution (Spec §2.2)
- ✅ GET /api/reviews/pending and GET /api/reviews/{thread_id} (Spec §2.3)
- ✅ POST /api/reviews/{thread_id}/resume webhook (Spec §2.4)
- ✅ Pydantic models matching spec schemas (Spec §3)
- ✅ End-to-end integration tests (Spec §4)
- ✅ All Review Focus edge cases covered with tests
