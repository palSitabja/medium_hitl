import pytest
import uuid
from pydantic import ValidationError
from app import TransferRequest, app
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

def test_transfer_request_valid():
    req = TransferRequest(recipient="ACME Corp", amount=25000.0, currency="USD")
    assert req.recipient == "ACME Corp"
    assert req.amount == 25000.0
    assert req.currency == "USD"

def test_transfer_request_missing_amount():
    with pytest.raises(ValidationError):
        TransferRequest(recipient="ACME Corp")

@pytest.mark.asyncio
async def test_app_startup_and_health():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # If lifespan succeeds, app is ready
            response = await client.get("/")
            # We expect 404 since root isn't defined yet, but app should be running
            assert response.status_code == 404

@pytest.mark.asyncio
async def test_initiate_transfer_missing_fields():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/transfer/initiate", json={"recipient": "ACME"})
            assert response.status_code == 422

@pytest.mark.asyncio
async def test_initiate_transfer():
    async with LifespanManager(app):
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

@pytest.mark.asyncio
async def test_get_review_details():
    import asyncio
    async with LifespanManager(app):
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

@pytest.mark.asyncio
async def test_get_review_nonexistent_thread():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/reviews/tx-nonexist")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_get_pending_reviews():
    import asyncio
    async with LifespanManager(app):
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
