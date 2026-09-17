"""hash-based unique constraints on pages.url and page_sections.heading_path

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres btree index rows cap at ~2704 bytes (pg16, 8KB pages) — a
    # long URL or heading path can exceed that on its own, breaking the
    # unique constraint's index at insert time. Fix: constrain on an MD5
    # hash instead of the raw value (Postgres's own suggested workaround).
    op.add_column("pages", sa.Column("url_hash", sa.String(32), nullable=True))
    op.execute("UPDATE pages SET url_hash = md5(url)")
    op.alter_column("pages", "url_hash", nullable=False)
    op.drop_constraint("uq_pages_user_url_flag", "pages", type_="unique")
    op.create_unique_constraint(
        "uq_pages_user_urlhash_flag", "pages", ["user_id", "url_hash", "flag"]
    )

    op.add_column(
        "page_sections", sa.Column("heading_path_hash", sa.String(32), nullable=True)
    )
    # chr(30) (record separator) joins the array elements before hashing —
    # avoids ambiguity between e.g. ['a,b'] and ['a','b'] that a comma
    # separator could produce.
    op.execute(
        "UPDATE page_sections SET heading_path_hash = "
        "md5(array_to_string(heading_path, chr(30)))"
    )
    op.alter_column("page_sections", "heading_path_hash", nullable=False)
    op.drop_constraint("uq_page_sections_page_heading", "page_sections", type_="unique")
    op.create_unique_constraint(
        "uq_page_sections_page_headinghash",
        "page_sections",
        ["page_id", "heading_path_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_page_sections_page_headinghash", "page_sections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_page_sections_page_heading", "page_sections", ["page_id", "heading_path"]
    )
    op.drop_column("page_sections", "heading_path_hash")

    op.drop_constraint("uq_pages_user_urlhash_flag", "pages", type_="unique")
    op.create_unique_constraint(
        "uq_pages_user_url_flag", "pages", ["user_id", "url", "flag"]
    )
    op.drop_column("pages", "url_hash")
