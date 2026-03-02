"""Add listing_comments table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "listing_comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("author_name", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_listing_comments_listing_id",
        "listing_comments",
        ["listing_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_listing_comments_listing_id", table_name="listing_comments")
    op.drop_table("listing_comments")
