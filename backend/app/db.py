"""SQLAlchemy engine and session wiring."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# search_path
#
# Neon's pooler REJECTS `options=-c search_path=...` outright:
#
#   ERROR: unsupported startup parameter in options: search_path.
#          Please use unpooled connection or remove this parameter
#
# so it cannot be a connect_arg. It is issued as an ordinary statement on each
# new connection instead, which every pooler accepts.
#
# The durable fix is server-side and belongs on the role, because it covers
# every client — psql, Alembic, a restore, anything added later:
#
#   ALTER ROLE <user> SET search_path = public;
#
# Why any of this is needed: pg_dump emits set_config('search_path', '', false),
# session-wide rather than transaction-local, so a pooled session handed back
# after a restore resolves no unqualified table. Every data endpoint then 500s
# while /health/db keeps working, because it queries information_schema
# explicitly. See DEPLOY.md.
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, _record):
    """Runs once per physical connection, as a statement rather than a startup
    parameter, so it works through a pooler that forbids the latter."""
    with dbapi_connection.cursor() as cur:
        cur.execute("SET search_path TO public")


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
