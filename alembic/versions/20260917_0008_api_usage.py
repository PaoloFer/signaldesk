"""Add api_usage table for estimated YouTube quota tracking.

Revision ID: 20260917_0008
Revises: 20260917_0007
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0008"
down_revision: str | None = "20260917_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("day", "operation", name="uq_api_usage_day_operation"),
    )
    op.create_index("idx_api_usage_day", "api_usage", ["day"])


def downgrade() -> None:
    op.drop_table("api_usage")
