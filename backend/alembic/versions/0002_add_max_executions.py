"""add scripts.max_executions (per-script execution-record retention)

Adds the column that caps how many execution rows a script keeps (0 = unlimited;
the engine auto-prunes older terminal runs beyond it). Existing rows get 50 via
the server default; a belt-and-suspenders UPDATE covers any backend that leaves
pre-existing rows NULL on ADD COLUMN.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN — NOT batch_alter_table. A pure column addition is
    # supported natively by both sqlite and postgres, so we avoid sqlite's
    # batch "recreate the whole table" (copy -> DROP -> RENAME) dance: it takes a
    # much wider write lock and is needless churn for an additive change. The
    # constant server default backfills existing rows on both engines.
    #
    # Idempotent guard: an AgentFlow DB migrated from the pre-Alembic system may
    # ALREADY have this column (it was briefly shipped as legacy migration V11)
    # while still being stamped at the 0001 baseline. Adding it again would fail
    # with "duplicate column". Skip the ADD when the column is already present so
    # the migration self-heals a drifted schema either way.
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("scripts")}
    if "max_executions" not in existing:
        op.add_column(
            "scripts",
            sa.Column("max_executions", sa.Integer(), server_default="50", nullable=True),
        )
    op.execute("UPDATE scripts SET max_executions = 50 WHERE max_executions IS NULL")


def downgrade() -> None:
    op.drop_column("scripts", "max_executions")
