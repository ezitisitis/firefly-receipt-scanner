from datetime import date
from unittest.mock import patch

import pytest

from app import matching
from tests.conftest import mock_response

ACCOUNT = {"id": "1", "name": "Checking", "currency_code": "EUR"}
RECEIPT = {"date": "2025-01-31", "amount": 12.5, "currency": "EUR"}


def split(journal_id, amount, day="2025-01-31", **extra):
    return {
        "group_id": f"g{journal_id}",
        "journal_id": str(journal_id),
        "date": day,
        "amount": amount,
        "currency_code": "EUR",
        "foreign_amount": None,
        "foreign_currency_code": None,
        "description": "Card payment",
        "destination_name": "",
        "category_name": "",
        "budget_name": "",
        "tags": [],
        "has_attachments": False,
        **extra,
    }


@pytest.fixture(autouse=True)
def clear_rates():
    matching._rates.clear()
    yield
    matching._rates.clear()


def find(splits, receipt=RECEIPT, window_days=3):
    with patch.object(matching, "get_account_withdrawals", return_value=splits) as get:
        result = matching.find_matches(receipt, ACCOUNT, window_days)
    return result, get


def test_window_is_passed_to_firefly():
    _, get = find([], window_days=2)
    assert get.call_args.args == ("1", "2025-01-29", "2025-02-02")


def test_exact_amount_ranks_before_closer_date_and_others_dropped():
    result, _ = find(
        [split(1, 12.5, "2025-02-02"), split(2, 12.6), split(3, 12.5, "2025-01-30")]
    )
    assert [c["journal_id"] for c in result] == ["3", "1"]
    assert result[0]["days"] == 1 and result[0]["reason"] == "same amount"


def test_amount_tolerance(monkeypatch):
    monkeypatch.setenv("MATCH_AMOUNT_TOLERANCE", "0.2")
    result, _ = find([split(1, 12.6), split(2, 12.5), split(3, 13)])
    assert [c["journal_id"] for c in result] == ["2", "1"]
    assert result[1]["reason"] == "amount within tolerance"


def test_foreign_amount_on_transaction_is_used():
    receipt = {"date": "2025-01-31", "amount": 500000, "currency": "VND"}
    result, _ = find(
        [split(1, 17.9, foreign_amount=500000.0, foreign_currency_code="VND")],
        receipt,
    )
    assert result[0]["diff"] == 0
    assert "original amount" in result[0]["reason"]


def test_converted_amount_within_percent():
    receipt = {"date": "2025-01-31", "amount": 500000, "currency": "vnd"}
    with patch.object(matching, "get_rate", return_value=0.000036):  # 18 EUR
        result, _ = find([split(1, 18.5), split(2, 25)], receipt)
    assert [c["journal_id"] for c in result] == ["1"]
    assert "converted from VND" in result[0]["reason"]


def test_without_rate_candidates_match_by_date_only():
    receipt = {"date": "2025-01-31", "amount": 500000, "currency": "VND"}
    with patch.object(matching, "get_rate", return_value=None):
        result, _ = find([split(1, 18.5)], receipt)
    assert result[0]["diff"] is None and "date only" in result[0]["reason"]


def test_flags_transactions_with_receipt():
    result, _ = find([split(1, 12.5, has_attachments=True), split(2, 12.5, tags=["automated"])])
    assert all(c["has_receipt"] for c in result)


def test_lookup_failure_returns_no_candidates():
    with patch.object(matching, "get_account_withdrawals", side_effect=RuntimeError):
        assert matching.find_matches(RECEIPT, ACCOUNT, 3) == []


def test_assign_matches_is_one_to_one():
    first = {"candidates": [{**split(1, 1), "diff": 0}]}
    second = {"candidates": [{**split(1, 1), "diff": 0}, {**split(2, 1), "diff": 0.1}]}
    unmatched = {"candidates": [{**split(3, 1), "diff": None}]}
    matching.assign_matches([first, second, unmatched, {}])
    assert first["selected_match"] == "g1:1"
    assert second["selected_match"] == "g2:2"
    assert unmatched["selected_match"] == "new"


def test_get_rate_fetches_and_caches():
    with patch.object(matching.requests, "get") as get:
        get.return_value = mock_response(json_data={"rates": {"EUR": 0.000036}})
        assert matching.get_rate("VND", "EUR") == 0.000036
        assert matching.get_rate("VND", "USD") is None
    get.assert_called_once()
    assert get.call_args.args[0] == "https://open.er-api.com/v6/latest/VND"
    assert ("VND", date.today()) in matching._rates


def test_get_rate_shortcuts(monkeypatch):
    assert matching.get_rate("EUR", "EUR") == 1.0
    assert matching.get_rate("", "EUR") is None
    monkeypatch.setenv("FX_RATES_URL", "")
    assert matching.get_rate("VND", "EUR") is None


def test_get_rate_failure_returns_none():
    with patch.object(matching.requests, "get", side_effect=RuntimeError("down")):
        assert matching.get_rate("VND", "EUR") is None
        assert matching.convert(1, "VND", "EUR") is None
