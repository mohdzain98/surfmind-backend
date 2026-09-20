"""add app_logs table for persisted WARNING+ log records

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("logger_name", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("extra", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_app_logs_logger_name", "app_logs", ["logger_name"])
    op.create_index("ix_app_logs_created_at", "app_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_app_logs_created_at", table_name="app_logs")
    op.drop_index("ix_app_logs_logger_name", table_name="app_logs")
    op.drop_table("app_logs")
