"""Top-level settings (env-backed). Per-domain defaults live in sibling modules
(gather.py, aggregate.py, solver.py, harness.py). Values mirror CLAUDE.md §16.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infra
    database_url: str = "postgresql+asyncpg://syncinerary:syncinerary@localhost:5432/syncinerary"
    redis_url: str = "redis://localhost:6379/0"

    # External tools
    google_maps_api_key: str = ""

    # LLM
    anthropic_api_key: str = ""
    sync_llm_model: str = "claude-opus-4-7"
    sync_cheap_model: str = "claude-haiku-4-5"

    # Observability
    phoenix_endpoint: str = "http://localhost:4317"
    phoenix_project_name: str = "syncinerary"

    # Harness (used from M2+; safe to set now)
    sync_max_steps: int = 50
    sync_max_tokens_usd: float = 2.0


settings = Settings()
