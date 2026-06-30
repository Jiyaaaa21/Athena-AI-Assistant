from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.config import DATABASE_URL

# Phase 11/12: DATABASE_URL now comes from core.config (env-driven) instead
# of being hardcoded, so swapping SQLite for PostgreSQL in production is a
# one-line env var change -- no code edit needed. `connect_args` is only
# meaningful for SQLite (disables its single-thread check, which FastAPI's
# threaded request handling needs); Postgres/psycopg2 ignores it if passed,
# but we only pass it when actually on SQLite to keep things explicit.
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    # Phase 12: pool_pre_ping avoids "server closed the connection
    # unexpectedly" errors against Postgres after idle periods. Harmless
    # no-op on SQLite.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)
