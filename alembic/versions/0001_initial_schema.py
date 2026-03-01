"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("references_csv", sa.Text),
        sa.Column("query_terms", sa.Text),
        sa.Column("required_keywords", sa.Text),
        sa.Column("forbidden_keywords", sa.Text),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("synced_at", sa.TIMESTAMP),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.Text, nullable=False, unique=True),
        sa.Column("title", sa.Text),
        sa.Column("price_amount", sa.Numeric),
        sa.Column("currency", sa.Text),
        sa.Column("condition", sa.Text),
        sa.Column("seller_location", sa.Text),
        sa.Column("image_url", sa.Text),
        sa.Column("first_seen_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.TIMESTAMP),
        sa.Column("last_checked_at", sa.TIMESTAMP),
        sa.Column("removed_at", sa.TIMESTAMP),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("availability_note", sa.Text),
        sa.Column("confidence_score", sa.Numeric),
        sa.Column("confidence_rationale", sa.Text),
        sa.Column("extra_data", sa.Text),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.TIMESTAMP),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("error_summary", sa.Text),
        sa.Column("watches_processed", sa.Integer, server_default="0"),
        sa.Column("listings_found", sa.Integer, server_default="0"),
        sa.Column("listings_new", sa.Integer, server_default="0"),
        sa.Column("triggered_by", sa.Text),
    )

    op.create_table(
        "run_source_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id")),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("run_source_errors")
    op.drop_table("runs")
    op.drop_table("listings")
    op.drop_table("watches")
