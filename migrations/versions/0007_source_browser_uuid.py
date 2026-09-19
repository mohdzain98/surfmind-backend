"""add pages.source_browser_uuid for cross-browser result attribution

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable — there's no way to retroactively know the origin browser
    # for an account that ever had more than one linked. Records which
    # browser first contributed a page, so the frontend can show "from
    # your other browser" for linked accounts.
    op.add_column("pages", sa.Column("source_browser_uuid", sa.String(), nullable=True))

    # One-time backfill: an account that has (and has only ever had) a
    # single linked browser could only have gotten its pages from that one
    # browser — safe to fill in. Accounts that were ever multi-browser are
    # left NULL rather than guessed at.
    op.execute("""
        UPDATE pages
        SET source_browser_uuid = solo.browser_uuid
        FROM (
            SELECT sync_account_id, MIN(browser_uuid) AS browser_uuid
            FROM users
            GROUP BY sync_account_id
            HAVING COUNT(*) = 1
        ) AS solo
        WHERE pages.user_id = solo.sync_account_id
        """)


def downgrade() -> None:
    op.drop_column("pages", "source_browser_uuid")
