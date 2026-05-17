"""
Migration runner — apply pending V*.sql files in version order.

Usage (from the backend/ directory):
    python migrations/apply.py               # apply all pending
    python migrations/apply.py --dry-run     # show what would run, don't apply
    python migrations/apply.py --status      # list applied/pending versions

Migration files must be named  V<N>__<description>.sql  where N is an integer.
They are applied in ascending N order. Each file is applied in a single
transaction; if it fails the transaction is rolled back and the script exits.

A `schema_migrations` table tracks which versions have been applied:
    version    TEXT PRIMARY KEY   e.g. "V1"
    applied_at TEXT               ISO-8601 UTC timestamp
"""
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Allow running from anywhere — resolve paths relative to this file
MIGRATIONS_DIR = Path(__file__).parent
BACKEND_DIR = MIGRATIONS_DIR.parent

# Add backend to sys.path so app.config / app.database are importable
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, text
from app.config import settings


def _parse_version(filename: str) -> int | None:
    m = re.match(r"V(\d+)__", filename)
    return int(m.group(1)) if m else None


def _load_migration_files() -> list[tuple[str, Path]]:
    files = []
    for p in MIGRATIONS_DIR.glob("V*.sql"):
        n = _parse_version(p.name)
        if n is not None:
            files.append((n, p))
    files.sort(key=lambda x: x[0])
    return [(f"V{n}", p) for n, p in files]


def _ensure_tracking_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """))
    conn.commit()


def _applied_versions(conn) -> set[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def _apply(conn, version: str, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    for stmt in statements:
        conn.execute(text(stmt))
    conn.execute(
        text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
        {"v": version, "t": datetime.now(timezone.utc).isoformat()},
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AgentFlow DB migrations")
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying")
    parser.add_argument("--status", action="store_true", help="Show applied/pending versions and exit")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    migrations = _load_migration_files()

    with engine.connect() as conn:
        _ensure_tracking_table(conn)
        applied = _applied_versions(conn)

        if args.status:
            print(f"{'VERSION':<12} {'STATUS':<10} FILE")
            for version, path in migrations:
                status = "applied" if version in applied else "pending"
                print(f"{version:<12} {status:<10} {path.name}")
            return

        pending = [(v, p) for v, p in migrations if v not in applied]
        if not pending:
            print("No pending migrations.")
            return

        for version, path in pending:
            print(f"{'[dry-run] ' if args.dry_run else ''}Applying {version}: {path.name}")
            if not args.dry_run:
                try:
                    _apply(conn, version, path)
                    print(f"  OK")
                except Exception as e:
                    print(f"  FAILED: {e}")
                    sys.exit(1)

    if not args.dry_run:
        print(f"Done. {len(pending)} migration(s) applied.")


if __name__ == "__main__":
    main()
