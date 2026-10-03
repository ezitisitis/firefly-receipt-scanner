from unittest.mock import patch

import pytest
import requests

from app import firefly
from app.models import ReceiptModel
from tests.conftest import mock_response

RECEIPT = ReceiptModel(
    date="2025-01-31",
    amount=12.5,
    store_name="Rimi",
    description="Groceries",
    category="Groceries",
    budget="Monthly",
)


def named(*names):
    return {"data": [{"attributes": {"name": name}} for name in names]}


@pytest.mark.parametrize(
    "func, endpoint",
    [
        (firefly.get_firefly_categories, "categories"),
        (firefly.get_firefly_budgets, "budgets"),
        (firefly.get_firefly_asset_accounts, "accounts"),
    ],
)
def test_list_endpoints(func, endpoint):
    with patch.object(firefly.requests, "get") as get:
        get.return_value = mock_response(json_data=named("A", "B"))
        assert func() == ["A", "B"]

    url = get.call_args.args[0]
    assert url == f"https://firefly.test/api/v1/{endpoint}"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer firefly-token"


def test_asset_accounts_filter_by_type():
    with patch.object(firefly.requests, "get") as get:
        get.return_value = mock_response(json_data=named("Cash"))
        firefly.get_firefly_asset_accounts()
    assert get.call_args.kwargs["params"] == {"type": "asset"}


@pytest.mark.parametrize(
    "func",
    [
        firefly.get_firefly_categories,
        firefly.get_firefly_budgets,
        firefly.get_firefly_asset_accounts,
    ],
)
@pytest.mark.parametrize(
    "error", [requests.exceptions.Timeout(), requests.exceptions.ConnectionError()]
)
def test_list_endpoints_return_empty_on_error(func, error):
    with patch.object(firefly.requests, "get", side_effect=error):
        assert func() == []


def test_list_endpoint_http_error_returns_empty():
    response = mock_response(status_code=500)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError()
    with patch.object(firefly.requests, "get", return_value=response):
        assert firefly.get_firefly_categories() == []


def test_create_transaction_payload():
    with patch.object(firefly.requests, "post") as post:
        post.return_value = mock_response(201, {"data": {"id": "42"}})
        result = firefly.create_firefly_transaction(RECEIPT, "Checking")

    assert result == {"data": {"id": "42"}}
    assert post.call_args.args[0] == "https://firefly.test/api/v1/transactions"
    tx = post.call_args.kwargs["json"]["transactions"][0]
    assert tx == {
        "type": "withdrawal",
        "date": "2025-01-31T00:00:00",
        "amount": "12.5",
        "description": "Groceries",
        "destination_name": "Rimi",
        "source_name": "Checking",
        "category_name": "Groceries",
        "budget_name": "Monthly",
        "tags": ["automated"],
    }


def test_create_transaction_invalid_date_uses_today():
    receipt = RECEIPT.model_copy(update={"date": "31/01/2025"})
    with patch.object(firefly.requests, "post") as post:
        post.return_value = mock_response(200, {"data": {"id": "1"}})
        firefly.create_firefly_transaction(receipt)

    tx = post.call_args.kwargs["json"]["transactions"][0]
    assert tx["date"][:4].isdigit() and "T" in tx["date"]
    assert tx["source_name"] == "Cash wallet"


@pytest.mark.parametrize(
    "status, json_data, message",
    [
        (401, None, "Authentication failed"),
        (403, None, "permission"),
        (404, None, "not found"),
        (422, {"message": "bad amount"}, "Validation error: bad amount"),
        (422, {}, "Invalid data provided"),
        (503, None, r"server error \(HTTP 503\)"),
        (418, {"message": "teapot"}, "HTTP 418 - teapot"),
    ],
)
def test_create_transaction_http_errors(status, json_data, message):
    with patch.object(firefly.requests, "post") as post:
        post.return_value = mock_response(status, json_data)
        with pytest.raises(Exception, match=message):
            firefly.create_firefly_transaction(RECEIPT)


def test_create_transaction_unparseable_error_body():
    response = mock_response(418, text="I'm a teapot")
    response.json.side_effect = ValueError()
    with patch.object(firefly.requests, "post", return_value=response):
        with pytest.raises(Exception, match="HTTP 418 - I'm a teapot"):
            firefly.create_firefly_transaction(RECEIPT)


@pytest.mark.parametrize(
    "error, message",
    [
        (requests.exceptions.Timeout(), "timed out"),
        (requests.exceptions.ConnectionError(), "Could not connect"),
        (requests.exceptions.RequestException("boom"), "boom"),
    ],
)
def test_create_transaction_network_errors(error, message):
    with patch.object(firefly.requests, "post", side_effect=error):
        with pytest.raises(Exception, match=message):
            firefly.create_firefly_transaction(RECEIPT)


def test_attach_image():
    with patch.object(firefly.requests, "post") as post:
        post.side_effect = [
            mock_response(200, {"data": {"id": "7"}}),
            mock_response(204),
        ]
        assert firefly.attach_image_to_transaction(99, b"jpeg", "r.jpg") == "7"

    create, upload = post.call_args_list
    assert create.args[0] == "https://firefly.test/api/v1/attachments"
    assert create.kwargs["json"] == {
        "filename": "r.jpg",
        "attachable_type": "TransactionJournal",
        "attachable_id": "99",
    }
    assert upload.args[0] == "https://firefly.test/api/v1/attachments/7/upload"
    assert upload.kwargs["data"] == b"jpeg"
    assert upload.kwargs["headers"]["Content-Type"] == "application/octet-stream"


def test_attach_image_raises_on_failure():
    response = mock_response(500)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    with patch.object(firefly.requests, "post", return_value=response):
        with pytest.raises(requests.exceptions.HTTPError):
            firefly.attach_image_to_transaction(99, b"jpeg", "r.jpg")
