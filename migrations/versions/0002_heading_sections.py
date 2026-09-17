"""add heading-scoped section columns to history_entries

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "history_entries", sa.Column("heading_path", ARRAY(sa.String), nullable=True)
    )
    op.add_column(
        "history_entries", sa.Column("heading_level", sa.Integer, nullable=True)
    )
    op.add_column(
        "history_entries", sa.Column("section_index", sa.Integer, nullable=True)
    )
    op.add_column("history_entries", sa.Column("page_type", sa.String, nullable=True))

    # Treat existing rows as single-section pages — matches the app-level
    # default (_default_heading_path) for items without real heading data,
    # so a page re-synced post-migration upserts onto this same row instead
    # of creating a duplicate.
    op.execute(
        "UPDATE history_entries SET heading_path = "
        "CASE WHEN title IS NOT NULL AND title <> '' THEN ARRAY[title] "
        "ELSE ARRAY[]::varchar[] END "
        "WHERE heading_path IS NULL"
    )
    op.alter_column("history_entries", "heading_path", nullable=False)

    op.drop_constraint(
        "uq_history_entries_user_url_flag", "history_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_history_entries_user_url_flag_heading",
        "history_entries",
        ["user_id", "url", "flag", "heading_path"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_history_entries_user_url_flag_heading", "history_entries", type_="unique"
    )
    op.create_unique_constraint(
        "uq_history_entries_user_url_flag",
        "history_entries",
        ["user_id", "url", "flag"],
    )
    op.drop_column("history_entries", "page_type")
    op.drop_column("history_entries", "section_index")
    op.drop_column("history_entries", "heading_level")
    op.drop_column("history_entries", "heading_path")
