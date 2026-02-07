from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str | None = None
    webhook_url: str | None = None

    offer_url: str | None = None
    feedback_group_chat_id: int | None = None
    feedback_group_url: str | None = None
    community_channel_url: str | None = None
    feedback_mode: str = "native"
    global_menu_enabled: bool = False
    screen_title_enabled: bool = True
    screen_images_dir: str = "app/assets/screen_images"

    llm_primary: str = "gemini"
    llm_fallback: str = "openai"
    llm_timeout_seconds: int = 35
    llm_auth_error_block_seconds: int = 3600
    report_safety_enabled: bool = True
    report_delay_seconds: int = 0

    # Прокси ТОЛЬКО для LLM-запросов (Gemini/OpenAI). Берется из .env:
    # LLM_PROXY_URL=http://user:pass@host:3128
    llm_proxy_url: str | None = None

    gemini_api_key: str | None = None
    gemini_api_keys: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    gemini_image_model: str | None = None

    openai_api_key: str | None = None
    openai_api_keys: str | None = None
    openai_model: str = "gpt-4o-mini"

    payment_enabled: bool = True
    payment_provider: str = "prodamus"
    prodamus_form_url: str | None = None
    prodamus_secret: str | None = None
    prodamus_status_url: str | None = None
    prodamus_webhook_secret: str | None = None
    cloudpayments_public_id: str | None = None
    cloudpayments_api_secret: str | None = None
    payment_webhook_url: str | None = None

    free_t0_cooldown_hours: int = 720

    database_url: str | None = None
    pdf_storage_bucket: str | None = None
    pdf_storage_key: str | None = None
    pdf_font_path: str | None = None

    monitoring_webhook_url: str | None = None
    admin_api_key: str | None = None
    admin_allowed_ips: str | None = None
    admin_auto_refresh_seconds: int = 0

    env: str = "dev"
    log_level: str = "info"


settings = Settings()
