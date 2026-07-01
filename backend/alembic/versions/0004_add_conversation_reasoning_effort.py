"""add conversations.reasoning_effort

Adds a per-conversation reasoning/think level (off | low | medium | high),
threaded into each run's input as input["reasoning"] and mapped to the model's
provider-specific thinking parameter by agentflow.get_llm(reasoning=...).

Plain add_column (a pure add needs no sqlite table-recreate) + inspector guard,
so a DB that already has the column (e.g. a pre-Alembic DB healed via create_all,
or one that got it through an interim path) is skipped rather than hitting a
duplicate-column error. Same defensive shape as 0002/0003.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("conversations")]
    if "reasoning_effort" not in cols:
        op.add_column(
            "conversations",
            sa.Column(
                "reasoning_effort",
                sa.String(length=16),
                nullable=False,
                server_default="off",
            ),
        )


def downgrade() -> None:
    op.drop_column("conversations", "reasoning_effort")
