"""
Migration runner CLI — apply pending V*.sql files in version order.

Usage (from the backend/ directory):
    python migrations/apply.py               # apply all pending
    python migrations/apply.py --dry-run     # show what would run, don't apply
    python migrations/apply.py --status      # list applied/pending versions

The migration logic lives in ``app.db_migrate`` and is *shared* with app
startup — the FastAPI lifespan auto-applies pending migrations, so this CLI is
only needed for inspection (--status/--dry-run) or manual/out-of-band runs.

Migration files must be named  V<N>__<description>.sql  where N is an integer;
they are applied in ascending N order, each in a single transaction. A
``schema_migrations`` table tracks which versions have been applied.
"""
import sys
import argparse
from pathlib import Path

# Add backend/ to sys.path so `app.*` is importable when run as a script
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from app.config import settings
from app.db_migrate import (
    load_migration_files,
    ensure_tracking_table,
    applied_versions,
    apply_one,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AgentFlow DB migrations")
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying")
    parser.add_argument("--status", action="store_true", help="Show applied/pending versions and exit")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    migrations = load_migration_files()

    with engine.connect() as conn:
        ensure_tracking_table(conn)
        applied = applied_versions(conn)

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
                    apply_one(conn, version, path)
                    print("  OK")
                except Exception as e:
                    print(f"  FAILED: {e}")
                    sys.exit(1)

    if not args.dry_run:
        print(f"Done. {len(pending)} migration(s) applied.")


if __name__ == "__main__":
    main()
