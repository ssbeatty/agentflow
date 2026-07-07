from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

DATABASE_URL = settings.database_url
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # ensure parent dir exists for the .db file
    db_path = DATABASE_URL.split("///", 1)[-1]
    if db_path and not db_path.startswith(":"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # A generous connection pool is REQUIRED, not cosmetic: the run endpoints are
    # `async def` but do synchronous SQLAlchemy work on the event loop, and a
    # long-running synchronous run (`POST /executions/run?wait=true`) keeps its
    # request coroutine (and the executions engine's own session) alive for the
    # whole run. With the SQLAlchemy default pool (5 + 10 overflow = 15) a burst of
    # concurrent runs momentarily needs >15 connections; the 16th checkout blocks
    # ON the event loop thread, which starves the subprocess-drain callbacks
    # (loop.call_soon_threadsafe) → runs never finish → their connections never
    # free → the checkout never unblocks = a permanent deadlock (reproduced at ~10
    # concurrent /run). sqlite connections are cheap file handles, so pool wide.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_size=20,
        max_overflow=80,
        pool_timeout=30,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        # Wait (up to 5s) for a write lock instead of failing immediately with
        # "database is locked": APScheduler jobs run in worker threads and can
        # write concurrently with the event-loop thread, so a momentary writer
        # collision should back off + retry, not error a run.
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
else:
    # postgres / mysql / etc — a wide pool for the same reason as sqlite above
    # (concurrent long synchronous /run requests each hold a connection; too small
    # a pool deadlocks the event loop on checkout). 60 stays under postgres' default
    # max_connections=100 for a single-instance deployment.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        echo=False,
    )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
