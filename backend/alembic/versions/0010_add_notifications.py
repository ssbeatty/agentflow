"""add notification_channels table + executions.trigger

Failure-notification channels (PushPlus / Bark / email) plus a `trigger` column
on executions so the notifier can tell how a run was started (and skip eval
sub-runs). Additive and defensive, same shape as 0002/0004/0008/0009:
  - executions.trigger via a plain add_column behind an inspector guard, with a
    server_default so existing rows populate on ADD.
  - notification_channels via create_table behind a get_table_names() guard (a
    healed pre-Alembic DB may already have it from create_all).
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = [c["name"] for c in insp.get_columns("executions")]
    if "trigger" not in cols:
        op.add_column(
            "executions",
            sa.Column("trigger", sa.String(length=32), nullable=False,
                      server_default="manual"),
        )

    if "notification_channels" not in insp.get_table_names():
        op.create_table(
            "notification_channels",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("notification_channels")
    op.drop_column("executions", "trigger")
