import asyncio
import uuid
from step1_initiate import initiate_transaction
from inspect_state import inspect_thread
from step2_resume import resume_transaction


async def run_full_demo():
    # Use a unique thread ID for each demo run
    test_thread_id = f"tx-{uuid.uuid4().hex[:6]}"
    print(f"\n###################################################################")
    print(f"# RUNNING END-TO-END DEMO FOR THREAD: {test_thread_id}")
    print(f"###################################################################\n")

    # Step 1: Initiate and pause
    await initiate_transaction(thread_id=test_thread_id)

    # Inspect state in Postgres
    await inspect_thread(thread_id=test_thread_id)

    print(">>> Simulating 2 days passing / process restart... <<<\n")
    await asyncio.sleep(1)

    # Step 2: Fresh worker connects and resumes
    await resume_transaction(thread_id=test_thread_id, action="approve", updated_amount=19500.0)

    # Re-inspect to see final settled state
    await inspect_thread(thread_id=test_thread_id)

    print(f"\n###################################################################")
    print(f"# DEMO FINISHED SUCCESSFULLY!")
    print(f"###################################################################\n")


if __name__ == "__main__":
    asyncio.run(run_full_demo())
