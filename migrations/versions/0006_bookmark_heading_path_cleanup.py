"""clean up orphaned bookmark page_sections and pin their heading_path

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bookmarks used to default heading_path to [title] when the client sent
    # none, which drifts whenever the tab title changes between syncs
    # (notification badges, live page state). Each drift missed the
    # (page_id, heading_path_hash) upsert conflict target and inserted a new
    # orphaned page_sections row instead of updating the existing one, so a
    # bookmark's section count only ever grew. Bookmark ingestion now always
    # pins heading_path to a constant [] (see ingestion_service.
    # _default_heading_path), so this is a one-off cleanup for rows that
    # already accumulated under the old behavior: keep only the most
    # recently synced section per bookmark page, and normalize its
    # heading_path/heading_path_hash so future syncs correctly upsert onto
    # it instead of drifting again.
    op.execute(
        """
        WITH ranked AS (
            SELECT ps.id, ps.page_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY ps.page_id ORDER BY ps.created_at DESC
                   ) AS rn
            FROM page_sections ps
            JOIN pages p ON p.id = ps.page_id
            WHERE p.flag = 'bookmark'
        )
        DELETE FROM page_sections
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    # section_embeddings for the deleted rows are removed automatically via
    # ondelete="CASCADE" on section_embeddings.section_id.

    op.execute(
        """
        UPDATE page_sections ps
        SET heading_path = '{}', heading_path_hash = md5('')
        FROM pages p
        WHERE ps.page_id = p.id AND p.flag = 'bookmark'
        """
    )


def downgrade() -> None:
    # Deleted duplicate rows and their original heading_path values aren't
    # recoverable — this cleanup is intentionally one-directional.
    pass
