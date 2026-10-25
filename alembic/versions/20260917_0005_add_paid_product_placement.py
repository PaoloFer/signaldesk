"""Add has_paid_product_placement flag to social_contents.

Revision ID: 20260917_0005
Revises: 20260917_0004
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0005"
down_revision: str | None = "20260917_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_contents",
        sa.Column(
            "has_paid_product_placement", sa.Integer(), nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("social_contents", "has_paid_product_placement")
