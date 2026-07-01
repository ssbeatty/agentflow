"""
Programmatic DB migration runner — the single implementation shared by the CLI
(``migrations/apply.py``) and application startup (``app.main`` lifespan, which
auto-applies migrations so a deploy never leaves the schema half-upgraded).

Statement parsing mirrors the original apply.py: split on ``;``, drop blank
chunks and chunks that start with ``--``.

Two startup scenarios (see :func:`run_startup_migrations`):

* **fresh database** — the schema was just fully built by
  ``Base.metadata.create_all()`` to the latest models, so every existing
  ``V*.sql`` is *recorded* as applied without executing it (a baseline stamp).
  Re-running their ``ALTER ... ADD COLUMN`` statements would error
  ("column already exists") against a create_all-built schema.

* **existing database** — apply pending migrations in version order. create_all
  has already created any brand-new *tables*, so ``CREATE TABLE IF NOT EXISTS``
  no-ops and only the incremental ``ALTER`` / ``CREATE INDEX`` statements do
  real work (e.g. adding ``scripts.skill_ids`` to a pre-skills database).

  This assumes ``schema_migrations`` reflects reality — i.e. the DB has been
  under this migration system since it was created (true for any AgentFlow DB,
  whose V0 baseline seeds the tracking table on first run).
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

# app/db_migrate.py  ->  parent = app/, parent.parent = backend/
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _parse_version(filename: str) -> int | None:
    m = re.match(r"V(\d+)__", filename)
    return int(m.group(1)) if m else None


def load_migration_files() -> list[tuple[str, Path]]:
    files = []
    for p in MIGRATIONS_DIR.glob("V*.sql"):
        n = _parse_version(p.name)
        if n is not None:
            files.append((n, p))
    files.sort(key=lambda x: x[0])
    return [(f"V{n}", p) for n, p in files]


def ensure_tracking_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """))
    conn.commit()


def applied_versions(conn) -> set[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def _statements(sql: str) -> list[str]:
    """Split a migration file into executable statements.

    Split on ``;``, then within each chunk drop full-line ``--`` comments and
    skip empties. Dropping comments *per line* (rather than dropping any chunk
    that merely starts with ``--``) matters for data migrations: a comment
    directly above an ``UPDATE`` must not swallow the statement — there's no
    ``create_all`` to silently paper over a skipped data change.
    """
    out = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            out.append(stmt)
    return out


def _record(conn, version: str) -> None:
    conn.execute(
        text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
        {"v": version, "t": datetime.now(timezone.utc).isoformat()},
    )


def apply_one(conn, version: str, path: Path) -> None:
    """Execute one migration file's statements and record it as applied (one txn)."""
    for stmt in _statements(path.read_text(encoding="utf-8")):
        conn.execute(text(stmt))
    _record(conn, version)
    conn.commit()


def pending_migrations(conn) -> list[tuple[str, Path]]:
    applied = applied_versions(conn)
    return [(v, p) for v, p in load_migration_files() if v not in applied]


def run_pending(engine: Engine, log=print) -> int:
    """Apply all not-yet-applied migrations in order. Returns count applied.

    Raises on the first failing migration (fail-fast: a half-migrated schema
    should surface loudly, not run behind a broken column set).
    """
    with engine.connect() as conn:
        ensure_tracking_table(conn)
        pending = pending_migrations(conn)
        for version, path in pending:
            log(f"[agentflow] applying migration {version}: {path.name}")
            apply_one(conn, version, path)
    return len(pending)


def stamp_all(engine: Engine, log=print) -> int:
    """Record every not-yet-recorded migration as applied WITHOUT executing it.

    Used for a fresh DB whose schema was just built by create_all(). Returns the
    number of versions baselined.
    """
    with engine.connect() as conn:
        ensure_tracking_table(conn)
        to_stamp = pending_migrations(conn)
        for version, _ in to_stamp:
            _record(conn, version)
        conn.commit()
    return len(to_stamp)


def run_startup_migrations(engine: Engine, fresh_db: bool, log=print) -> None:
    """Entry point for app startup, called right after ``create_all()``.

    ``fresh_db`` must be computed *before* create_all ran (it reflects whether
    the DB already contained application tables). See ``app.main.lifespan``.
    """
    if fresh_db:
        n = stamp_all(engine, log)
        log(f"[agentflow] fresh database: baselined {n} migration(s) as applied")
    else:
        n = run_pending(engine, log)
        if n:
            log(f"[agentflow] applied {n} pending migration(s)")
        else:
            log("[agentflow] database schema up to date")
