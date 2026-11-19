import pytest
from pydantic import ValidationError
from app import TransferRequest, app
from httpx import AsyncClient, ASGITransport

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # If lifespan succeeds, app is ready
        response = await client.get("/")
        # We expect 404 since root isn't defined yet, but app should be running
        assert response.status_code == 404
