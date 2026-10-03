"""Run: uv run python -m app.test_parse"""

from .receipt_processing import parse_receipt

RAW = '{"date": "2025-01-31", "amount": 12.5, "store_name": "Rimi", "description": "Groceries", "category": "Groceries", "budget": "Monthly"}'

for text in (RAW, f"```json\n{RAW}\n```", f"```\n{RAW}\n```", f"  {RAW}\n"):
    receipt = parse_receipt(text)
    assert receipt.store_name == "Rimi", text
    assert receipt.amount == 12.5, text
    assert receipt.date == "2025-01-31", text

print("parse_receipt OK")
