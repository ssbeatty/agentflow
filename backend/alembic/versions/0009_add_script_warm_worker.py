"""add scripts.warm / scripts.keep_warm

Per-script warm-worker (serverless-style) execution flags. Only consulted when
the global AGENTFLOW_WARM_WORKERS flag is enabled; otherwise every run spawns a
fresh subprocess (the classic isolation). `warm` (default True) lets a script
reuse a long-lived per-script worker between runs; `keep_warm` (default False)
eagerly preheats it. See services/worker_pool.py.

Two plain add_columns with server_defaults (booleans stored as 0/1 on sqlite),
each behind an inspector guard so a DB that already has the column is skipped.
Same defensive shape as 0002/0004/0008.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("scripts")]
    if "warm" not in cols:
        op.add_column(
            "scripts",
            sa.Column("warm", sa.Boolean(), nullable=False, server_default="1"),
        )
    if "keep_warm" not in cols:
        op.add_column(
            "scripts",
            sa.Column("keep_warm", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("scripts", "keep_warm")
    op.drop_column("scripts", "warm")
