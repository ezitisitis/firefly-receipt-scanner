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
    # Initial state of "Match with existing transactions" on the upload page
    match_existing_default: bool = False
    # Look for existing withdrawals this many days before/after the receipt date
    match_date_window_days: int = Field(3, ge=0)
    # Allowed amount difference when the receipt and transaction share a currency
    match_amount_tolerance: float = Field(0.0, ge=0)
    # Allowed difference (%) when the receipt amount had to be converted
    match_fx_tolerance_percent: float = Field(5.0, ge=0)
    # Exchange rates endpoint, {base} is replaced by the receipt currency;
    # must return {"rates": {"EUR": 0.000035, ...}}. Empty disables conversion.
    fx_rates_url: str = "https://open.er-api.com/v6/latest/{base}"

    @computed_field
    @property
    def firefly_api_url(self) -> str:
        return self.firefly_iii_url.rstrip("/") + "/api/v1/"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
