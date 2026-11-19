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
