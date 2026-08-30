"""SQLAlchemy engine and session wiring."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    # Pin search_path on every connection.
    #
    # Against a pooled Postgres (Neon's pooler, PgBouncer, RDS Proxy) a
    # connection is reused across clients, and it carries whatever session
    # state the previous client left behind. Restoring a pg_dump sets
    # `search_path` to '' — session-wide, not transaction-local — so a pooled
    # session handed back afterwards resolves no unqualified table at all.
    # Every data endpoint then 500s while /health/db keeps working, because it
    # queries information_schema explicitly. That is exactly what happened
    # after loading the audit log into the deployed database.
    #
    # Setting it per connection means the app never inherits another client's
    # session state, whatever left it there.
    connect_args={"options": "-c search_path=public"},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
