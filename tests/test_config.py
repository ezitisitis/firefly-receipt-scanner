import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.llm_model == "gemini-2.5-flash"
    assert settings.image_quality == 85
    assert settings.attach_receipt_default is True
    assert settings.llm_base_url.startswith("https://generativelanguage.googleapis.com")


@pytest.mark.parametrize(
    "url", ["https://firefly.test", "https://firefly.test/", "https://firefly.test//"]
)
def test_firefly_api_url_normalizes_trailing_slash(monkeypatch, url):
    monkeypatch.setenv("FIREFLY_III_URL", url)
    assert Settings(_env_file=None).firefly_api_url == "https://firefly.test/api/v1/"


def test_legacy_env_names(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "google-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-old")
    settings = Settings(_env_file=None)
    assert settings.llm_api_key == "google-key"
    assert settings.llm_model == "gemini-old"


def test_new_env_names_take_precedence(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "google-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-x")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-old")
    settings = Settings(_env_file=None)
    assert settings.llm_api_key == "llm-key"
    assert settings.llm_model == "gpt-x"


def test_missing_api_key_fails(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("quality", ["0", "101"])
def test_image_quality_bounds(monkeypatch, quality):
    monkeypatch.setenv("IMAGE_QUALITY", quality)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_attach_receipt_default_false(monkeypatch):
    monkeypatch.setenv("ATTACH_RECEIPT_DEFAULT", "false")
    assert Settings(_env_file=None).attach_receipt_default is False
