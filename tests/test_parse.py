import pytest
from pydantic import ValidationError

from app.receipt_processing import parse_receipt

RAW = '{"date": "2025-01-31", "amount": 12.5, "store_name": "Rimi", "description": "Groceries", "category": "Groceries", "budget": "Monthly"}'


@pytest.mark.parametrize(
    "text", [RAW, f"```json\n{RAW}\n```", f"```\n{RAW}\n```", f"  {RAW}\n"]
)
def test_parse_receipt(text):
    receipt = parse_receipt(text)
    assert receipt.store_name == "Rimi"
    assert receipt.amount == 12.5
    assert receipt.date == "2025-01-31"
    assert receipt.budget == "Monthly"


@pytest.mark.parametrize("text", ["", "not json", '{"date": "2025-01-31"}'])
def test_parse_receipt_invalid(text):
    with pytest.raises(ValidationError):
        parse_receipt(text)
