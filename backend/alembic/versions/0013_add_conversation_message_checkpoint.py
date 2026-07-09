"""add conversation_messages.checkpoint_id

Conversation threading: a /converse conversation is a durable LangGraph thread
(thread_id == conversation id) persisted to the script's workspace/threads.db, so
a chat agent keeps context across turns and reads a bound skill only once. This
column records the thread's head checkpoint right after each assistant turn; the
next turn anchors there, and deleting a later turn rolls the thread back to the
previous surviving message's checkpoint.

One additive, nullable column behind an inspector guard (a DB that already has it
is skipped), same defensive shape as 0002/0004/0008/0009/0012. Nullable with no
backfill — a NULL checkpoint just means "non-threaded / not yet recorded", which
the anchor logic treats as a fresh thread.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("conversation_messages")]
    if "checkpoint_id" not in cols:
        op.add_column(
            "conversation_messages",
            sa.Column("checkpoint_id", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("conversation_messages", "checkpoint_id")
