import asyncio
import os
import sys
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)


async def resume_transaction(thread_id: str = "tx-10029", action: str = "approve", updated_amount: float = 20000.0):
    print(f"\n=======================================================")
    print(f"[WORKER 2] Reviewer Connecting to Resume Thread: {thread_id}")
    print(f"=======================================================\n")

    async with AsyncConnectionPool(conninfo=DB_URI, max_size=10, kwargs={"autocommit": True}) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        builder = get_workflow_builder()
        graph = builder.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}

        # 1. Inspect current state from PostgreSQL
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            print(f"[WORKER 2] Thread '{thread_id}' has no pending actions or is already completed.")
            print(f"Current State Values: {snapshot.values}")
            return

        print(f"[WORKER 2] Loaded state from PostgreSQL.")
        print(f"  - Paused at: {snapshot.next}")
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            print(f"  - Pending approval request: {snapshot.tasks[0].interrupts[0].value}")

        # 2. Prepare human decision
        human_decision = {
            "action": action,
            "updated_amount": updated_amount,
            "reviewer": "Director of Finance"
        }

        print(f"\n[WORKER 2] Submitting Human Review Decision: {human_decision}")
        print("Resuming execution via Command(resume=...)...")

        # 3. Resume the graph with the Command
        async for event in graph.astream(Command(resume=human_decision), config=config):
            for node_name, output in event.items():
                print(f"  [Event] Node '{node_name}' finished. Output: {output}")

        # 4. Final state verification
        final_snapshot = await graph.aget_state(config)
        print("\n-------------------------------------------------------")
        print("[WORKER 2] Final Workflow State:")
        print(f"  - Status: {final_snapshot.values.get('action_status')}")
        print(f"  - Final Amount: ${final_snapshot.values.get('amount', 0):,.2f} {final_snapshot.values.get('currency')}")
        print(f"  - Recipient: {final_snapshot.values.get('recipient')}")
        print("  - Messages:")
        for msg in final_snapshot.values.get("messages", []):
            role = getattr(msg, "type", "message")
            print(f"     [{role.upper()}]: {msg.content}")
        print("-------------------------------------------------------\n")


if __name__ == "__main__":
    action_arg = sys.argv[1] if len(sys.argv) > 1 else "approve"
    amount_arg = float(sys.argv[2]) if len(sys.argv) > 2 else 20000.0
    asyncio.run(resume_transaction(action=action_arg, updated_amount=amount_arg))
