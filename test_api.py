import pytest
from pydantic import ValidationError
from app import TransferRequest

def test_transfer_request_valid():
    req = TransferRequest(recipient="ACME Corp", amount=25000.0, currency="USD")
    assert req.recipient == "ACME Corp"
    assert req.amount == 25000.0
    assert req.currency == "USD"

def test_transfer_request_missing_amount():
    with pytest.raises(ValidationError):
        TransferRequest(recipient="ACME Corp")
