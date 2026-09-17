"""add opt-in categorization: categories table, pages.category_id/confidence

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-17

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
    # Opt-in feature flag lives on sync_accounts, the account-level identity
    # table (same place `tier` already lives) — not on `users`, which only
    # maps one browser to its account and has no room for account-wide state.
    op.add_column(
        "sync_accounts",
        sa.Column(
            "categorization_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("sync_accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        # required — this is what classification runs against
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
    )

    # ON DELETE SET NULL: deleting a category uncategorizes its pages
    # without deleting the pages themselves.
    op.add_column(
        "pages",
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Nullable — Jev returns a real confidence score, the Gemini fallback
    # path doesn't, so this stays unset for fallback-classified pages.
    op.add_column("pages", sa.Column("category_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("pages", "category_confidence")
    op.drop_column("pages", "category_id")
    op.drop_table("categories")
    op.drop_column("sync_accounts", "categorization_enabled")
