"""Add content ad signals table.

Revision ID: 20260917_0011
Revises: 20260917_0010
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0011"
down_revision: str | None = "20260917_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_ad_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "content_id", sa.Integer(), sa.ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("platform", sa.Text(), nullable=False, server_default="YouTube"),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("ad_type", sa.Text(), nullable=False, server_default="none"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("disclosure_quality", sa.Text(), nullable=False, server_default="not_applicable"),
        sa.Column("is_commercial", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_disclosed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("affiliate_signals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("sponsorship_signals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("risks_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("detected_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "content_id",
            name="uq_content_ad_signals_project_content",
        ),
    )
    op.create_index("idx_content_ad_signals_project", "content_ad_signals", ["project_id"])
    op.create_index("idx_content_ad_signals_content", "content_ad_signals", ["content_id"])
    op.create_index("idx_content_ad_signals_type", "content_ad_signals", ["project_id", "ad_type"])
    op.create_index("idx_content_ad_signals_brand", "content_ad_signals", ["project_id", "brand_name"])


def downgrade() -> None:
    op.drop_index("idx_content_ad_signals_brand", table_name="content_ad_signals")
    op.drop_index("idx_content_ad_signals_type", table_name="content_ad_signals")
    op.drop_index("idx_content_ad_signals_content", table_name="content_ad_signals")
    op.drop_index("idx_content_ad_signals_project", table_name="content_ad_signals")
    op.drop_table("content_ad_signals")
