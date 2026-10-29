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


ACCOUNTS = [{"id": "1", "name": "Checking", "currency_code": "EUR"}]


@pytest.fixture(autouse=True)
def accounts(app_module):
    with patch.object(
        app_module, "get_firefly_asset_accounts_detailed", return_value=ACCOUNTS
    ):
        yield


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


CANDIDATE = {
    "group_id": "5",
    "journal_id": "100",
    "date": "2025-01-30",
    "amount": 12.5,
    "currency_code": "EUR",
    "description": "CARD 1234 RIMI",
    "destination_name": "Rimi",
    "category_name": "",
    "budget_name": "",
    "diff": 0,
    "days": 1,
    "reason": "same amount",
    "has_receipt": False,
}


def extract(app_module, client, data, files=1, extracted=None, find=()):
    with (
        patch.object(
            app_module,
            "extract_receipt_data",
            AsyncMock(side_effect=lambda f: dict(extracted or EXTRACTED)),
        ),
        patch.object(app_module, "find_matches", return_value=list(find)) as mock,
    ):
        response = client.post(
            "/extract",
            files=[("file", (f"r{i}.png", make_image(), "image/png")) for i in range(files)],
            data={"source_account": "Checking", **data},
        )
    return response, mock


def test_extract_without_matching_skips_lookup(app_module, client):
    response, find = extract(app_module, client, {})
    find.assert_not_called()
    assert "Existing transactions" not in response.text


def test_extract_with_matching_preselects_candidate(app_module, client):
    response, find = extract(
        app_module, client, {"match_existing": "true", "window_days": "5"}, find=[CANDIDATE]
    )
    assert find.call_args.args[1] == ACCOUNTS[0] and find.call_args.args[2] == 5
    assert 'value="5:100" checked' in response.text
    # Blank category/budget are pre-ticked for overwriting, filled ones are not
    assert 'value="category" checked' in response.text
    assert 'value="description">' in response.text


def test_extract_with_matching_no_candidates(app_module, client):
    response, _ = extract(app_module, client, {"match_existing": "true"})
    assert "No matching transaction found." in response.text
    assert 'id="match_new" value="new" checked' in response.text


@pytest.mark.parametrize("rate, amount", [(0.000036, 'value="18.0"'), (None, 'value=""')])
def test_extract_converts_foreign_currency(app_module, client, rate, amount):
    with patch.object(app_module, "convert", return_value=rate and 500000 * rate):
        response, _ = extract(
            app_module, client, {}, extracted={**EXTRACTED, "amount": 500000, "currency": "VND"}
        )
    assert amount in response.text
    assert 'name="foreign_amount" value="500000"' in response.text
    assert 'name="foreign_currency" value="VND"' in response.text


def test_extract_bulk_renders_rows_with_errors(app_module, client):
    calls = iter([dict(EXTRACTED), RuntimeError("blurry")])

    def fake_extract(f):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    with (
        patch.object(app_module, "extract_receipt_data", AsyncMock(side_effect=fake_extract)),
        patch.object(app_module, "find_matches", return_value=[]),
    ):
        response = client.post(
            "/extract",
            files=[("file", (f"r{i}.png", make_image(), "image/png")) for i in range(2)],
            data={"source_account": "Checking"},
        )
    assert 'action="/create-transactions"' in response.text
    assert 'name="count" value="2"' in response.text
    assert 'name="r0_store_name"' in response.text
    assert "Could not read this receipt: blurry" in response.text
    assert 'name="r1_match" value="skip"' in response.text


def test_create_transaction_updates_match(app_module, client):
    form = {**FORM, "match": "5:100", "overwrite_100": ["category", "budget"]}
    with (
        patch.object(
            app_module, "update_transaction_from_data", AsyncMock(return_value="Transaction 5 updated")
        ) as update,
        patch.object(app_module, "get_firefly_asset_accounts", return_value=["Checking"]),
    ):
        response = client.post("/create-transaction", data=form)
    assert "Existing transaction updated with the receipt!" in response.text
    data, group_id, journal_id, overwrite, image = update.call_args.args
    assert (group_id, journal_id, overwrite, image) == ("5", "100", ["category", "budget"], None)
    assert data["store_name"] == "Rimi"


def bulk(app_module, client, data, create_result="Transaction created successfully"):
    with (
        patch.object(
            app_module, "create_transaction_from_data", AsyncMock(return_value=create_result)
        ) as create,
        patch.object(
            app_module, "update_transaction_from_data", AsyncMock(return_value="Transaction 5 updated")
        ) as update,
        patch.object(app_module, "get_firefly_asset_accounts", return_value=["Checking"]),
    ):
        response = client.post("/create-transactions", data=data)
    return response, create, update


def row(i, **extra):
    return {f"r{i}_{k}": v for k, v in {**FORM, "filename": f"r{i}.png", **extra}.items()}


def test_create_transactions_mixed(app_module, client):
    data = {
        "count": "4",
        "source_account": "Checking",
        **row(0, attach_receipt="true", image_base64=EXTRACTED["image_base64"]),
        **row(1, match="5:100", overwrite_100=["budget"]),
        **row(2, match="skip"),
        **row(3, match="6:100"),
    }
    response, create, update = bulk(app_module, client, data)
    assert "1 created, 1 matched and updated, 1 skipped." in response.text
    assert "r3.png: its transaction is already matched by another receipt" in response.text
    assert create.call_args.args[1:] == ("Checking", b"jpeg")
    assert update.call_args.args[1:] == ("5", "100", ["budget"], None)


def test_create_transactions_reports_failures(app_module, client):
    data = {"count": "2", "source_account": "Checking", **row(0), **row(1, amount="")}
    response, _, _ = bulk(
        app_module, client, data, "Failed to create transaction after 3 attempts."
    )
    assert "0 created, 0 matched and updated, 0 skipped." in response.text
    assert "r0.png: Failed to create transaction after 3 attempts." in response.text
    assert "r1.png: the amount is missing" in response.text


def test_create_transactions_attachment_failed(app_module, client):
    data = {"count": "1", "source_account": "Checking", **row(0)}
    response, _, _ = bulk(
        app_module, client, data, "Transaction created (attaching the receipt image failed)"
    )
    assert "1 created" in response.text
    assert "r0.png: attaching the receipt image failed" in response.text
