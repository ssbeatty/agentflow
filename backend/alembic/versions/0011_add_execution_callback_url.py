"""add executions.callback_url

Optional completion webhook for a run. When set, the engine POSTs the run's
final result to this URL on terminal state, so an external caller can submit
async (POST /executions/run?wait=false) and be pushed the result instead of
polling. Additive and defensive, same shape as 0002/0004/0010: a plain
add_column behind an inspector guard (nullable, so an ADD can't fail on a
populated table and no backfill is needed).
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("executions")]
    if "callback_url" not in cols:
        op.add_column("executions", sa.Column("callback_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "callback_url")
