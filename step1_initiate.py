import asyncio
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)


async def initiate_transaction(thread_id: str = "tx-10029"):
    print(f"\n=======================================================")
    print(f"[WORKER 1] Starting Wire Transfer Flow for Thread: {thread_id}")
    print(f"=======================================================\n")

    # Enterprise connection pooling
    async with AsyncConnectionPool(conninfo=DB_URI, max_size=10, kwargs={"autocommit": True}) as pool:
        checkpointer = AsyncPostgresSaver(pool)

        # Provisions checkpoints, checkpoint_writes, checkpoint_blobs tables if not present
        await checkpointer.setup()

        builder = get_workflow_builder()
        graph = builder.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "messages": [HumanMessage(content="Wire $25,000 to ACME Corp for data center server racks.")],
            "recipient": "",
            "amount": 0.0,
            "currency": "USD",
            "action_status": "INITIALIZED"
        }

        print("[WORKER 1] Streaming graph execution...")
        async for event in graph.astream(initial_state, config=config):
            for node_name, output in event.items():
                print(f"  [Event] Node '{node_name}' finished. Output: {output}")

        # Check graph state after interruption
        snapshot = await graph.aget_state(config)

        print("\n-------------------------------------------------------")
        print("[WORKER 1] Workflow has paused at Interrupt Gate!")
        print(f"  - Next pending node: {snapshot.next}")
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            interrupt_val = snapshot.tasks[0].interrupts[0].value
            print(f"  - Interrupt Payload: {interrupt_val}")
        print("-------------------------------------------------------")
        print(">>> Worker 1 process now exits safely. The state is committed in PostgreSQL! <<<\n")


if __name__ == "__main__":
    asyncio.run(initiate_transaction())
