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
