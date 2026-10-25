"""Add niches and niche_contents tables.

Revision ID: 20260917_0003
Revises: 20260917_0002
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0003"
down_revision: str | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "niches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "seed_channels_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "seed_videos_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "include_keywords_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "exclude_keywords_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("filters_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "name", name="uq_niches_project_name"),
    )
    op.create_index("idx_niches_project", "niches", ["project_id"])

    op.create_table(
        "niche_contents",
        sa.Column("niche_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column(
            "relevance_score", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column("matched_seed", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("matched_value", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["social_contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("niche_id", "content_id"),
    )
    op.create_index("idx_niche_contents_niche", "niche_contents", ["niche_id"])


def downgrade() -> None:
    op.drop_table("niche_contents")
    op.drop_table("niches")
