import io
import os
from unittest.mock import MagicMock

import pytest
from PIL import Image

# Settings are required at import time; never use a developer's real .env
os.environ.update(
    {
        "FIREFLY_III_URL": "https://firefly.test",
        "FIREFLY_III_TOKEN": "firefly-token",
        "LLM_API_KEY": "llm-key",
    }
)

from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_image(size=(100, 50), mode="RGB", fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, "white").save(buf, format=fmt)
    return buf.getvalue()


def mock_response(status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = text
    response.headers = {}
    return response
