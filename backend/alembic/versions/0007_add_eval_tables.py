"""add eval_cases + eval_runs tables

Backs the per-script eval / regression feature: a dataset of test cases
(input + assertions) and batch runs that grade the script's output and record a
pass/fail score (optionally pinned to a ScriptRevision).

Additive-table migration: each `create_table` is guarded by a
`get_table_names()` check so a DB that already has the table (e.g. a healed
pre-Alembic DB that got it via create_all) is skipped rather than erroring —
same defensive shape as 0003's search_config guard.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    if "eval_cases" not in existing:
        op.create_table(
            "eval_cases",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("script_id", sa.String(), sa.ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False, server_default="case"),
            sa.Column("input_json", sa.Text(), server_default="{}"),
            sa.Column("assertions", sa.JSON()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )

    if "eval_runs" not in existing:
        op.create_table(
            "eval_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("script_id", sa.String(), sa.ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="running"),
            sa.Column("revision_number", sa.Integer(), nullable=True),
            sa.Column("judge_model", sa.String(length=255), nullable=True),
            sa.Column("total", sa.Integer(), server_default="0"),
            sa.Column("passed", sa.Integer(), server_default="0"),
            sa.Column("results_json", sa.JSON()),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
