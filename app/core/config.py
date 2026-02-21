from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str | None = None
    telegram_bot_username: str | None = None
    webhook_url: str | None = None

    offer_url: str | None = None
    legal_consent_url: str | None = None
    newsletter_unsubscribe_base_url: str | None = None
    newsletter_unsubscribe_secret: str | None = None
    newsletter_consent_document_version: str = "v1"
    yandex_metrika_counter_id: int = 106884182
    admin_ids: str | None = None
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
    report_delay_seconds: int = 10
    report_job_poll_interval_seconds: int = 5
    report_job_lock_timeout_seconds: int = 600
    resume_nudge_delay_hours: int = 6
    resume_nudge_campaign: str = "resume_after_stall_v1"

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
    payment_debug_auto_confirm_local: bool = False
    payment_provider: str = "prodamus"
    prodamus_form_url: str | None = None
    prodamus_key: str | None = None
    prodamus_api_key: str | None = None
    prodamus_secret: str | None = None
    prodamus_webhook_secret: str | None = None
    prodamus_allow_unsigned_webhook: bool = False
    prodamus_unsigned_webhook_ips: str | None = None
    prodamus_unsigned_payload_secret: str | None = None
    cloudpayments_public_id: str | None = None
    cloudpayments_api_secret: str | None = None
    payment_webhook_url: str | None = None
    payment_success_url: str | None = None
    payment_fail_url: str | None = None
    payment_provider_poll_min_interval_seconds: int = 10

    free_t0_cooldown_hours: int = 720
    tariff_t0_price_rub: int = 0
    tariff_t1_price_rub: int = 560
    tariff_t2_price_rub: int = 2190
    tariff_t3_price_rub: int = 5930

    database_url: str | None = None
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    pdf_storage_bucket: str | None = None
    pdf_storage_key: str | None = None
    pdf_font_path: str | None = None
    pdf_font_regular_path: str | None = None
    pdf_font_bold_path: str | None = None
    pdf_font_accent_path: str | None = None
    pdf_subsection_fallback_heuristic_enabled: bool = False
    pdf_strict_text_mode: bool | None = None

    monitoring_webhook_url: str | None = None
    admin_login: str | None = None
    admin_password: str | None = None
    admin_auto_refresh_seconds: int = 0

    env: str = "dev"
    log_level: str = "info"

    @property
    def prodamus_unified_key(self) -> str | None:
        return (
            self.prodamus_key
            or self.prodamus_api_key
            or self.prodamus_secret
            or self.prodamus_webhook_secret
        )

    @property
    def tariff_prices_rub(self) -> dict[str, int]:
        return {
            "T0": self.tariff_t0_price_rub,
            "T1": self.tariff_t1_price_rub,
            "T2": self.tariff_t2_price_rub,
            "T3": self.tariff_t3_price_rub,
        }

    @property
    def pdf_strict_text_mode_enabled(self) -> bool:
        if self.pdf_strict_text_mode is not None:
            return self.pdf_strict_text_mode
        return str(self.env or "").lower() in {"prod", "production"}

settings = Settings()
