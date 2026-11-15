"""add sync_accounts.last_classified_at for the refresh-button cooldown

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sync_accounts",
        sa.Column("last_classified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_accounts", "last_classified_at")
