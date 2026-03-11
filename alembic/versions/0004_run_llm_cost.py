"""Add LLM cost columns to runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("llm_verify_calls", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("llm_verify_rejected", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("img_verify_calls", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("img_verify_rejected", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("llm_cost_usd", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "llm_cost_usd")
    op.drop_column("runs", "img_verify_rejected")
    op.drop_column("runs", "img_verify_calls")
    op.drop_column("runs", "llm_verify_rejected")
    op.drop_column("runs", "llm_verify_calls")
