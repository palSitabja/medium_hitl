from typing import Literal
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.types import interrupt, Command


# =====================================================================
# State Definition
# =====================================================================
class TransactionState(MessagesState):
    recipient: str
    amount: float
    currency: str
    action_status: str


# =====================================================================
# Workflow Nodes
# =====================================================================
def parse_transaction(state: TransactionState):
    """Parses intent and extracts wire transfer parameters."""
    print("  -> [Node: parse_transaction] Extracting transfer details...")
    # Simulated extraction (in real apps, an LLM call or tool call)
    last_msg = state["messages"][-1].content
    return {
        "recipient": "Vendor-ACME-Corp",
        "amount": 25000.00,
        "currency": "USD",
        "action_status": "PENDING_APPROVAL",
        "messages": [AIMessage(content=f"Prepared wire transfer: $25,000.00 to Vendor-ACME-Corp. Requesting manager sign-off.")]
    }


def human_approval_gate(state: TransactionState):
    """
    Enterprise Human-in-the-Loop Interrupt Gate.
    The graph stops execution here and commits its checkpoint snapshot to PostgreSQL.
    """
    print("  -> [Node: human_approval_gate] Entering interrupt gate...")

    # Surface payload to human reviewer (surfaced via state_snapshot.tasks[0].interrupts[0].value)
    decision = interrupt({
        "alert": "HIGH_VALUE_TRANSACTION",
        "recipient": state["recipient"],
        "amount": state["amount"],
        "currency": state["currency"],
        "risk_score": 0.88,
        "required_role": "FINANCE_DIRECTOR"
    })

    # The value of `decision` comes from Command(resume=<payload>)
    print(f"  -> [Node: human_approval_gate] Resumed with decision: {decision}")
    review_status = decision.get("action", "reject")

    if review_status == "approve":
        # Reviewer can optionally edit/negotiate the amount before approving
        approved_amount = float(decision.get("updated_amount", state["amount"]))
        return {
            "amount": approved_amount,
            "action_status": "APPROVED",
            "messages": [AIMessage(content=f"Human approved wire transfer for ${approved_amount:,.2f} {state['currency']}.")]
        }
    else:
        reason = decision.get("reason", "Rejected by manager")
        return {
            "action_status": "REJECTED",
            "messages": [AIMessage(content=f"Human rejected wire transfer. Reason: {reason}")]
        }


def execute_transfer(state: TransactionState):
    """Executes the transfer with the external banking API if approved."""
    print("  -> [Node: execute_transfer] Reaching settlement...")
    if state["action_status"] == "APPROVED":
        print(f"\n[BANK API EXECUTION] Successfully wired ${state['amount']:,.2f} {state['currency']} to {state['recipient']}!\n")
        return {"action_status": "SETTLED"}
    else:
        print(f"\n[BANK API EXECUTION] Transfer cancelled. Status: {state['action_status']}\n")
        return {"action_status": "CANCELLED"}


def route_after_approval(state: TransactionState) -> Literal["execute_transfer", "__end__"]:
    """Conditional routing based on approval status."""
    if state["action_status"] == "APPROVED":
        return "execute_transfer"
    return "__end__"


# =====================================================================
# Build Graph
# =====================================================================
def get_workflow_builder() -> StateGraph:
    builder = StateGraph(TransactionState)
    builder.add_node("parse_transaction", parse_transaction)
    builder.add_node("human_approval_gate", human_approval_gate)
    builder.add_node("execute_transfer", execute_transfer)

    builder.add_edge(START, "parse_transaction")
    builder.add_edge("parse_transaction", "human_approval_gate")
    builder.add_conditional_edges("human_approval_gate", route_after_approval)
    builder.add_edge("execute_transfer", END)
    return builder
