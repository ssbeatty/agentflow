"""add scripts.input_schema

Adds an optional JSON Schema cache for a script's run() input. The schema is
authored *in the script* (a module-level ``INPUT_SCHEMA`` dict or a Pydantic
model's ``.model_json_schema()``) and extracted into this column by
services/script_schema.py; downstream it drives pre-run validation, typed /docs
examples, and auto-rendered input forms. Null = untyped (legacy behaviour).

Plain add_column (a pure nullable add needs no sqlite table-recreate) + inspector
guard, so a DB that already has the column is skipped rather than hitting a
duplicate-column error. Same defensive shape as 0002/0003/0004.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("scripts")]
    if "input_schema" not in cols:
        op.add_column(
            "scripts",
            sa.Column("input_schema", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("scripts", "input_schema")
