"""add executions token-usage columns

Adds per-execution aggregated LLM token usage:
`prompt_tokens` / `completion_tokens` / `total_tokens` / `llm_calls`.

The tracer captures usage on every LLM call, the runner emits a single
`{"type":"usage"}` event at the end of a run, and the engine persists the
totals here. Powers the cost/usage dashboard and per-run token display.

Each is a plain `op.add_column` with an integer `server_default="0"` (a pure
add with a default backfills existing rows and needs no sqlite table-recreate)
guarded by an inspector check, so a DB that already has a column is skipped
rather than hitting a duplicate-column error. Same defensive shape as
0002/0003/0004/0005.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels = None
depends_on = None


_COLUMNS = ("prompt_tokens", "completion_tokens", "total_tokens", "llm_calls")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("executions")}
    for name in _COLUMNS:
        if name not in existing:
            op.add_column(
                "executions",
                sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("executions", name)
