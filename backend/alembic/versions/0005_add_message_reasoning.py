"""add conversation_messages.reasoning

Stores the assistant turn's chain-of-thought (the streamed <think> block) so it
survives reload, kept SEPARATE from `content` so it never enters the model history
(chat_start builds history from `content` only). Nullable, no backfill needed
(NULL = the message had no reasoning).

Plain add_column (a pure nullable add needs no sqlite table-recreate) + inspector
guard, so a DB that already has the column is skipped rather than hitting a
duplicate-column error. Same defensive shape as 0002/0003/0004.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("conversation_messages")]
    if "reasoning" not in cols:
        op.add_column(
            "conversation_messages",
            sa.Column("reasoning", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("conversation_messages", "reasoning")
