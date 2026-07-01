"""add search_config (built-in web_search / web_fetch provider settings)

Creates the singleton `search_config` table backing the Tools-page "Web search
provider" card. One row (id="default") holds the preferred provider and the
Tavily API key; DuckDuckGo stays the always-on fallback.

Idempotent guard: a pre-Alembic DB healed to the ORM models (see
app/migrate.py::_heal_schema_to_models) may already have this table via
create_all before being stamped head. Skip the create when it already exists so
the revision self-heals either way.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "search_config" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "search_config",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(length=32), server_default="tavily", nullable=False),
        sa.Column("tavily_api_key", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("search_config")
