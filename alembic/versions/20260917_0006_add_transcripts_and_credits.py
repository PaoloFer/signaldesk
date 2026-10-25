"""Add content_transcripts table and project transcription credits.

Revision ID: 20260917_0006
Revises: 20260917_0005
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0006"
down_revision: str | None = "20260917_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_projects",
        sa.Column(
            "transcription_credits", sa.Integer(), nullable=False,
            server_default=sa.text("25"),
        ),
    )
    op.create_table(
        "content_transcripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(),
            sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default=sa.text("'YouTube'")),
        sa.Column("language", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("text", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("segments_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("analysis_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("extracted_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "platform", "external_id",
            name="uq_transcripts_project_platform_external",
        ),
    )
    op.create_index("idx_transcripts_project", "content_transcripts", ["project_id"])
    op.create_index(
        "idx_transcripts_status", "content_transcripts", ["project_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("content_transcripts")
    op.drop_column("research_projects", "transcription_credits")
