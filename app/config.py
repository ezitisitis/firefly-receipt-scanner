from functools import lru_cache

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    firefly_iii_url: str
    firefly_iii_token: str
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # Old GOOGLE_AI_API_KEY / GEMINI_MODEL names are still accepted
    llm_api_key: str = Field(
        validation_alias=AliasChoices("LLM_API_KEY", "GOOGLE_AI_API_KEY")
    )
    llm_model: str = Field(
        "gemini-2.5-flash",
        validation_alias=AliasChoices("LLM_MODEL", "GEMINI_MODEL"),
    )
    # JPEG quality (1-100) of the image sent to the LLM
    image_quality: int = Field(85, ge=1, le=100)
    # Initial state of the "attach receipt image" checkbox on the review page
    attach_receipt_default: bool = True

    @computed_field
    @property
    def firefly_api_url(self) -> str:
        return self.firefly_iii_url.rstrip("/") + "/api/v1/"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
