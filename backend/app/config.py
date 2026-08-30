"""Application configuration, loaded from environment variables.

Every value here has a matching entry in the repo-root .env.example.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalise_database_url(url: str) -> str:
    """Upgrade a bare postgres URL to the psycopg3 driver.

    Managed hosts hand out `postgresql://...` (and Heroku-style `postgres://`).
    SQLAlchemy reads both as psycopg2, which this project does not install — it
    pins psycopg3 — so the app would fail at startup with a driver error that
    says nothing about the cause. Rewriting here means the operator pastes the
    URL the host gave them and it works.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


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

    @field_validator("database_url")
    @classmethod
    def _fix_driver(cls, v: str) -> str:
        return _normalise_database_url(v)

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

    #: Browser origins allowed to call this API. Comma-separated in the
    #: environment (CORS_ORIGINS). Localhost is kept so a developer running the
    #: frontend against a deployed backend still works; a deployment adds its
    #: own origin rather than editing code. Never "*": these endpoints include
    #: the human review actions, and a wildcard would let any page on the
    #: internet post an approval from a logged-in reviewer's browser.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def razorpay_is_test_mode(self) -> bool:
        """Guard used by the ingest layer so a live key can never be used."""
        return bool(self.razorpay_key_id and self.razorpay_key_id.startswith("rzp_test_"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
