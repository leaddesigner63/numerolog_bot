from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    webhook_url: str | None = None

    offer_url: str
    feedback_group_chat_id: int | None = None
    feedback_group_url: str | None = None
    feedback_mode: str = "native"

    llm_primary: str = "gemini"
    llm_fallback: str = "openai"
    llm_timeout_seconds: int = 35
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    payment_provider: str = "prodamus"
    prodamus_form_url: str | None = None
    prodamus_secret: str | None = None
    prodamus_webhook_secret: str | None = None
    cloudpayments_public_id: str | None = None
    cloudpayments_api_secret: str | None = None
    payment_webhook_url: str | None = None

    free_t0_cooldown_hours: int = 720

    database_url: str | None = None
    pdf_storage_bucket: str | None = None
    pdf_storage_key: str | None = None
    pdf_font_path: str | None = None

    env: str = "dev"
    log_level: str = "info"


settings = Settings()
