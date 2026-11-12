import asyncio
import os
import sys
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from workflow import get_workflow_builder

load_dotenv()

DEFAULT_DB_URI = "postgresql://research:root@localhost:5432/langgraph_hitl?sslmode=disable"
DB_URI = os.getenv("POSTGRES_DB_URI", DEFAULT_DB_URI)


async def inspect_thread(thread_id: str = "tx-10029"):
    print(f"\n=======================================================")
    print(f"Inspecting Checkpoint State for Thread: {thread_id}")
    print(f"=======================================================\n")

    async with AsyncConnectionPool(conninfo=DB_URI, max_size=5, kwargs={"autocommit": True}) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        builder = get_workflow_builder()
        graph = builder.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}

        # 1. State Snapshot via LangGraph API
        snapshot = await graph.aget_state(config)
        print("1. LangGraph State Snapshot:")
        print(f"   - Next Pending Node: {snapshot.next}")
        print(f"   - Values in State: {snapshot.values}")
        if snapshot.tasks:
            for i, task in enumerate(snapshot.tasks):
                print(f"   - Task {i} (id={task.id}, name={task.name}):")
                if task.interrupts:
                    for intr in task.interrupts:
                        print(f"       * Interrupt Payload: {intr.value}")

        # 2. Query Postgres Checkpoint Table directly
        print("\n2. Direct PostgreSQL Checkpoint Table Query:")
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint->>'ts' as timestamp
                    FROM checkpoints
                    WHERE thread_id = %s
                    ORDER BY checkpoint_id ASC
                    """,
                    (thread_id,)
                )
                rows = await cur.fetchall()
                if rows:
                    print(f"   Found {len(rows)} checkpoint snapshots in database:")
                    for r in rows:
                        print(f"   - ID: {r[0]} | Parent: {r[1]} | Timestamp: {r[2]}")
                else:
                    print("   No checkpoints found for this thread in the database.")
    print()


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else "tx-10029"
    asyncio.run(inspect_thread(thread_id=tid))
