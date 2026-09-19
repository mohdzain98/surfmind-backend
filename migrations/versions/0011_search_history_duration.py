"""add search_history.duration_ms for search latency tracking

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_history", sa.Column("duration_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("search_history", "duration_ms")
