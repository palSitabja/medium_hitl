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
