"""add search_history.mode, fast_strictness

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_history",
        sa.Column("mode", sa.String(), nullable=False, server_default="standard"),
    )
    op.add_column(
        "search_history", sa.Column("fast_strictness", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("search_history", "fast_strictness")
    op.drop_column("search_history", "mode")
