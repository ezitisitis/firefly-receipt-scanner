import base64
import importlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_image, mock_response

EXTRACTED = {
    "date": "2025-01-31",
    "amount": 12.5,
    "store_name": "Rimi",
    "description": "Weekly shop",
    "category": "Food",
    "budget": "Monthly",
    "available_categories": ["Food", "Fun"],
    "available_budgets": ["Monthly"],
    "image_base64": base64.b64encode(b"jpeg").decode(),
}
FORM = {
    "date": "2025-01-31",
    "amount": "12.5",
    "store_name": "Rimi",
    "description": "Weekly shop",
    "category": "Food",
    "budget": "Monthly",
    "source_account": "Checking",
}


@pytest.fixture(scope="module")
def app_module():
    # The startup connection check runs at import time
    with patch("app.firefly.requests.get") as get:
        get.return_value = mock_response(json_data={"data": []})
        import app.app

        return importlib.reload(app.app)


@pytest.fixture
def client(app_module):
    return TestClient(app_module.app)


def test_index_lists_accounts(app_module, client):
    with patch.object(
        app_module, "get_firefly_asset_accounts", return_value=["Checking", "Savings"]
    ):
        response = client.get("/")
    assert response.status_code == 200
    assert "Checking" in response.text and "Savings" in response.text


def test_index_default_account(app_module, client):
    with patch.object(app_module, "get_firefly_asset_accounts", return_value=[]):
        response = client.get("/")
    assert "Cash wallet" in response.text


def test_static_files(client):
    assert client.get("/static/manifest.json").status_code == 200


def test_extract_renders_review(app_module, client):
    with patch.object(
        app_module, "extract_receipt_data", AsyncMock(return_value=dict(EXTRACTED))
    ):
        response = client.post(
            "/extract",
            files={"file": ("r.png", make_image(), "image/png")},
            data={"source_account": "Checking"},
        )
    assert response.status_code == 200
    assert 'value="Rimi"' in response.text
    assert 'value="Checking"' in response.text
    assert 'id="attach_receipt"' in response.text


@pytest.mark.parametrize(
    "error, message",
    [
        (TimeoutError(), "operation timed out"),
        (ValueError("LLM exploded"), "LLM exploded"),
    ],
)
def test_extract_errors(app_module, client, error, message):
    with patch.object(app_module, "extract_receipt_data", AsyncMock(side_effect=error)):
        response = client.post(
            "/extract",
            files={"file": ("r.png", make_image(), "image/png")},
            data={"source_account": "Checking"},
        )
    assert message in response.text


def test_extract_requires_file(client):
    response = client.post("/extract", data={"source_account": "Checking"})
    assert response.status_code == 422


def create(app_module, client, result, data):
    with (
        patch.object(
            app_module, "create_transaction_from_data", AsyncMock(return_value=result)
        ) as mock,
        patch.object(app_module, "get_firefly_asset_accounts", return_value=["Checking"]),
    ):
        response = client.post("/create-transaction", data=data)
    return response, mock


def test_create_transaction_success(app_module, client):
    response, mock = create(
        app_module, client, "Transaction created successfully with ID: 1", FORM
    )
    assert "Transaction created successfully!" in response.text
    assert "Attaching the receipt image failed" not in response.text
    data, account, image = mock.call_args.args
    assert data["amount"] == 12.5 and account == "Checking"
    assert image is None


def test_create_transaction_with_attachment(app_module, client):
    form = {**FORM, "attach_receipt": "true", "image_base64": EXTRACTED["image_base64"]}
    _, mock = create(app_module, client, "Transaction created successfully", form)
    assert mock.call_args.args[2] == b"jpeg"


def test_create_transaction_attachment_unchecked(app_module, client):
    form = {**FORM, "image_base64": EXTRACTED["image_base64"]}
    _, mock = create(app_module, client, "Transaction created successfully", form)
    assert mock.call_args.args[2] is None


def test_create_transaction_attachment_failed(app_module, client):
    response, _ = create(
        app_module,
        client,
        "Transaction created successfully (attaching the receipt image failed)",
        FORM,
    )
    assert "Attaching the receipt image failed." in response.text


def test_create_transaction_failure(app_module, client):
    response, _ = create(
        app_module, client, "Failed to create transaction after 3 attempts.", FORM
    )
    assert "Failed to create transaction after 3 attempts." in response.text
    assert "Transaction created successfully!" not in response.text


def test_create_transaction_rejects_invalid_amount(client):
    response = client.post("/create-transaction", data={**FORM, "amount": "abc"})
    assert response.status_code == 422


def test_create_transaction_unexpected_error(app_module, client):
    with patch.object(
        app_module,
        "create_transaction_from_data",
        AsyncMock(side_effect=RuntimeError("kaboom")),
    ):
        response = client.post("/create-transaction", data=FORM)
    assert "kaboom" in response.text


@pytest.mark.parametrize(
    "categories, expected", [(["Food"], True), ([], True), (None, False)]
)
def test_firefly_connection_check(app_module, categories, expected):
    with patch.object(app_module, "get_firefly_categories", return_value=categories):
        assert app_module.test_firefly_connection() is expected


def test_firefly_connection_check_exception(app_module):
    with patch.object(
        app_module, "get_firefly_categories", side_effect=RuntimeError("down")
    ):
        assert app_module.test_firefly_connection() is False
