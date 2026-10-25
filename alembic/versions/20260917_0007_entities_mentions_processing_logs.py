"""Add entities and content_entity_mentions tables.

These tables were previously created only by the SQLite ``initialize()``
path; this migration makes them versioned for every backend, PostgreSQL
included. (``processing_logs`` è già versionata dalla revisione 0004.)

Revision ID: 20260917_0007
Revises: 20260917_0006
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0007"
down_revision: str | None = "20260917_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(),
            sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False, server_default=sa.text("'brand'")),
        sa.Column("sector", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_entities_project_name"),
    )
    op.create_index("idx_entities_project", "entities", ["project_id"])
    op.create_index("idx_entities_type", "entities", ["type"])

    op.create_table(
        "content_entity_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(),
            sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "content_id", sa.Integer(),
            sa.ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "entity_id", sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'rule'")),
        sa.Column("extracted_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "content_id", "entity_id",
            name="uq_mentions_project_content_entity",
        ),
    )
    op.create_index("idx_mentions_project", "content_entity_mentions", ["project_id"])
    op.create_index("idx_mentions_content", "content_entity_mentions", ["content_id"])
    op.create_index("idx_mentions_entity", "content_entity_mentions", ["entity_id"])


def downgrade() -> None:
    op.drop_table("content_entity_mentions")
    op.drop_table("entities")
