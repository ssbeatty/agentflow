"""Shared pytest setup + fixtures.

CRITICAL ordering note: `app.config` builds the `settings` singleton (and
`app.database` the engine, `app.security` the signing secret) at *import* time
from environment variables. So every app-state env var must be set **here, at
the top of conftest**, before any test module imports an `app.*` / `services.*`
module — pytest loads this conftest before collecting the test files, so setting
`os.environ` now guarantees the whole suite runs against a throwaway temp
sqlite DB + data dir instead of your real `backend/data`.
"""
import os
import sys
import tempfile
from pathlib import Path

# ── make the backend package root importable (app/, services/, agentflow/) ────
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# ── isolate ALL app state into a throwaway temp dir (see module docstring) ─────
_TMP = Path(tempfile.mkdtemp(prefix="agentflow-tests-"))
# Fixed signing secret → deterministic tokens + no write to data/.secret_key.
os.environ["SECRET_KEY"] = "test-secret-key-do-not-use-in-prod"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TMP / "scripts")
os.environ["APP_ENV"] = "test"

import pytest  # noqa: E402


@pytest.fixture()
def db():
    """A SQLAlchemy session against the isolated temp sqlite DB.

    Tables are (re)created from the ORM models before each test and dropped
    after, so tests are independent. This builds the *current* model schema
    directly (not via Alembic) — fine for exercising service/model logic; use a
    dedicated migration test if you need to verify a specific revision.
    """
    from app.database import Base, SessionLocal, engine
    import app.models  # noqa: F401  — registers every model on Base.metadata

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
