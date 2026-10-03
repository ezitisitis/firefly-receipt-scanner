import base64
import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile

from app import receipt_processing as rp
from tests.conftest import make_image

TODAY = datetime.now().strftime("%Y-%m-%d")
LLM_REPLY = {
    "date": "2025-01-31",
    "amount": 12.5,
    "store_name": "Rimi",
    "description": "Groceries",
    "category": "Food",
    "budget": "Monthly",
}
RECEIPT_DATA = {**LLM_REPLY, "source_account": "Checking"}
CREATED = {
    "data": {
        "id": "42",
        "attributes": {"transactions": [{"transaction_journal_id": "100"}]},
    }
}


def upload():
    return UploadFile(file=io.BytesIO(make_image()), filename="receipt.png")


def llm_client(content):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=content))
    ]
    return client


@pytest.fixture
def firefly_lists():
    with (
        patch.object(rp, "get_firefly_categories", return_value=["Food", "Fun"]),
        patch.object(rp, "get_firefly_budgets", return_value=["Monthly"]),
    ):
        yield


@pytest.fixture
def no_sleep():
    with patch.object(rp.time, "sleep") as sleep:
        yield sleep


def test_llm_client_uses_settings():
    rp.get_llm_client.cache_clear()
    try:
        client = rp.get_llm_client()
        assert client.api_key == "llm-key"
        assert str(client.base_url).startswith("https://generativelanguage")
    finally:
        rp.get_llm_client.cache_clear()


async def test_extract_receipt_data(firefly_lists):
    client = llm_client(json.dumps(LLM_REPLY))
    with patch.object(rp, "get_llm_client", return_value=client):
        data = await rp.extract_receipt_data(upload())

    assert {k: data[k] for k in LLM_REPLY} == LLM_REPLY
    assert data["available_categories"] == ["Food", "Fun"]
    assert data["available_budgets"] == ["Monthly"]
    assert base64.b64decode(data["image_base64"])[:2] == b"\xff\xd8"  # JPEG

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    text, image = kwargs["messages"][0]["content"]
    assert "Food, Fun" in text["text"]
    assert "Monthly" in text["text"]
    assert TODAY in text["text"]
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_extract_uses_defaults_when_firefly_unavailable():
    client = llm_client(json.dumps(LLM_REPLY))
    with (
        patch.object(rp, "get_firefly_categories", return_value=[]),
        patch.object(rp, "get_firefly_budgets", return_value=[]),
        patch.object(rp, "get_llm_client", return_value=client),
    ):
        data = await rp.extract_receipt_data(upload())

    assert "Groceries" in data["available_categories"]
    assert data["available_budgets"] == ["Monthly", "Weekly", "Other"]


async def test_extract_invalid_date_falls_back_to_today(firefly_lists):
    reply = {**LLM_REPLY, "date": "31.01.2025"}
    with patch.object(rp, "get_llm_client", return_value=llm_client(json.dumps(reply))):
        data = await rp.extract_receipt_data(upload())
    assert data["date"] == TODAY


async def test_extract_timeout_becomes_timeout_error(firefly_lists):
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("Request timeout")
    with patch.object(rp, "get_llm_client", return_value=client):
        with pytest.raises(TimeoutError):
            await rp.extract_receipt_data(upload())


async def test_extract_reraises_llm_errors(firefly_lists):
    with patch.object(rp, "get_llm_client", return_value=llm_client("garbage")):
        with pytest.raises(Exception):
            await rp.extract_receipt_data(upload())


async def test_create_transaction(no_sleep):
    with (
        patch.object(rp, "create_firefly_transaction", return_value=CREATED) as create,
        patch.object(rp, "attach_image_to_transaction") as attach,
    ):
        result = await rp.create_transaction_from_data(RECEIPT_DATA, "Checking")

    assert result == "Transaction created successfully with ID: 42"
    receipt, account = create.call_args.args
    assert receipt.store_name == "Rimi" and account == "Checking"
    attach.assert_not_called()
    no_sleep.assert_not_called()


async def test_create_transaction_attaches_image():
    with (
        patch.object(rp, "create_firefly_transaction", return_value=CREATED),
        patch.object(rp, "attach_image_to_transaction") as attach,
    ):
        result = await rp.create_transaction_from_data(
            RECEIPT_DATA, "Checking", b"jpeg"
        )

    assert "attaching" not in result
    attach.assert_called_once_with("100", b"jpeg", "receipt_2025-01-31.jpg")


async def test_failed_attachment_does_not_retry(no_sleep):
    with (
        patch.object(rp, "create_firefly_transaction", return_value=CREATED) as create,
        patch.object(rp, "attach_image_to_transaction", side_effect=Exception("x")),
    ):
        result = await rp.create_transaction_from_data(
            RECEIPT_DATA, "Checking", b"jpeg"
        )

    assert result.endswith("(attaching the receipt image failed)")
    assert create.call_count == 1


async def test_create_transaction_retries_with_backoff(no_sleep):
    with patch.object(
        rp,
        "create_firefly_transaction",
        side_effect=[Exception("down"), Exception("down"), CREATED],
    ) as create:
        result = await rp.create_transaction_from_data(RECEIPT_DATA, "Checking")

    assert result.startswith("Transaction created successfully")
    assert create.call_count == 3
    assert [c.args[0] for c in no_sleep.call_args_list] == [3, 6]


async def test_create_transaction_gives_up(no_sleep):
    with patch.object(
        rp, "create_firefly_transaction", side_effect=Exception("down")
    ) as create:
        result = await rp.create_transaction_from_data(RECEIPT_DATA, "Checking")

    assert result == "Failed to create transaction after 3 attempts. Last error: down"
    assert create.call_count == 3


async def test_create_transaction_empty_response(no_sleep):
    with patch.object(rp, "create_firefly_transaction", return_value=None):
        result = await rp.create_transaction_from_data(RECEIPT_DATA, "Checking")
    assert "No response from Firefly III" in result
