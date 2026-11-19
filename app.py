import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, BackgroundTasks, status, HTTPException
from pydantic import BaseModel
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)

# Global state for graph and pool
_graph = None
_pool = None

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

async def run_agent_workflow(graph, thread_id: str, payload: dict):
    """Runs workflow in background until completion or interrupt."""
    config = {"configurable": {"thread_id": thread_id}}
    async for _ in graph.astream(payload, config=config):
        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _pool
    # Startup: Initialize DB pool and compile graph
    _pool = AsyncConnectionPool(conninfo=DB_URI, max_size=20, kwargs={"autocommit": True})
    await _pool.open()

    checkpointer = AsyncPostgresSaver(_pool)
    await checkpointer.setup()

    builder = get_workflow_builder()
    _graph = builder.compile(checkpointer=checkpointer)

    yield

    # Shutdown: Close pool
    await _pool.close()

app = FastAPI(title="LangGraph HITL Service", lifespan=lifespan)

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

    background_tasks.add_task(run_agent_workflow, _graph, thread_id, initial_payload)

    return TransferResponse(
        thread_id=thread_id,
        status="PROCESSING",
        message="Workflow started in background"
    )

@app.get("/api/reviews/pending")
async def get_pending_reviews():
    pool = _pool
    graph = _graph

    # Query recent thread_ids from checkpoints table
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT thread_id, MAX(checkpoint_id) as max_checkpoint
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY max_checkpoint DESC
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

@app.get("/api/reviews/{thread_id}", response_model=ReviewDetailResponse)
async def get_review_details(thread_id: str):
    graph = _graph
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # Check if thread exists - empty values dict means non-existent thread
    if not snapshot.values:
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

@app.post("/api/reviews/{thread_id}/resume")
async def resume_workflow(thread_id: str, decision: ReviewDecision):
    from langgraph.types import Command
    
    graph = _graph
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
