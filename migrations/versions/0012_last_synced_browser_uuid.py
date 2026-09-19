"""add pages.last_synced_browser_uuid, decoupled from source_browser_uuid

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pages", sa.Column("last_synced_browser_uuid", sa.String(), nullable=True)
    )

    # Backfill: before this column existed, "who created this row" and
    # "who last confirmed it's still synced" were the same event for every
    # existing page — source_browser_uuid is the best available guess for
    # last_synced_browser_uuid until each page's next real resync updates
    # it properly. Leaving this NULL instead would make every existing
    # user's page-counts read as 0 until their next sync, a confusing
    # regression right after deploy.
    op.execute(
        "UPDATE pages SET last_synced_browser_uuid = source_browser_uuid "
        "WHERE source_browser_uuid IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("pages", "last_synced_browser_uuid")
