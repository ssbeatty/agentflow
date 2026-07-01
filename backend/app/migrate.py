"""Alembic-driven schema migration, applied automatically on app startup.

Replaces the old hand-rolled ``V*.sql`` runner. All DDL + version tracking is
Alembic's job now (trusted, battle-tested, works on sqlite AND postgres). This
module only *orchestrates* Alembic — deciding, for the DB it finds, whether to
build from scratch, adopt an existing schema, or upgrade.

Startup reconcile (the important part — makes any prior deployment self-heal):

* **``alembic_version`` table present** → the DB is already under Alembic; just
  ``upgrade head``.
* **no ``alembic_version`` but ``scripts`` table present** → a pre-Alembic
  deployment of *unknown / possibly partial* schema. Old AgentFlow DBs went
  through a fragile ``schema_migrations`` runner that could leave the schema
  half-applied (e.g. crash on one migration → later columns like
  ``scripts.skill_ids`` / whole tables like ``skills`` never got created). So we
  do NOT assume it matches any particular revision. Instead we **reconcile it to
  the ORM models** — ``create_all`` builds missing *tables*, then we add any
  missing *columns* (nullable + backfilled to the model default, so ``ADD
  COLUMN`` can't fail on a populated table and API-required fields aren't NULL).
  Then ``stamp head`` records it as fully current. This heals ANY partial state.
* **empty DB** → ``upgrade head`` builds the whole schema from the revisions.

Idempotent: on a DB already at head, ``upgrade head`` is a no-op; the heal only
adds what's genuinely missing.
"""
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, update
from sqlalchemy.engine import Engine

from app.config import BACKEND_ROOT


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


def _model_default(col):
    """The value to backfill a freshly-added column with, from the model default.

    Scalar defaults (``default=50`` / ``"none"``) return the value; callable
    defaults (``default=list`` / ``dict`` on JSON columns) return the produced
    value (``[]`` / ``{}``) which the dialect serialises. ``None`` = leave NULL.
    """
    d = col.default
    if d is None:
        return None
    if getattr(d, "is_scalar", False):
        return d.arg
    if getattr(d, "is_callable", False):
        fn = d.arg
        for call in (lambda: fn(None), lambda: fn(), lambda: fn({})):
            try:
                return call()
            except Exception:
                continue
    return None


def _heal_schema_to_models(engine: Engine, log=print) -> None:
    """Make an existing DB match the ORM models: create missing tables, then add
    missing columns (nullable + backfilled). Safe on populated tables."""
    from app.database import Base
    import app.models  # noqa: F401  (populates Base.metadata)

    # 1) create any missing *tables* (checkfirst=True → skips existing ones).
    Base.metadata.create_all(bind=engine)

    # 2) add any missing *columns* on tables that already existed.
    with engine.begin() as conn:
        insp = inspect(conn)
        existing_tables = set(insp.get_table_names())
        prep = engine.dialect.identifier_preparer
        # Plan first (before any DDL) so the inspector snapshot stays consistent.
        plan = []
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # just built by create_all with all columns
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    plan.append((table, col))
        for table, col in plan:
            type_sql = col.type.compile(dialect=engine.dialect)
            conn.exec_driver_sql(
                f"ALTER TABLE {prep.format_table(table)} "
                f"ADD COLUMN {prep.quote(col.name)} {type_sql}"
            )
            default_value = _model_default(col)
            if default_value is not None:
                conn.execute(
                    update(table)
                    .where(table.c[col.name].is_(None))
                    .values({col.name: default_value})
                )
            log(f"[agentflow] schema-heal: added {table.name}.{col.name}")


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
        log("[agentflow] alembic: existing pre-Alembic DB - reconciling schema to models, then stamping head")
        _heal_schema_to_models(engine, log)
        command.stamp(cfg, "head")
    else:
        log("[agentflow] alembic: fresh DB - building schema at head")
        command.upgrade(cfg, "head")
