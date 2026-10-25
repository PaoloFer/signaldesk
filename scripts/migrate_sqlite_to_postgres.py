from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select, text


TABLE_ORDER = (
    "organizations",
    "users",
    "social_comments",
    "social_contents",
    "content_snapshots",
    "research_projects",
    "organization_members",
    "user_sessions",
    "project_contents",
    "project_comments",
    "niches",
    "niche_contents",
    "channel_profiles",
    "niche_channels",
    "creators",
    "creator_links",
    "project_sources",
    "monitoring_runs",
    "background_jobs",
    "comment_analysis",
    "entities",
    "content_entity_mentions",
    "processing_logs",
    "content_transcripts",
    "api_usage",
)
SEQUENCE_TABLES = (
    "organizations", "users", "social_comments", "social_contents",
    "content_snapshots", "research_projects", "project_sources", "monitoring_runs",
    "background_jobs", "niches", "channel_profiles", "creators", "entities",
    "content_entity_mentions", "processing_logs", "content_transcripts", "api_usage",
)


def migrate(source_path: Path, target_url: str) -> dict[str, int]:
    if not source_path.exists():
        raise FileNotFoundError(f"Database SQLite non trovato: {source_path}")
    if not target_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Il database di destinazione deve essere PostgreSQL")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = create_engine(target_url, pool_pre_ping=True)
    metadata = MetaData()
    metadata.reflect(bind=target)
    target_tables = set(inspect(target).get_table_names())
    counts: dict[str, int] = {}
    try:
        with target.begin() as connection:
            populated = sum(
                connection.execute(select(text("COUNT(*)")).select_from(metadata.tables[name])).scalar_one()
                for name in TABLE_ORDER
                if name in target_tables
            )
            if populated:
                raise RuntimeError("Il database PostgreSQL non è vuoto; migrazione annullata")

            source_tables = {
                row[0] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for name in TABLE_ORDER:
                if name not in source_tables or name not in target_tables:
                    continue
                table = metadata.tables[name]
                target_columns = {column.name for column in table.columns}
                rows = [
                    {key: row[key] for key in row.keys() if key in target_columns}
                    for row in source.execute(f'SELECT * FROM "{name}"')
                ]
                if rows:
                    connection.execute(table.insert(), rows)
                counts[name] = len(rows)

            for name in SEQUENCE_TABLES:
                if name not in target_tables:
                    continue
                connection.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                    f"GREATEST(COALESCE((SELECT MAX(id) FROM {name}), 1), 1))"
                ))
    finally:
        source.close()
        target.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra SignalDesk da SQLite a PostgreSQL")
    parser.add_argument("--source", default="social_intelligence.db")
    parser.add_argument("--target", default=os.getenv("DATABASE_URL", ""))
    arguments = parser.parse_args()
    counts = migrate(Path(arguments.source), arguments.target)
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
