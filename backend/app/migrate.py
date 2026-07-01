"""Alembic-driven schema migration, applied automatically on app startup.

Replaces the old hand-rolled ``V*.sql`` runner. All DDL + version tracking is
Alembic's job now (trusted, battle-tested, works on sqlite AND postgres). This
module only *orchestrates* Alembic — deciding, for the DB it finds, whether to
build from scratch, adopt an existing schema, or upgrade.

Startup reconcile (the important part — makes any prior deployment self-heal):

* **``alembic_version`` table present** → the DB is already under Alembic; just
  ``upgrade head``.
* **no ``alembic_version`` but ``scripts`` table present** → a pre-Alembic
  deployment (it was already running, so its schema equals the ``0001`` baseline).
  ``stamp`` it at ``0001`` *without re-running* those CREATE TABLEs, then
  ``upgrade head`` to apply anything newer (e.g. ``0002`` adds max_executions).
  This is what fixes a DB whose old ``schema_migrations`` bookkeeping drifted
  out of sync with reality.
* **empty DB** → ``upgrade head`` builds the whole schema from the revisions.

Idempotent: on a DB already at head, ``upgrade head`` is a no-op.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.config import BACKEND_ROOT

# The revision representing "what every already-running deployment has" — the
# full schema minus features added afterwards. Pre-Alembic DBs are stamped here.
BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    """Build an Alembic Config pointed at our on-disk env.py + versions.

    The DB URL is deliberately NOT injected here — env.py reads it straight from
    app settings (single source of truth), which also sidesteps configparser
    ``%`` interpolation issues with passwords in a postgres URL.
    """
    ini = BACKEND_ROOT / "alembic.ini"
    cfg = Config(str(ini)) if ini.exists() else Config()
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def run_migrations(engine: Engine, log=print) -> None:
    """Bring the DB schema up to head, self-healing pre-Alembic databases."""
    try:
        tables = set(inspect(engine).get_table_names())
    except Exception as exc:
        log(f"[agentflow] alembic: could not inspect DB ({exc}); attempting upgrade head")
        tables = set()

    cfg = _alembic_config()

    if "alembic_version" in tables:
        log("[agentflow] alembic: upgrading to head")
        command.upgrade(cfg, "head")
    elif "scripts" in tables:
        log(f"[agentflow] alembic: existing pre-Alembic DB - stamping {BASELINE_REVISION} then upgrading to head")
        command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")
    else:
        log("[agentflow] alembic: fresh DB - building schema at head")
        command.upgrade(cfg, "head")
