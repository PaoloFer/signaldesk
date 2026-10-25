"""Add persistent panorama niches and channel identities.

Revision ID: 20260917_0010
Revises: 20260917_0009
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0010"
down_revision: str | None = "20260917_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "niches", sa.Column("kind", sa.Text(), nullable=False, server_default="topic")
    )
    op.add_column(
        "niches", sa.Column("definition_json", sa.Text(), nullable=False, server_default="{}")
    )
    op.create_table(
        "channel_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default="YouTube"),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("custom_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("country", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_language", sa.Text(), nullable=False, server_default=""),
        sa.Column("subscribers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("themes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "platform", "channel_id",
            name="uq_channel_profiles_project_platform_channel",
        ),
    )
    op.create_index("idx_channel_profiles_project", "channel_profiles", ["project_id"])
    op.create_index(
        "idx_channel_profiles_platform_channel", "channel_profiles", ["platform", "channel_id"]
    )
    op.create_table(
        "niche_channels",
        sa.Column("niche_id", sa.Integer(), sa.ForeignKey("niches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_profile_id", sa.Integer(), sa.ForeignKey("channel_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("matched_themes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("niche_id", "channel_profile_id"),
    )
    op.create_index("idx_niche_channels_niche", "niche_channels", ["niche_id"])
    op.create_index("idx_niche_channels_profile", "niche_channels", ["channel_profile_id"])
    op.create_table(
        "creators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_creators_project", "creators", ["project_id"])
    op.create_table(
        "creator_links",
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_profile_id", sa.Integer(), sa.ForeignKey("channel_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_method", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("creator_id", "channel_profile_id"),
    )
    op.create_index("idx_creator_links_profile", "creator_links", ["channel_profile_id"])


def downgrade() -> None:
    op.drop_index("idx_creator_links_profile", table_name="creator_links")
    op.drop_table("creator_links")
    op.drop_index("idx_creators_project", table_name="creators")
    op.drop_table("creators")
    op.drop_index("idx_niche_channels_profile", table_name="niche_channels")
    op.drop_index("idx_niche_channels_niche", table_name="niche_channels")
    op.drop_table("niche_channels")
    op.drop_index("idx_channel_profiles_platform_channel", table_name="channel_profiles")
    op.drop_index("idx_channel_profiles_project", table_name="channel_profiles")
    op.drop_table("channel_profiles")
    op.drop_column("niches", "definition_json")
    op.drop_column("niches", "kind")
