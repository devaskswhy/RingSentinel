"""Application configuration, loaded from environment variables.

Every value here has a matching entry in the repo-root .env.example.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- App ----
    app_env: str = "local"
    log_level: str = "info"

    # ---- Database ----
    # SQLAlchemy 2.x + psycopg3 driver URL.
    database_url: str = (
        "postgresql+psycopg://ringsentinel:ringsentinel@db:5432/ringsentinel"
    )

    # ---- Razorpay (TEST MODE ONLY) ----
    # Phase 2. Key ids must begin with "rzp_test_"; live keys are never valid here.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    # ---- Claude case files (Phase 4) ----
    #: Which model writes case files. Explicit rather than "whatever the SDK
    #: defaults to", because the model materially changes both quality and cost
    #: per cluster, and a silent default makes the cost story unfalsifiable.
    #: Every generation records its measured cost, so this is a decision that
    #: can be revisited with data rather than opinion.
    claude_case_file_model: str | None = None

    #: Whether this instance may CALL Claude to write new case files.
    #:
    #: Set false on any deployment reachable by people other than the operator.
    #: The Agent SDK's terms do not permit offering claude.ai login or rate
    #: limits to a product's users (CLAUDE.md §5), so a hosted RingSentinel
    #: serving judges on the author's subscription would be outside them. Case
    #: files already in the database are still served in full — they are real
    #: Claude output, generated locally — only new generation is refused.
    claude_generation_enabled: bool = True

    @property
    def razorpay_is_test_mode(self) -> bool:
        """Guard used by the ingest layer so a live key can never be used."""
        return bool(self.razorpay_key_id and self.razorpay_key_id.startswith("rzp_test_"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
