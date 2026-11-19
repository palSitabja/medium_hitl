import os
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from dotenv import load_dotenv
from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)

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
