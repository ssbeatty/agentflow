"""add scripts.module_ids / scripts.kind / scripts.module_package

Reusable code modules: a Script with kind="module" is importable library code
that other scripts bind via `module_ids` (like skill_ids / mcp_server_ids). At
run time the engine materializes each bound module's files into the referencing
script's `script_dir/modules/<package>/` and merges the module's requirements
into that script's venv install. A module has no venv and is never run.

Three additive columns, each behind an inspector guard (a DB that already has
the column is skipped), same defensive shape as 0002/0004/0008/0009. `module_ids`
is backfilled to '[]' on existing rows so the API's list field never reads NULL.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("scripts")]
    if "module_ids" not in cols:
        op.add_column("scripts", sa.Column("module_ids", sa.JSON(), nullable=True))
        op.execute("UPDATE scripts SET module_ids = '[]' WHERE module_ids IS NULL")
    if "kind" not in cols:
        op.add_column(
            "scripts",
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="script"),
        )
    if "module_package" not in cols:
        op.add_column("scripts", sa.Column("module_package", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("scripts", "module_package")
    op.drop_column("scripts", "kind")
    op.drop_column("scripts", "module_ids")
