"""Add comment_analysis and processing_logs tables.

Revision ID: 20260917_0004
Revises: 20260917_0003
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0004"
down_revision: str | None = "20260917_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comment_analysis",
        sa.Column(
            "comment_id", sa.Integer(), sa.ForeignKey("social_comments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("language", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("sentiment", sa.Text(), nullable=False, server_default=sa.text("'neutral'")),
        sa.Column(
            "sentiment_score", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column("intent", sa.Text(), nullable=False, server_default=sa.text("'other'")),
        sa.Column(
            "toxicity_score", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column("flags_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("processed_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_comment_analysis_sentiment", "comment_analysis", ["sentiment"])
    op.create_index("idx_comment_analysis_intent", "comment_analysis", ["intent"])

    op.create_table(
        "processing_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_processing_logs_project", "processing_logs", ["project_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("processing_logs")
    op.drop_table("comment_analysis")
