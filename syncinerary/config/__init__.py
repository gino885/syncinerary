"""Top-level settings (env-backed). Per-domain defaults live in sibling modules
(gather.py, aggregate.py, solver.py, harness.py). Values mirror CLAUDE.md §16.
"""
from decimal import Decimal
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infra
    database_url: str = "postgresql+asyncpg://syncinerary:syncinerary@localhost:5432/syncinerary"
    redis_url: str = "redis://localhost:6379/0"

    # External tools
    google_maps_api_key: str = ""
    brave_search_api_key: str = ""
    attachment_upload_dir: str = ".data/attachments"
    # The primary transit provider. Anything after it in the chain below is a
    # fallback for arcs it could not route, never a parallel query.
    sync_transit_provider: Literal["google", "transitous"] = "google"
    # Ordered, comma separated. A provider whose credentials are missing is
    # left out of the chain rather than failing, so the pipeline still runs on
    # a laptop with only a Google key.
    sync_transit_fallback_providers: str = "here"
    here_api_key: str = ""

    # Account email delivery. Plain transport is restricted to loopback for tests.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: Literal["starttls", "tls", "plain"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""

    # Native OAuth audiences. Empty values keep that provider unavailable.
    google_oauth_client_id: str = ""
    apple_oauth_client_id: str = ""
    apple_oauth_client_secret: SecretStr = SecretStr("")

    # LLM
    anthropic_api_key: str = ""
    # Versioned AES-256 keys used only to encrypt account-owned provider
    # credentials. The JSON value is injected by the cloud secret manager,
    # for example {"1":"<urlsafe-base64-32-byte-key>"}. Keep old versions
    # present while records encrypted with them still exist.
    sync_credential_encryption_keys: SecretStr = SecretStr("")
    sync_credential_encryption_active_version: int = 1
    sync_llm_model: str = "claude-opus-4-7"
    sync_cheap_model: str = "claude-haiku-4-5"

    # Observability
    phoenix_endpoint: str = "http://localhost:4317"
    phoenix_project_name: str = "syncinerary"
    # Prompts and responses can contain trip preferences and user messages.
    # Production traces keep only operational metadata unless a private local
    # developer explicitly opts into content capture.
    sync_trace_sensitive_content: bool = False
    # Console log level. Phoenix keeps the full trace, but a gather is easier
    # to follow live in the terminal that is serving the app.
    sync_log_level: str = "INFO"

    # Harness (used from M2+; safe to set now)
    sync_max_steps: int = 50
    sync_max_tokens_usd: Decimal = Decimal("2.0")
    # Claude Opus 4.7 standard API pricing, configurable because provider
    # pricing changes independently of application releases.
    sync_llm_input_usd_per_million: Decimal = Decimal(5)
    sync_llm_output_usd_per_million: Decimal = Decimal(25)


settings = Settings()
