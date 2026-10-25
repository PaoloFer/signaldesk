"""Add indexes for hot query paths (B4).

- ``project_contents(project_id, niche)``: filtri per nicchia nei report,
  refresh metriche e cancellazione per nicchia.
- ``content_snapshots(external_id)``: lookup degli snapshot per lista di
  contenuti (l'indice esistente è prefissato su ``platform``).

Revision ID: 20260917_0009
Revises: 20260917_0008
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0009"
down_revision: str | None = "20260917_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_project_contents_niche", "project_contents", ["project_id", "niche"]
    )
    op.create_index(
        "idx_snapshots_external_id", "content_snapshots", ["external_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_snapshots_external_id", table_name="content_snapshots")
    op.drop_index("idx_project_contents_niche", table_name="project_contents")
