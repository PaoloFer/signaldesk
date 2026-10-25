"""Add persistent project sources.

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("refresh_hours", sa.Integer(), nullable=False, server_default=sa.text("24")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_run_at", sa.Text()),
        sa.Column("next_run_at", sa.Text()),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.ForeignKeyConstraint(["project_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id", "source_type", "config_json",
            name="uq_project_sources_project_type_config",
        ),
    )
    op.create_index("idx_sources_project", "project_sources", ["project_id", sa.text("created_at DESC")])
    op.create_index("idx_sources_due", "project_sources", ["status", "next_run_at"])


def downgrade() -> None:
    op.drop_table("project_sources")
