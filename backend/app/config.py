"""Application settings, loaded from environment variables (see .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    app_name: str = "Cognitech Recruiter Workflow Platform"
    environment: str = "development"
    database_url: str = "postgresql+psycopg2://cognitech:cognitech@localhost:5432/cognitech"
    secret_key: str = "change-me-in-production"
    app_url: str = "http://localhost:5173"  # frontend base URL (used in email deep links)
    api_url: str = "http://localhost:8000"  # public API base URL (tracking pixels, signed actions)
    timezone: str = "America/New_York"
    cors_origins: str = "http://localhost:5173"

    # Auth
    auth_mode: str = "dev"  # dev | oidc
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_audience: str = ""
    token_ttl_hours: int = 12

    # Worker / scheduler
    embedded_worker: bool = True  # run queue worker + scheduler inside the API process (dev only)
    worker_poll_seconds: int = 5

    # Mail
    mail_backend: str = "console"  # console | smtp | sendgrid | ses
    mail_from: str = "Cognitech Talent Acquisition <talent@cognitech.example>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = False
    sendgrid_api_key: str = ""
    aws_region: str = "us-east-1"

    # Recruiter mailbox sync
    inbox_provider: str = "webhook"  # webhook | gmail | m365
    google_client_id: str = ""
    google_client_secret: str = ""
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""

    # Storage (documents are always encrypted at rest)
    storage_backend: str = "local"  # local | s3
    storage_path: str = "./storage"
    storage_encryption_key: str = ""  # Fernet key; generated from secret_key if empty
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_kms_key_id: str = ""

    # AI layer
    llm_provider: str = "template"  # template | anthropic
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-5"

    # Webhooks
    webhook_secret: str = "dev-webhook-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
