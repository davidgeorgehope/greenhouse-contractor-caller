from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = "https://msg.engineer"
    database_path: str = "data/greenhouse.sqlite3"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    imsg_from_label: str = "operator Messages.app account"

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime-2"
    openai_realtime_voice: str = "marin"
    brave_search_api_key: str = ""
    discovery_results_per_query: int = 6

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    resend_api_key: str = ""
    resend_from: str = ""
    cloudflare_account_id: str = ""
    cloudflare_email_token: str = ""
    cloudflare_email_from: str = ""

    contractor_auth_secret: str = ""
    contractor_invite_code: str = ""
    contractor_session_cookie: str = "contractor_session"
    contractor_email_ingest_secret: str = ""
    contractor_product_name: str = "Contractor Relief"
    contractor_billing_required: bool = False
    contractor_plan_active_jobs: int = 5
    contractor_plan_call_credits: int = 10
    contractor_plan_leads_per_job: int = 10
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    stripe_credit_price_id: str = ""
    contractor_credit_pack_size: int = 10

    owner_name: str = "Customer"
    owner_phone: str = ""
    project_address: str = ""
    greenhouse_product_url: str = "https://exaco.com/product/modern/"

    operator_timezone: str = "America/New_York"
    max_calls_per_run: int = 8
    call_spacing_seconds: int = 10
    max_call_wait_seconds: int = 180
    max_drive_minutes: int = 90
    max_distance_miles: int = 75
    caller_disabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
