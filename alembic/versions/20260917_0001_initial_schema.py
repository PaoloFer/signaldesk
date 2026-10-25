"""Create the initial application schema.

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False, unique=True),
        sa.Column("content_id", sa.Text(), nullable=False),
        sa.Column("content_title", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("author_hash", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'YouTube'")),
        sa.Column("niche", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("topic", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.create_index("idx_comments_published_at", "social_comments", ["published_at"])
    op.create_index("idx_comments_niche", "social_comments", ["niche"])

    op.create_table(
        "social_contents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'YouTube'")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("channel_id", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("channel_title", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("published_at", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("views", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("likes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("comments", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("niche", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("topic", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("source_query", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("acquired_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("platform", "external_id", name="uq_social_contents_platform_external_id"),
    )
    op.create_index("idx_contents_published_at", "social_contents", ["published_at"])
    op.create_index("idx_contents_niche", "social_contents", ["niche"])

    op.create_table(
        "content_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'YouTube'")),
        sa.Column("captured_at", sa.Text(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("likes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("comments", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint(
            "platform", "external_id", "captured_at",
            name="uq_content_snapshots_platform_external_id_captured_at",
        ),
    )
    op.create_index("idx_snapshots_content", "content_snapshots", ["platform", "external_id"])
    op.create_index("idx_snapshots_captured_at", "content_snapshots", ["captured_at"])

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "research_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'owner'")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_sessions_user", "user_sessions", ["user_id"])
    op.create_index("idx_sessions_expiry", "user_sessions", ["expires_at"])

    op.create_table(
        "project_contents",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("niche", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("topic", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("source_query", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["social_contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "content_id"),
    )
    op.create_index("idx_project_contents_project", "project_contents", ["project_id"])
    op.create_table(
        "project_comments",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        sa.Column("niche", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("topic", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("added_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["social_comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "comment_id"),
    )
    op.create_index("idx_project_comments_project", "project_comments", ["project_id"])
    op.create_table(
        "monitoring_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("requested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("received", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("project_id", sa.Integer()),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_monitoring_runs_started_at", "monitoring_runs", [sa.text("started_at DESC")])
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("result_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_jobs_status_created", "background_jobs", ["status", "created_at"])
    op.create_index("idx_jobs_project", "background_jobs", ["project_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("background_jobs")
    op.drop_table("monitoring_runs")
    op.drop_table("project_comments")
    op.drop_table("project_contents")
    op.drop_table("user_sessions")
    op.drop_table("organization_members")
    op.drop_table("research_projects")
    op.drop_table("users")
    op.drop_table("organizations")
    op.drop_table("content_snapshots")
    op.drop_table("social_contents")
    op.drop_table("social_comments")
