from __future__ import annotations

import sqlite3
import json
import os
import re
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg


DB_PATH = Path(__file__).resolve().parent.parent / "social_intelligence.db"


COMMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS social_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE NOT NULL,
    content_id TEXT NOT NULL,
    content_title TEXT NOT NULL DEFAULT '',
    author_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    published_at TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    niche TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_comments_published_at ON social_comments(published_at);
CREATE INDEX IF NOT EXISTS idx_comments_niche ON social_comments(niche);
"""

CONTENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS social_contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    channel_id TEXT NOT NULL DEFAULT '',
    channel_title TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    has_paid_product_placement INTEGER NOT NULL DEFAULT 0,
    niche TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    source_query TEXT NOT NULL DEFAULT '',
    acquired_at TEXT NOT NULL,
    UNIQUE(platform, external_id)
);
CREATE INDEX IF NOT EXISTS idx_contents_published_at ON social_contents(published_at);
CREATE INDEX IF NOT EXISTS idx_contents_niche ON social_contents(niche);
"""

SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    captured_at TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    UNIQUE(platform, external_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_content ON content_snapshots(platform, external_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at ON content_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_external_id ON content_snapshots(external_id);
"""

MONITORING_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    requested INTEGER NOT NULL DEFAULT 0,
    received INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
    ,project_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_started_at ON monitoring_runs(started_at DESC);
"""

PROJECTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    transcription_credits INTEGER NOT NULL DEFAULT 25,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_contents (
    project_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    niche TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    source_query TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    PRIMARY KEY(project_id, content_id)
);
CREATE TABLE IF NOT EXISTS project_comments (
    project_id INTEGER NOT NULL,
    comment_id INTEGER NOT NULL,
    niche TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    PRIMARY KEY(project_id, comment_id)
);
CREATE INDEX IF NOT EXISTS idx_project_contents_project ON project_contents(project_id);
CREATE INDEX IF NOT EXISTS idx_project_contents_niche ON project_contents(project_id, niche);
CREATE INDEX IF NOT EXISTS idx_project_comments_project ON project_comments(project_id);
"""

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organization_members (
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    PRIMARY KEY(organization_id, user_id)
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON user_sessions(expires_at);
"""

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS background_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON background_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON background_jobs(project_id, created_at DESC);
"""

SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    refresh_hours INTEGER NOT NULL DEFAULT 24,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    next_run_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    UNIQUE(project_id, source_type, config_json)
);
CREATE INDEX IF NOT EXISTS idx_sources_project ON project_sources(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_due ON project_sources(status, next_run_at);
"""

NICHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    kind TEXT NOT NULL DEFAULT 'topic',
    definition_json TEXT NOT NULL DEFAULT '{}',
    seed_channels_json TEXT NOT NULL DEFAULT '[]',
    seed_videos_json TEXT NOT NULL DEFAULT '[]',
    include_keywords_json TEXT NOT NULL DEFAULT '[]',
    exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
    filters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_niches_project ON niches(project_id);
"""

NICHE_CONTENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS niche_contents (
    niche_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    relevance_score REAL NOT NULL DEFAULT 0.0,
    matched_seed TEXT NOT NULL DEFAULT '',
    matched_value TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    PRIMARY KEY(niche_id, content_id)
);
CREATE INDEX IF NOT EXISTS idx_niche_contents_niche ON niche_contents(niche_id);
"""

CHANNEL_PROFILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    custom_url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    default_language TEXT NOT NULL DEFAULT '',
    subscribers INTEGER NOT NULL DEFAULT 0,
    video_count INTEGER NOT NULL DEFAULT 0,
    themes_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    computed_at TEXT NOT NULL,
    UNIQUE(project_id, platform, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_profiles_project ON channel_profiles(project_id);
CREATE INDEX IF NOT EXISTS idx_channel_profiles_platform_channel ON channel_profiles(platform, channel_id);
"""

NICHE_CHANNELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS niche_channels (
    niche_id INTEGER NOT NULL,
    channel_profile_id INTEGER NOT NULL,
    relevance_score REAL NOT NULL DEFAULT 0.0,
    matched_themes_json TEXT NOT NULL DEFAULT '[]',
    added_at TEXT NOT NULL,
    PRIMARY KEY(niche_id, channel_profile_id)
);
CREATE INDEX IF NOT EXISTS idx_niche_channels_niche ON niche_channels(niche_id);
CREATE INDEX IF NOT EXISTS idx_niche_channels_profile ON niche_channels(channel_profile_id);
"""

CREATORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creators_project ON creators(project_id);
CREATE TABLE IF NOT EXISTS creator_links (
    creator_id INTEGER NOT NULL,
    channel_profile_id INTEGER NOT NULL,
    link_method TEXT NOT NULL DEFAULT 'manual',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    PRIMARY KEY(creator_id, channel_profile_id)
);
CREATE INDEX IF NOT EXISTS idx_creator_links_profile ON creator_links(channel_profile_id);
"""

COMMENT_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS comment_analysis (
    comment_id INTEGER PRIMARY KEY,
    language TEXT NOT NULL DEFAULT '',
    sentiment TEXT NOT NULL DEFAULT 'neutral',
    sentiment_score REAL NOT NULL DEFAULT 0.0,
    intent TEXT NOT NULL DEFAULT 'other',
    toxicity_score REAL NOT NULL DEFAULT 0.0,
    flags_json TEXT NOT NULL DEFAULT '[]',
    processed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comment_analysis_sentiment ON comment_analysis(sentiment);
CREATE INDEX IF NOT EXISTS idx_comment_analysis_intent ON comment_analysis(intent);
"""

ENTITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'brand',
    sector TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_entities_project ON entities(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
"""

CONTENT_ENTITY_MENTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    mention_text TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'rule',
    extracted_at TEXT NOT NULL,
    UNIQUE(project_id, content_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_project ON content_entity_mentions(project_id);
CREATE INDEX IF NOT EXISTS idx_mentions_content ON content_entity_mentions(content_id);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON content_entity_mentions(entity_id);
"""

CONTENT_AD_SIGNALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_ad_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    external_id TEXT NOT NULL,
    ad_type TEXT NOT NULL DEFAULT 'none',
    confidence REAL NOT NULL DEFAULT 0.0,
    disclosure_quality TEXT NOT NULL DEFAULT 'not_applicable',
    is_commercial INTEGER NOT NULL DEFAULT 0,
    is_disclosed INTEGER NOT NULL DEFAULT 0,
    brand_name TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    affiliate_signals_json TEXT NOT NULL DEFAULT '[]',
    sponsorship_signals_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    detected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, content_id)
);
CREATE INDEX IF NOT EXISTS idx_content_ad_signals_project ON content_ad_signals(project_id);
CREATE INDEX IF NOT EXISTS idx_content_ad_signals_content ON content_ad_signals(content_id);
CREATE INDEX IF NOT EXISTS idx_content_ad_signals_type ON content_ad_signals(project_id, ad_type);
CREATE INDEX IF NOT EXISTS idx_content_ad_signals_brand ON content_ad_signals(project_id, brand_name);
"""

PROCESSING_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_processing_logs_project ON processing_logs(project_id, created_at DESC);
"""

TRANSCRIPTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    external_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'YouTube',
    language TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    segments_json TEXT NOT NULL DEFAULT '[]',
    analysis_json TEXT NOT NULL DEFAULT '{}',
    extracted_at TEXT NOT NULL,
    UNIQUE(project_id, platform, external_id)
);
CREATE INDEX IF NOT EXISTS idx_transcripts_project ON content_transcripts(project_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_status ON content_transcripts(project_id, status);
"""

API_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    operation TEXT NOT NULL,
    units INTEGER NOT NULL DEFAULT 0,
    UNIQUE(day, operation)
);
CREATE INDEX IF NOT EXISTS idx_api_usage_day ON api_usage(day);
"""


class HybridRow(Mapping[str, Any]):
    def __init__(self, columns: list[str], values: tuple[Any, ...]):
        self._columns = columns
        self._values = values
        self._mapping = dict(zip(columns, values))

    def __getitem__(self, key: str | int) -> Any:
        return self._values[key] if isinstance(key, int) else self._mapping[key]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)


class PostgresCursor:
    def __init__(self, cursor: Any, lastrowid: int | None = None):
        self.cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def _row(self, values: tuple[Any, ...] | None) -> HybridRow | None:
        if values is None:
            return None
        columns = [item.name for item in self.cursor.description]
        return HybridRow(columns, values)

    def fetchone(self) -> HybridRow | None:
        return self._row(self.cursor.fetchone())

    def fetchall(self) -> list[HybridRow]:
        return [self._row(row) for row in self.cursor.fetchall()]  # type: ignore[misc]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row


class PostgresConnection:
    dialect = "postgresql"
    _id_tables = {
        "research_projects", "users", "organizations", "monitoring_runs",
        "background_jobs", "niches", "channel_profiles", "creators",
    }

    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, statement: str, parameters: Any = ()) -> PostgresCursor:
        sql = statement.strip()
        if sql.upper() == "BEGIN IMMEDIATE":
            sql = "BEGIN"
        ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE", sql, re.IGNORECASE))
        if ignored:
            sql = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", sql, count=1, flags=re.IGNORECASE)
        sql = sql.replace("%", "%%").replace("?", "%s")
        table_match = re.match(r"INSERT\s+INTO\s+(\w+)", sql, re.IGNORECASE)
        wants_id = bool(table_match and table_match.group(1) in self._id_tables and "RETURNING" not in sql.upper())
        if ignored and "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT DO NOTHING"
        if wants_id:
            sql += " RETURNING id"
        cursor = self.connection.cursor()
        cursor.execute(sql, parameters)
        lastrowid = None
        if wants_id and cursor.description:
            returned = cursor.fetchone()
            lastrowid = returned[0] if returned else None
        return PostgresCursor(cursor, lastrowid)

    def executemany(self, statement: str, parameters: list[Any]) -> PostgresCursor:
        sql = statement.strip()
        ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE", sql, re.IGNORECASE))
        if ignored:
            sql = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", sql, count=1, flags=re.IGNORECASE)
            if "ON CONFLICT" not in sql.upper():
                sql += " ON CONFLICT DO NOTHING"
        sql = sql.replace("%", "%%").replace("?", "%s")
        cursor = self.connection.cursor()
        cursor.executemany(sql, parameters)
        return PostgresCursor(cursor)

    def executescript(self, _: str) -> None:
        # PostgreSQL schema changes are owned by Alembic.
        return None


@contextmanager
def connect() -> Iterator[Any]:
    database_url = os.getenv("DATABASE_URL", "")
    is_postgres = database_url.startswith(("postgresql://", "postgresql+psycopg://"))
    if is_postgres:
        dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        raw_connection = psycopg.connect(dsn)
        connection: Any = PostgresConnection(raw_connection)
    else:
        raw_connection = sqlite3.connect(DB_PATH)
        raw_connection.row_factory = sqlite3.Row
        connection = raw_connection
    try:
        yield connection
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def initialize() -> None:
    with connect() as connection:
        is_postgres = getattr(connection, "dialect", "sqlite") == "postgresql"
        if not is_postgres:
            connection.executescript(COMMENTS_SCHEMA)
            connection.executescript(CONTENTS_SCHEMA)
            ensure_column(connection, "social_contents", "tags_json", "TEXT NOT NULL DEFAULT '[]'")
            ensure_column(
                connection, "social_contents", "has_paid_product_placement",
                "INTEGER NOT NULL DEFAULT 0",
            )
            connection.executescript(SNAPSHOTS_SCHEMA)
            connection.executescript(MONITORING_SCHEMA)
            ensure_column(connection, "monitoring_runs", "project_id", "INTEGER")
            connection.executescript(AUTH_SCHEMA)
            connection.executescript(JOBS_SCHEMA)
            connection.executescript(SOURCES_SCHEMA)
            connection.executescript(PROJECTS_SCHEMA)
            connection.executescript(NICHE_SCHEMA)
            ensure_column(connection, "niches", "kind", "TEXT NOT NULL DEFAULT 'topic'")
            ensure_column(connection, "niches", "definition_json", "TEXT NOT NULL DEFAULT '{}'")
            connection.executescript(NICHE_CONTENTS_SCHEMA)
            connection.executescript(CHANNEL_PROFILES_SCHEMA)
            connection.executescript(NICHE_CHANNELS_SCHEMA)
            connection.executescript(CREATORS_SCHEMA)
            connection.executescript(COMMENT_ANALYSIS_SCHEMA)
            connection.executescript(ENTITIES_SCHEMA)
            connection.executescript(CONTENT_ENTITY_MENTIONS_SCHEMA)
            connection.executescript(CONTENT_AD_SIGNALS_SCHEMA)
            connection.executescript(PROCESSING_LOGS_SCHEMA)
            connection.executescript(TRANSCRIPTS_SCHEMA)
            connection.executescript(API_USAGE_SCHEMA)
            ensure_column(connection, "research_projects", "organization_id", "INTEGER NOT NULL DEFAULT 1")
            ensure_column(
                connection, "research_projects", "transcription_credits",
                "INTEGER NOT NULL DEFAULT 25",
            )
        seed_demo = os.getenv("SEED_DEMO_DATA", "true").lower() in {"1", "true", "yes", "on"}
        comment_count = connection.execute("SELECT COUNT(*) FROM social_comments").fetchone()[0]
        if seed_demo and comment_count == 0:
            connection.executemany(
                """INSERT INTO social_comments (
                    external_id, content_id, content_title, author_hash, text,
                    published_at, platform, niche, topic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                demo_comments(),
            )
        content_count = connection.execute("SELECT COUNT(*) FROM social_contents").fetchone()[0]
        if seed_demo and content_count == 0:
            connection.executemany(
                """INSERT INTO social_contents (
                    external_id, platform, title, description, tags_json, channel_id, channel_title,
                    published_at, duration_seconds, views, likes, comments,
                    has_paid_product_placement, niche, topic,
                    source_query, acquired_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                demo_contents(),
            )
        snapshot_count = connection.execute("SELECT COUNT(*) FROM content_snapshots").fetchone()[0]
        if seed_demo and snapshot_count == 0:
            seed_demo_snapshots(connection)
        migrate_default_project(connection)
        connection.execute(
            """UPDATE background_jobs SET status = 'queued', started_at = NULL,
               error = 'Ripreso dopo il riavvio del servizio'
               WHERE status = 'running'"""
        )


def all_comments(
    project_id: int = 1, since: str | None = None
) -> list[dict[str, Any]]:
    clauses = ["pc.project_id = ?"]
    parameters: list[Any] = [project_id]
    if since:
        clauses.append("c.published_at >= ?")
        parameters.append(since)
    query = f"""SELECT c.id, c.external_id, c.content_id, c.content_title,
                       c.author_hash, c.text, c.published_at, c.platform,
                       pc.niche, pc.topic
                FROM social_comments c
                JOIN project_comments pc ON pc.comment_id = c.id
                WHERE {' AND '.join(clauses)} ORDER BY c.published_at"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def list_niches(project_id: int = 1) -> list[dict[str, Any]]:
    """Restituisce un riepilogo testuale delle nicchie osservate nel progetto.

    Questa funzione è mantenuta per compatibilità con i report esistenti che
    usano la colonna testuale ``niche`` su ``project_contents``/``project_comments``.
    Per gestire le nuove entità ``niches`` usare :func:`list_niche_entities`.
    """
    with connect() as connection:
        query = """SELECT niche, SUM(comments) AS comments, SUM(contents) AS contents
                   FROM (
                       SELECT pc.niche, COUNT(*) AS comments, 0 AS contents
                       FROM project_comments pc
                       WHERE pc.project_id = ? AND pc.niche != '' GROUP BY pc.niche
                       UNION ALL
                       SELECT pc.niche, 0 AS comments, COUNT(*) AS contents
                       FROM project_contents pc
                       WHERE pc.project_id = ? AND pc.niche != '' GROUP BY pc.niche
                   ) GROUP BY niche ORDER BY contents DESC, comments DESC, niche"""
        return [dict(row) for row in connection.execute(query, (project_id, project_id))]


def _niche_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "kind": row["kind"] if "kind" in row.keys() else "topic",
        "definition": json.loads(
            (row["definition_json"] if "definition_json" in row.keys() else "{}") or "{}"
        ),
        "seed_channels": json.loads(row["seed_channels_json"] or "[]"),
        "seed_videos": json.loads(row["seed_videos_json"] or "[]"),
        "include_keywords": json.loads(row["include_keywords_json"] or "[]"),
        "exclude_keywords": json.loads(row["exclude_keywords_json"] or "[]"),
        "filters": json.loads(row["filters_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_niche(
    project_id: int,
    name: str,
    description: str = "",
    status: str = "draft",
    kind: str = "topic",
    definition: dict[str, Any] | None = None,
    seed_channels: list[dict[str, Any]] | None = None,
    seed_videos: list[dict[str, Any]] | None = None,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO niches (
                project_id, name, description, status, kind, definition_json,
                seed_channels_json, seed_videos_json,
                include_keywords_json, exclude_keywords_json,
                filters_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, name.strip(), description.strip(), status, kind,
                json.dumps(definition or {}, ensure_ascii=False),
                json.dumps(seed_channels or [], ensure_ascii=False),
                json.dumps(seed_videos or [], ensure_ascii=False),
                json.dumps(include_keywords or [], ensure_ascii=False),
                json.dumps(exclude_keywords or [], ensure_ascii=False),
                json.dumps(filters or {}, ensure_ascii=False),
                now, now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM niches WHERE id = ?", (int(cursor.lastrowid),)
        ).fetchone()
        if row is None:
            raise RuntimeError("Niche appena creata non recuperabile")
        return _niche_from_row(row)


def get_niche(niche_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM niches WHERE id = ?", (niche_id,)).fetchone()
        return _niche_from_row(row) if row else None


def list_niche_entities(project_id: int) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM niches WHERE project_id = ? ORDER BY name",
            (project_id,),
        ).fetchall()
        return [_niche_from_row(row) for row in rows]


def update_niche(
    niche_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    definition: dict[str, Any] | None = None,
    seed_channels: list[dict[str, Any]] | None = None,
    seed_videos: list[dict[str, Any]] | None = None,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fields: list[str] = []
    parameters: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        parameters.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        parameters.append(description.strip())
    if status is not None:
        fields.append("status = ?")
        parameters.append(status)
    if kind is not None:
        fields.append("kind = ?")
        parameters.append(kind)
    if definition is not None:
        fields.append("definition_json = ?")
        parameters.append(json.dumps(definition, ensure_ascii=False))
    if seed_channels is not None:
        fields.append("seed_channels_json = ?")
        parameters.append(json.dumps(seed_channels, ensure_ascii=False))
    if seed_videos is not None:
        fields.append("seed_videos_json = ?")
        parameters.append(json.dumps(seed_videos, ensure_ascii=False))
    if include_keywords is not None:
        fields.append("include_keywords_json = ?")
        parameters.append(json.dumps(include_keywords, ensure_ascii=False))
    if exclude_keywords is not None:
        fields.append("exclude_keywords_json = ?")
        parameters.append(json.dumps(exclude_keywords, ensure_ascii=False))
    if filters is not None:
        fields.append("filters_json = ?")
        parameters.append(json.dumps(filters, ensure_ascii=False))
    if not fields:
        return get_niche(niche_id)
    fields.append("updated_at = ?")
    parameters.append(now)
    parameters.append(niche_id)
    with connect() as connection:
        connection.execute(f"UPDATE niches SET {', '.join(fields)} WHERE id = ?", parameters)
        row = connection.execute("SELECT * FROM niches WHERE id = ?", (niche_id,)).fetchone()
        return _niche_from_row(row) if row else None


def delete_niche(niche_id: int) -> bool:
    with connect() as connection:
        connection.execute("DELETE FROM niche_channels WHERE niche_id = ?", (niche_id,))
        connection.execute("DELETE FROM niche_contents WHERE niche_id = ?", (niche_id,))
        cursor = connection.execute("DELETE FROM niches WHERE id = ?", (niche_id,))
        return bool(cursor.rowcount)


def _channel_profile_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "platform": row["platform"],
        "channel_id": row["channel_id"],
        "channel_title": row["title"],
        "custom_url": row["custom_url"],
        "description": row["description"],
        "country": row["country"],
        "language": row["default_language"],
        "subscribers": row["subscribers"],
        "declared_video_count": row["video_count"],
        "themes": json.loads(row["themes_json"] or "[]"),
        "metrics": json.loads(row["metrics_json"] or "{}"),
        "computed_at": row["computed_at"],
    }


def upsert_channel_profiles(
    project_id: int, channels: list[dict[str, Any]], connection: Any | None = None,
) -> list[dict[str, Any]]:
    """Upsert idempotente dei profili, distinti per progetto/piattaforma/canale."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def run(db: Any) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for channel in channels:
            platform = channel.get("platform") or "YouTube"
            channel_id = (channel.get("channel_id") or "").strip()
            if not channel_id:
                continue
            metrics = {
                key: channel.get(key)
                for key in (
                    "video_count", "total_views", "avg_views", "max_views",
                    "engagement_rate", "last_published_at", "anomalous_videos",
                    "score", "score_breakdown", "candidate_level", "circles",
                )
                if key in channel
            }
            parameters = (
                channel.get("channel_title", ""), channel.get("custom_url", ""),
                channel.get("description", ""), channel.get("country", ""),
                channel.get("language", ""), int(channel.get("subscribers", 0) or 0),
                int(channel.get("declared_video_count", 0) or 0),
                json.dumps(channel.get("themes", []), ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False), now,
                project_id, platform, channel_id,
            )
            updated = db.execute(
                """UPDATE channel_profiles SET title = ?, custom_url = ?, description = ?,
                   country = ?, default_language = ?, subscribers = ?, video_count = ?,
                   themes_json = ?, metrics_json = ?, computed_at = ?
                   WHERE project_id = ? AND platform = ? AND channel_id = ?""",
                parameters,
            )
            if not updated.rowcount:
                db.execute(
                    """INSERT INTO channel_profiles (
                       project_id, platform, channel_id, title, custom_url, description,
                       country, default_language, subscribers, video_count, themes_json,
                       metrics_json, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id, platform, channel_id, channel.get("channel_title", ""),
                        channel.get("custom_url", ""), channel.get("description", ""),
                        channel.get("country", ""), channel.get("language", ""),
                        int(channel.get("subscribers", 0) or 0),
                        int(channel.get("declared_video_count", 0) or 0),
                        json.dumps(channel.get("themes", []), ensure_ascii=False),
                        json.dumps(metrics, ensure_ascii=False), now,
                    ),
                )
            row = db.execute(
                """SELECT * FROM channel_profiles
                   WHERE project_id = ? AND platform = ? AND channel_id = ?""",
                (project_id, platform, channel_id),
            ).fetchone()
            if row:
                profiles.append(_channel_profile_from_row(row))
        return profiles

    if connection is not None:
        return run(connection)
    with connect() as db:
        return run(db)


def list_channel_profiles(
    project_id: int, platform: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM channel_profiles WHERE project_id = ?"
    parameters: list[Any] = [project_id]
    if platform:
        query += " AND platform = ?"
        parameters.append(platform)
    query += " ORDER BY title, platform"
    with connect() as connection:
        return [_channel_profile_from_row(row) for row in connection.execute(query, parameters)]


def sync_niche_channels(
    project_id: int,
    niche_id: int,
    channels: list[dict[str, Any]],
    *,
    replace: bool = True,
) -> list[dict[str, Any]]:
    """Salva profili e membership in una transazione, senza duplicati."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        owner = connection.execute(
            "SELECT project_id FROM niches WHERE id = ?", (niche_id,)
        ).fetchone()
        if owner is None or int(owner["project_id"]) != project_id:
            raise ValueError("Nicchia non trovata nel progetto")
        profiles = upsert_channel_profiles(project_id, channels, connection=connection)
        profile_ids = {profile["channel_id"]: profile["id"] for profile in profiles}
        if replace:
            connection.execute("DELETE FROM niche_channels WHERE niche_id = ?", (niche_id,))
        for channel in channels:
            profile_id = profile_ids.get(channel.get("channel_id", ""))
            if profile_id is None:
                continue
            matched = [theme["term"] for theme in channel.get("themes", [])[:12]]
            connection.execute(
                """INSERT INTO niche_channels (
                   niche_id, channel_profile_id, relevance_score, matched_themes_json, added_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(niche_id, channel_profile_id) DO UPDATE SET
                   relevance_score = excluded.relevance_score,
                   matched_themes_json = excluded.matched_themes_json,
                   added_at = excluded.added_at""",
                (
                    niche_id, profile_id, float(channel.get("score", 0.0) or 0.0),
                    json.dumps(matched, ensure_ascii=False), now,
                ),
            )
    return list_niche_channels(niche_id)


def list_niche_channels(niche_id: int) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT cp.*, nc.relevance_score, nc.matched_themes_json, nc.added_at
               FROM niche_channels nc
               JOIN channel_profiles cp ON cp.id = nc.channel_profile_id
               WHERE nc.niche_id = ?
               ORDER BY nc.relevance_score DESC, cp.title""",
            (niche_id,),
        ).fetchall()
    result = []
    for row in rows:
        profile = _channel_profile_from_row(row)
        profile.update({
            "relevance_score": row["relevance_score"],
            "matched_themes": json.loads(row["matched_themes_json"] or "[]"),
            "added_at": row["added_at"],
        })
        result.append(profile)
    return result


def create_creator_link(
    project_id: int,
    display_name: str,
    channel_profile_ids: list[int],
) -> dict[str, Any]:
    """Collega manualmente profili multipiattaforma a una identità creator."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO creators (project_id, display_name, created_at) VALUES (?, ?, ?)",
            (project_id, display_name.strip(), now),
        )
        creator_id = int(cursor.lastrowid)
        for profile_id in dict.fromkeys(channel_profile_ids):
            allowed = connection.execute(
                "SELECT 1 FROM channel_profiles WHERE id = ? AND project_id = ?",
                (profile_id, project_id),
            ).fetchone()
            if not allowed:
                raise ValueError("Profilo canale non trovato nel progetto")
            connection.execute(
                """INSERT INTO creator_links (
                   creator_id, channel_profile_id, link_method, confidence, created_at
                ) VALUES (?, ?, 'manual', 1.0, ?)""",
                (creator_id, profile_id, now),
            )
    return get_creator(creator_id) or {}


def get_creator(creator_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        creator = connection.execute(
            "SELECT * FROM creators WHERE id = ?", (creator_id,)
        ).fetchone()
        if not creator:
            return None
        links = connection.execute(
            """SELECT cp.* FROM creator_links cl
               JOIN channel_profiles cp ON cp.id = cl.channel_profile_id
               WHERE cl.creator_id = ? ORDER BY cp.platform, cp.title""",
            (creator_id,),
        ).fetchall()
    return {
        "id": creator["id"], "project_id": creator["project_id"],
        "display_name": creator["display_name"], "created_at": creator["created_at"],
        "profiles": [_channel_profile_from_row(row) for row in links],
    }


def search_comments(query: str, project_id: int = 1, niche: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    clauses = ["pc.project_id = ?", "LOWER(c.text) LIKE LOWER(?)"]
    parameters: list[Any] = [project_id, f"%{query}%"]
    if niche:
        clauses.append("pc.niche = ?")
        parameters.append(niche)
    parameters.append(limit)
    statement = f"""SELECT c.external_id, c.content_id, c.content_title, c.author_hash, c.text,
                             c.published_at, c.platform, pc.niche, pc.topic
                     FROM social_comments c
                     JOIN project_comments pc ON pc.comment_id = c.id
                     WHERE {' AND '.join(clauses)}
                     ORDER BY published_at DESC LIMIT ?"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(statement, parameters)]


def insert_comments(comments: list[dict[str, Any]], project_id: int = 1) -> int:
    inserted = 0
    with connect() as connection:
        for comment in comments:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO social_comments (
                    external_id, content_id, content_title, author_hash, text,
                    published_at, platform, niche, topic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comment["external_id"], comment["content_id"],
                    comment.get("content_title", ""), comment["author_hash"],
                    comment["text"], comment["published_at"],
                    comment.get("platform", "YouTube"), comment.get("niche", ""),
                    comment.get("topic", ""),
                ),
            )
            comment_id = connection.execute(
                "SELECT id FROM social_comments WHERE external_id = ?",
                (comment["external_id"],),
            ).fetchone()[0]
            membership = connection.execute(
                """INSERT OR IGNORE INTO project_comments
                   (project_id, comment_id, niche, topic, added_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    project_id, comment_id, comment.get("niche", ""),
                    comment.get("topic", ""),
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                ),
            )
            inserted += membership.rowcount
    return inserted


def all_contents(
    project_id: int = 1, since: str | None = None
) -> list[dict[str, Any]]:
    clauses = ["pc.project_id = ?"]
    parameters: list[Any] = [project_id]
    if since:
        clauses.append("c.published_at >= ?")
        parameters.append(since)
    query = f"""SELECT c.id, c.external_id, c.platform, c.title, c.description, c.tags_json,
                       c.channel_id, c.channel_title, c.published_at,
                       c.duration_seconds, c.views, c.likes, c.comments,
                       c.has_paid_product_placement,
                       pc.niche, pc.topic, pc.source_query, c.acquired_at
                FROM social_contents c
                JOIN project_contents pc ON pc.content_id = c.id
                WHERE {' AND '.join(clauses)} ORDER BY c.published_at"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def all_snapshots() -> list[dict[str, Any]]:
    with connect() as connection:
        query = "SELECT * FROM content_snapshots ORDER BY captured_at"
        return [dict(row) for row in connection.execute(query)]


def project_snapshots(
    project_id: int | None = None, external_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Snapshot limitati ai contenuti del progetto o a una lista di external_id.

    ``content_snapshots`` non è per-progetto: senza questo filtro i report
    leggerebbero anche gli snapshot di contenuti di altri progetti. Quando
    ``external_ids`` è fornita (tipicamente dai contenuti già filtrati per
    periodo) la query resta piccola anche su dataset grandi.
    """
    if external_ids is not None:
        if not external_ids:
            return []
        placeholders = ",".join("?" for _ in external_ids)
        query = f"""SELECT * FROM content_snapshots
                    WHERE external_id IN ({placeholders})
                    ORDER BY captured_at"""
        with connect() as connection:
            return [dict(row) for row in connection.execute(query, external_ids)]
    if project_id is None:
        return all_snapshots()
    query = """SELECT s.* FROM content_snapshots s
               WHERE s.external_id IN (
                   SELECT c.external_id FROM social_contents c
                   JOIN project_contents pc ON pc.content_id = c.id
                   WHERE pc.project_id = ?
               )
               ORDER BY s.captured_at"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, (project_id,))]


def refreshable_content_ids(niche: str | None = None, limit: int = 200, project_id: int | None = None) -> list[str]:
    clauses = ["c.platform = 'YouTube'", "c.external_id NOT LIKE 'demo-%'"]
    parameters: list[Any] = []
    join = ""
    if project_id is not None:
        join = "JOIN project_contents pc ON pc.content_id = c.id"
        clauses.append("pc.project_id = ?")
        parameters.append(project_id)
    if niche:
        clauses.append("pc.niche = ?" if project_id is not None else "c.niche = ?")
        parameters.append(niche)
    parameters.append(limit)
    query = f"SELECT DISTINCT c.external_id FROM social_contents c {join} WHERE {' AND '.join(clauses)} ORDER BY c.acquired_at DESC LIMIT ?"
    with connect() as connection:
        return [row[0] for row in connection.execute(query, parameters)]


def project_content_targets(
    project_id: int, niche: str | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    clauses = ["pc.project_id = ?", "c.platform = 'YouTube'", "c.external_id NOT LIKE 'demo-%'"]
    parameters: list[Any] = [project_id]
    if niche:
        clauses.append("pc.niche = ?")
        parameters.append(niche)
    parameters.append(limit)
    query = f"""SELECT c.external_id, c.title, pc.niche, pc.topic
                FROM social_contents c
                JOIN project_contents pc ON pc.content_id = c.id
                WHERE {' AND '.join(clauses)}
                ORDER BY c.views DESC LIMIT ?"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def upsert_contents(contents: list[dict[str, Any]], project_id: int = 1) -> int:
    changed = 0
    with connect() as connection:
        for content in contents:
            connection.execute(
                """INSERT INTO social_contents (
                    external_id, platform, title, description, tags_json, channel_id, channel_title,
                    published_at, duration_seconds, views, likes, comments,
                    has_paid_product_placement, niche, topic,
                    source_query, acquired_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, external_id) DO UPDATE SET
                    title=excluded.title, description=excluded.description, tags_json=excluded.tags_json,
                    channel_id=excluded.channel_id, channel_title=excluded.channel_title,
                    duration_seconds=excluded.duration_seconds, views=excluded.views,
                    likes=excluded.likes, comments=excluded.comments,
                    has_paid_product_placement=excluded.has_paid_product_placement,
                    niche=excluded.niche, topic=excluded.topic,
                    source_query=excluded.source_query, acquired_at=excluded.acquired_at""",
                (
                    content["external_id"], content.get("platform", "YouTube"),
                    content["title"], content.get("description", ""),
                    content.get("tags_json") or json.dumps(content.get("tags", []), ensure_ascii=False),
                    content.get("channel_id", ""), content.get("channel_title", ""),
                    content["published_at"], content.get("duration_seconds", 0),
                    content.get("views", 0), content.get("likes", 0),
                    content.get("comments", 0),
                    int(bool(content.get("has_paid_product_placement", False))),
                    content.get("niche", ""),
                    content.get("topic", ""), content.get("source_query", ""),
                    content["acquired_at"],
                ),
            )
            content_id = connection.execute(
                "SELECT id FROM social_contents WHERE platform = ? AND external_id = ?",
                (content.get("platform", "YouTube"), content["external_id"]),
            ).fetchone()[0]
            membership = connection.execute(
                """INSERT INTO project_contents
                   (project_id, content_id, niche, topic, source_query, added_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, content_id) DO UPDATE SET
                       niche=excluded.niche, topic=excluded.topic,
                       source_query=excluded.source_query""",
                (
                    project_id, content_id, content.get("niche", ""),
                    content.get("topic", ""), content.get("source_query", ""),
                    content["acquired_at"],
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO content_snapshots
                   (external_id, platform, captured_at, views, likes, comments)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    content["external_id"], content.get("platform", "YouTube"),
                    content["acquired_at"], content.get("views", 0),
                    content.get("likes", 0), content.get("comments", 0),
                ),
            )
            changed += max(membership.rowcount, 0)
    return changed


def upsert_contents_for_niche(
    project_id: int, niche_id: int, niche_name: str, contents: list[dict[str, Any]]
) -> dict[str, int]:
    """Salva contenuti associandoli a un progetto e a una nicchia entità."""
    stored = 0
    linked = 0
    with connect() as connection:
        for content in contents:
            connection.execute(
                """INSERT INTO social_contents (
                    external_id, platform, title, description, tags_json, channel_id, channel_title,
                    published_at, duration_seconds, views, likes, comments,
                    has_paid_product_placement, niche, topic,
                    source_query, acquired_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, external_id) DO UPDATE SET
                    title=excluded.title, description=excluded.description, tags_json=excluded.tags_json,
                    channel_id=excluded.channel_id, channel_title=excluded.channel_title,
                    duration_seconds=excluded.duration_seconds, views=excluded.views,
                    likes=excluded.likes, comments=excluded.comments,
                    has_paid_product_placement=excluded.has_paid_product_placement,
                    niche=excluded.niche, topic=excluded.topic,
                    source_query=excluded.source_query, acquired_at=excluded.acquired_at""",
                (
                    content["external_id"], content.get("platform", "YouTube"),
                    content["title"], content.get("description", ""),
                    content.get("tags_json") or json.dumps(content.get("tags", []), ensure_ascii=False),
                    content.get("channel_id", ""), content.get("channel_title", ""),
                    content["published_at"], content.get("duration_seconds", 0),
                    content.get("views", 0), content.get("likes", 0),
                    content.get("comments", 0),
                    int(bool(content.get("has_paid_product_placement", False))),
                    niche_name,
                    content.get("topic", ""), content.get("source_query", ""),
                    content["acquired_at"],
                ),
            )
            content_id = connection.execute(
                "SELECT id FROM social_contents WHERE platform = ? AND external_id = ?",
                (content.get("platform", "YouTube"), content["external_id"]),
            ).fetchone()[0]
            membership = connection.execute(
                """INSERT INTO project_contents
                   (project_id, content_id, niche, topic, source_query, added_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, content_id) DO UPDATE SET
                       niche=excluded.niche, topic=excluded.topic,
                       source_query=excluded.source_query""",
                (
                    project_id, content_id, niche_name,
                    content.get("topic", ""), content.get("source_query", ""),
                    content["acquired_at"],
                ),
            )
            connection.execute(
                """INSERT INTO niche_contents
                   (niche_id, content_id, relevance_score, matched_seed, matched_value, added_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(niche_id, content_id) DO UPDATE SET
                       relevance_score=excluded.relevance_score,
                       matched_seed=excluded.matched_seed,
                       matched_value=excluded.matched_value""",
                (
                    niche_id, content_id,
                    content.get("relevance_score", 0.0),
                    content.get("matched_seed", ""),
                    content.get("matched_value", ""),
                    content["acquired_at"],
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO content_snapshots
                   (external_id, platform, captured_at, views, likes, comments)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    content["external_id"], content.get("platform", "YouTube"),
                    content["acquired_at"], content.get("views", 0),
                    content.get("likes", 0), content.get("comments", 0),
                ),
            )
            stored += 1
            linked += membership.rowcount
    return {"stored": stored, "project_linked": linked}


def update_content_metrics(metrics: list[dict[str, Any]], captured_at: str) -> int:
    updated = 0
    with connect() as connection:
        for item in metrics:
            cursor = connection.execute(
                """UPDATE social_contents
                   SET views = ?, likes = ?, comments = ?, acquired_at = ?
                   WHERE platform = 'YouTube' AND external_id = ?""",
                (item["views"], item["likes"], item["comments"], captured_at, item["external_id"]),
            )
            if cursor.rowcount:
                connection.execute(
                    """INSERT OR IGNORE INTO content_snapshots
                       (external_id, platform, captured_at, views, likes, comments)
                       VALUES (?, 'YouTube', ?, ?, ?, ?)""",
                    (item["external_id"], captured_at, item["views"], item["likes"], item["comments"]),
                )
                updated += 1
    return updated


def start_monitoring_run(trigger: str, started_at: str, project_id: int | None = None) -> int:
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO monitoring_runs (trigger, started_at, project_id)
               VALUES (?, ?, ?)""",
            (trigger, started_at, project_id),
        )
        return int(cursor.lastrowid)


def finish_monitoring_run(
    run_id: int, finished_at: str, status: str, requested: int = 0,
    received: int = 0, updated: int = 0, error: str = "",
) -> None:
    with connect() as connection:
        connection.execute(
            """UPDATE monitoring_runs
               SET finished_at = ?, status = ?, requested = ?, received = ?,
                   updated = ?, error = ? WHERE id = ?""",
            (finished_at, status, requested, received, updated, error[:500], run_id),
        )


def monitoring_runs(limit: int = 10, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as connection:
        if project_id is None:
            query = "SELECT * FROM monitoring_runs ORDER BY started_at DESC LIMIT ?"
            parameters: tuple[Any, ...] = (limit,)
        else:
            query = """SELECT * FROM monitoring_runs WHERE project_id = ?
                       ORDER BY started_at DESC LIMIT ?"""
            parameters = (project_id, limit)
        return [dict(row) for row in connection.execute(query, parameters)]


def enqueue_background_job(project_id: int, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        existing = connection.execute(
            """SELECT * FROM background_jobs
               WHERE project_id = ? AND job_type = ? AND payload_json = ?
                 AND status IN ('queued', 'running')
               ORDER BY id DESC LIMIT 1""",
            (project_id, job_type, payload_json),
        ).fetchone()
        if existing:
            return dict(existing)
        cursor = connection.execute(
            """INSERT INTO background_jobs
               (project_id, job_type, payload_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (project_id, job_type, payload_json, created_at),
        )
        row = connection.execute(
            "SELECT * FROM background_jobs WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)


def claim_background_job() -> dict[str, Any] | None:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT * FROM background_jobs
               WHERE status = 'queued' AND cancel_requested = 0
               ORDER BY created_at, id LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            """UPDATE background_jobs SET status = 'running', started_at = ?,
               progress = 1 WHERE id = ?""",
            (started_at, row["id"]),
        )
        claimed = dict(row)
        claimed.update({"status": "running", "started_at": started_at, "progress": 1})
        return claimed


def update_background_job(job_id: int, progress: int) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE background_jobs SET progress = ? WHERE id = ? AND status = 'running'",
            (max(0, min(progress, 99)), job_id),
        )


def finish_background_job(
    job_id: int, status: str, result: dict[str, Any] | None = None, error: str = ""
) -> None:
    finished_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    progress = 100 if status == "completed" else 0
    with connect() as connection:
        connection.execute(
            """UPDATE background_jobs SET status = ?, progress = ?, result_json = ?,
               error = ?, finished_at = ? WHERE id = ?""",
            (
                status, progress, json.dumps(result or {}, ensure_ascii=False),
                error[:1000], finished_at, job_id,
            ),
        )


def background_job(job_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def background_jobs(project_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as connection:
        query = """SELECT * FROM background_jobs WHERE project_id = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?"""
        return [dict(row) for row in connection.execute(query, (project_id, limit))]


def cancel_background_job(job_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE background_jobs
               SET cancel_requested = 1,
                   status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                   finished_at = CASE WHEN status = 'queued' THEN ? ELSE finished_at END
               WHERE id = ? AND status IN ('queued', 'running')""",
            (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), job_id),
        )
        return bool(cursor.rowcount)


def background_job_cancel_requested(job_id: int) -> bool:
    with connect() as connection:
        row = connection.execute(
            "SELECT cancel_requested FROM background_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return bool(row and row[0])


def reap_stalled_jobs(timeout_hours: float = 6.0) -> int:
    """Marca come falliti i job rimasti 'running' oltre il timeout.

    Copre il caso di crash o terminazione del worker mentre un job era in
    esecuzione: senza questo passaggio resterebbero 'running' per sempre.
    Restituisce il numero di job marcati.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
    ).replace(microsecond=0).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE background_jobs SET status = 'failed', progress = 0,
                   error = ?, finished_at = ?
               WHERE status = 'running' AND started_at IS NOT NULL AND started_at < ?""",
            (
                f"Job interrotto: nessun aggiornamento per oltre {timeout_hours:g} ore",
                datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                cutoff,
            ),
        )
        return int(cursor.rowcount)


def upsert_project_source(
    project_id: int, source_type: str, name: str, config: dict[str, Any],
    refresh_hours: int = 24,
) -> dict[str, Any]:
    config_json = json.dumps(config, ensure_ascii=False, sort_keys=True)
    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    next_run_at = (created_at + timedelta(hours=refresh_hours)).isoformat()
    with connect() as connection:
        connection.execute(
            """INSERT INTO project_sources
               (project_id, source_type, name, config_json, status, refresh_hours,
                created_at, next_run_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
               ON CONFLICT(project_id, source_type, config_json) DO UPDATE SET
                   name=excluded.name, refresh_hours=excluded.refresh_hours,
                   status='active'""",
            (
                project_id, source_type, name.strip(), config_json, refresh_hours,
                created_at.isoformat(), next_run_at,
            ),
        )
        row = connection.execute(
            """SELECT * FROM project_sources
               WHERE project_id = ? AND source_type = ? AND config_json = ?""",
            (project_id, source_type, config_json),
        ).fetchone()
        return dict(row)


def project_sources(project_id: int) -> list[dict[str, Any]]:
    with connect() as connection:
        query = """SELECT * FROM project_sources WHERE project_id = ?
                   ORDER BY created_at DESC, id DESC"""
        return [dict(row) for row in connection.execute(query, (project_id,))]


def project_source(source_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM project_sources WHERE id = ?", (source_id,)
        ).fetchone()
        return dict(row) if row else None


def update_project_source(
    source_id: int,
    status: str | None = None,
    refresh_hours: int | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    assignments = []
    parameters: list[Any] = []
    if status is not None:
        assignments.append("status = ?")
        parameters.append(status)
    if name is not None:
        assignments.append("name = ?")
        parameters.append(name.strip())
    if refresh_hours is not None:
        assignments.extend(("refresh_hours = ?", "next_run_at = ?"))
        parameters.extend((
            refresh_hours,
            (datetime.now(timezone.utc) + timedelta(hours=refresh_hours)).replace(microsecond=0).isoformat(),
        ))
    if not assignments:
        return project_source(source_id)
    parameters.append(source_id)
    with connect() as connection:
        connection.execute(
            f"UPDATE project_sources SET {', '.join(assignments)} WHERE id = ?",
            parameters,
        )
        row = connection.execute(
            "SELECT * FROM project_sources WHERE id = ?", (source_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_project_source(source_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM project_sources WHERE id = ?", (source_id,))
        return bool(cursor.rowcount)


def due_project_sources(now: str, limit: int = 50) -> list[dict[str, Any]]:
    with connect() as connection:
        query = """SELECT * FROM project_sources
                   WHERE status = 'active' AND next_run_at IS NOT NULL AND next_run_at <= ?
                   ORDER BY next_run_at, id LIMIT ?"""
        return [dict(row) for row in connection.execute(query, (now, limit))]


def mark_source_enqueued(source_id: int) -> None:
    source = project_source(source_id)
    if not source:
        return
    next_run_at = (
        datetime.now(timezone.utc) + timedelta(hours=int(source["refresh_hours"]))
    ).replace(microsecond=0).isoformat()
    with connect() as connection:
        connection.execute(
            "UPDATE project_sources SET next_run_at = ? WHERE id = ?",
            (next_run_at, source_id),
        )


def finish_source_run(source_id: int, error: str = "") -> None:
    source = project_source(source_id)
    if not source:
        return
    now = datetime.now(timezone.utc).replace(microsecond=0)
    next_run = (now + timedelta(hours=int(source["refresh_hours"]))).isoformat()
    with connect() as connection:
        connection.execute(
            """UPDATE project_sources SET last_run_at = ?, next_run_at = ?,
               last_error = ? WHERE id = ?""",
            (now.isoformat(), next_run, error[:1000], source_id),
        )


def ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_default_project(connection: Any) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    connection.execute(
        """INSERT OR IGNORE INTO organizations (id, name, created_at)
           VALUES (1, 'SignalDesk Workspace', ?)""",
        (now,),
    )
    connection.execute(
        """INSERT OR IGNORE INTO research_projects
           (id, organization_id, name, description, created_at)
           VALUES (1, 1, 'Osservatorio principale', 'Dataset iniziale e importazioni esistenti', ?)""",
        (now,),
    )
    connection.execute(
        """INSERT OR IGNORE INTO project_contents
           (project_id, content_id, niche, topic, source_query, added_at)
           SELECT 1, id, niche, topic, source_query, acquired_at FROM social_contents"""
    )
    connection.execute(
        """INSERT OR IGNORE INTO project_comments
           (project_id, comment_id, niche, topic, added_at)
           SELECT 1, id, niche, topic, published_at FROM social_comments"""
    )
    if getattr(connection, "dialect", "sqlite") == "postgresql":
        connection.execute(
            """SELECT setval(pg_get_serial_sequence('organizations', 'id'),
               GREATEST((SELECT MAX(id) FROM organizations), 1))"""
        )
        connection.execute(
            """SELECT setval(pg_get_serial_sequence('research_projects', 'id'),
               GREATEST((SELECT MAX(id) FROM research_projects), 1))"""
        )


def list_projects(user_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as connection:
        membership_join = ""
        parameters: tuple[Any, ...] = ()
        if user_id is not None:
            membership_join = "JOIN organization_members om ON om.organization_id = p.organization_id AND om.user_id = ?"
            parameters = (user_id,)
        query = """SELECT p.id, p.name, p.description, p.created_at,
                          p.organization_id, p.transcription_credits,
                          (SELECT COUNT(*) FROM project_contents pc WHERE pc.project_id = p.id) AS contents,
                          (SELECT COUNT(*) FROM project_comments pm WHERE pm.project_id = p.id) AS comments
                   FROM research_projects p {membership_join}
                   ORDER BY p.created_at, p.id""".format(membership_join=membership_join)
        return [dict(row) for row in connection.execute(query, parameters)]


def create_project(name: str, description: str = "", user_id: int | None = None) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        organization_id = 1
        if user_id is not None:
            membership = connection.execute(
                """SELECT organization_id FROM organization_members
                   WHERE user_id = ? ORDER BY role = 'owner' DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            if not membership:
                raise ValueError("L'utente non appartiene a un'organizzazione")
            organization_id = membership[0]
        cursor = connection.execute(
            """INSERT INTO research_projects
               (organization_id, name, description, created_at) VALUES (?, ?, ?, ?)""",
            (organization_id, name.strip(), description.strip(), created_at),
        )
        credits_row = connection.execute(
            "SELECT transcription_credits FROM research_projects WHERE id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        return {
            "id": int(cursor.lastrowid), "name": name.strip(),
            "description": description.strip(), "created_at": created_at,
            "organization_id": organization_id,
            "transcription_credits": int(credits_row[0]) if credits_row else 0,
            "contents": 0, "comments": 0,
        }


def delete_project(project_id: int, user_id: int | None = None) -> bool:
    if project_id == 1:
        return False
    with connect() as connection:
        if user_id is not None and not _project_access(connection, user_id, project_id):
            return False
        connection.execute("DELETE FROM project_sources WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM background_jobs WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM monitoring_runs WHERE project_id = ?", (project_id,))
        niche_ids = [
            row[0] for row in connection.execute(
                "SELECT id FROM niches WHERE project_id = ?", (project_id,)
            )
        ]
        profile_ids = [
            row[0] for row in connection.execute(
                "SELECT id FROM channel_profiles WHERE project_id = ?", (project_id,)
            )
        ]
        creator_ids = [
            row[0] for row in connection.execute(
                "SELECT id FROM creators WHERE project_id = ?", (project_id,)
            )
        ]
        for niche_id in niche_ids:
            connection.execute("DELETE FROM niche_channels WHERE niche_id = ?", (niche_id,))
            connection.execute("DELETE FROM niche_contents WHERE niche_id = ?", (niche_id,))
        for creator_id in creator_ids:
            connection.execute("DELETE FROM creator_links WHERE creator_id = ?", (creator_id,))
        for profile_id in profile_ids:
            connection.execute(
                "DELETE FROM creator_links WHERE channel_profile_id = ?", (profile_id,)
            )
        connection.execute("DELETE FROM creators WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM channel_profiles WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM niches WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM project_contents WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM project_comments WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM content_entity_mentions WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
        cursor = connection.execute("DELETE FROM research_projects WHERE id = ?", (project_id,))
        connection.execute(
            "DELETE FROM social_comments WHERE id NOT IN (SELECT comment_id FROM project_comments)"
        )
        orphan_ids = [
            row[0] for row in connection.execute(
                "SELECT external_id FROM social_contents WHERE id NOT IN (SELECT content_id FROM project_contents)"
            )
        ]
        connection.execute(
            "DELETE FROM social_contents WHERE id NOT IN (SELECT content_id FROM project_contents)"
        )
        if orphan_ids:
            placeholders = ",".join("?" for _ in orphan_ids)
            connection.execute(
                f"DELETE FROM content_snapshots WHERE external_id IN ({placeholders})", orphan_ids
            )
        return bool(cursor.rowcount)


def delete_project_contents(project_id: int, niche: str | None = None) -> dict[str, int]:
    """Scollega i contenuti (e i commenti associati) da un progetto.

    Rimuove le righe di collegamento ``project_contents``; i record globali
    restano disponibili per altri progetti. Con ``niche`` si limita la
    cancellazione a un sottoinsieme. Restituisce i conteggi per la conferma
    in UI. Elimina anche i contenuti diventati orfani (nessun progetto).
    """
    with connect() as connection:
        clauses = ["project_id = ?"]
        parameters: list[Any] = [project_id]
        if niche:
            clauses.append("niche = ?")
            parameters.append(niche)
        where = " AND ".join(clauses)
        content_ids = [
            row[0] for row in connection.execute(
                f"SELECT content_id FROM project_contents WHERE {where}", parameters
            )
        ]
        cursor = connection.execute(
            f"DELETE FROM project_contents WHERE {where}", parameters
        )
        detached = int(cursor.rowcount)
        removed_orphans = 0
        if content_ids:
            placeholders = ",".join("?" for _ in content_ids)
            cursor = connection.execute(
                f"""DELETE FROM social_contents
                    WHERE id IN ({placeholders})
                      AND id NOT IN (SELECT content_id FROM project_contents)""",
                content_ids,
            )
            removed_orphans = int(cursor.rowcount)
        connection.execute(
            "DELETE FROM social_comments WHERE id NOT IN (SELECT comment_id FROM project_comments)"
        )
        return {"detached": detached, "orphans_removed": removed_orphans}


def _project_access(connection: sqlite3.Connection, user_id: int, project_id: int) -> bool:
    row = connection.execute(
        """SELECT 1 FROM research_projects p
           JOIN organization_members om ON om.organization_id = p.organization_id
           WHERE p.id = ? AND om.user_id = ?""",
        (project_id, user_id),
    ).fetchone()
    return bool(row)


def user_can_access_project(user_id: int, project_id: int) -> bool:
    with connect() as connection:
        return _project_access(connection, user_id, project_id)


def create_user_account(email: str, password_hash: str, organization_name: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, now),
        )
        user_id = int(cursor.lastrowid)
        unclaimed = connection.execute(
            """SELECT o.id FROM organizations o
               LEFT JOIN organization_members om ON om.organization_id = o.id
               WHERE om.user_id IS NULL AND o.id = 1"""
        ).fetchone()
        if unclaimed:
            organization_id = 1
            connection.execute(
                "UPDATE organizations SET name = ? WHERE id = 1",
                (organization_name.strip() or "Workspace principale",),
            )
        else:
            organization = connection.execute(
                "INSERT INTO organizations (name, created_at) VALUES (?, ?)",
                (organization_name.strip() or "Nuovo workspace", now),
            )
            organization_id = int(organization.lastrowid)
            connection.execute(
                """INSERT INTO research_projects
                   (organization_id, name, description, created_at)
                   VALUES (?, ?, '', ?)""",
                (organization_id, f"Osservatorio {user_id}", now),
            )
        connection.execute(
            """INSERT INTO organization_members (organization_id, user_id, role)
               VALUES (?, ?, 'owner')""",
            (organization_id, user_id),
        )
        return {"id": user_id, "email": email.lower().strip(), "organization_id": organization_id}


def user_by_email(email: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_user_session(token_hash: str, user_id: int, expires_at: str) -> None:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        connection.execute(
            """INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (token_hash, user_id, created_at, expires_at),
        )


def session_user(token_hash: str, now: str) -> dict[str, Any] | None:
    with connect() as connection:
        connection.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
        row = connection.execute(
            """SELECT u.id, u.email FROM users u
               JOIN user_sessions s ON s.user_id = u.id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash, now),
        ).fetchone()
        return dict(row) if row else None


def delete_user_session(token_hash: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))


def unprocessed_comments(project_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with connect() as connection:
        query = """SELECT c.id, c.external_id, c.text, c.platform
                   FROM social_comments c
                   JOIN project_comments pc ON pc.comment_id = c.id
                   WHERE pc.project_id = ? AND c.id NOT IN (
                       SELECT comment_id FROM comment_analysis
                   )
                   LIMIT ?"""
        return [dict(row) for row in connection.execute(query, (project_id, limit))]


def save_comment_analysis(analyses: list[dict[str, Any]]) -> int:
    if not analyses:
        return 0
    with connect() as connection:
        connection.executemany(
            """INSERT INTO comment_analysis
               (comment_id, language, sentiment, sentiment_score, intent,
                toxicity_score, flags_json, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(comment_id) DO UPDATE SET
                   language=excluded.language,
                   sentiment=excluded.sentiment,
                   sentiment_score=excluded.sentiment_score,
                   intent=excluded.intent,
                   toxicity_score=excluded.toxicity_score,
                   flags_json=excluded.flags_json,
                   processed_at=excluded.processed_at""",
            [
                (
                    a["comment_id"], a.get("language", ""), a.get("sentiment", "neutral"),
                    a.get("sentiment_score", 0.0), a.get("intent", "other"),
                    a.get("toxicity_score", 0.0),
                    json.dumps(a.get("flags", []), ensure_ascii=False),
                    a["processed_at"],
                )
                for a in analyses
            ],
        )
        return len(analyses)


def comment_analysis_summary(project_id: int, niche: str | None = None) -> dict[str, Any]:
    clauses = ["pc.project_id = ?"]
    params: list[Any] = [project_id]
    if niche:
        clauses.append("pc.niche = ?")
        params.append(niche)
    where = " AND ".join(clauses)
    with connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM social_comments c JOIN project_comments pc ON pc.comment_id = c.id WHERE {where}",
            params,
        ).fetchone()[0]
        analyzed = connection.execute(
            f"""SELECT COUNT(*) FROM comment_analysis ca
                JOIN project_comments pc ON pc.comment_id = ca.comment_id
                WHERE {where}""",
            params,
        ).fetchone()[0]
        sentiment_rows = connection.execute(
            f"""SELECT ca.sentiment, COUNT(*) AS count
                FROM comment_analysis ca
                JOIN project_comments pc ON pc.comment_id = ca.comment_id
                WHERE {where}
                GROUP BY ca.sentiment""",
            params,
        ).fetchall()
        intent_rows = connection.execute(
            f"""SELECT ca.intent, COUNT(*) AS count
                FROM comment_analysis ca
                JOIN project_comments pc ON pc.comment_id = ca.comment_id
                WHERE {where}
                GROUP BY ca.intent""",
            params,
        ).fetchall()
        flagged = connection.execute(
            f"""SELECT COUNT(*) FROM comment_analysis ca
                JOIN project_comments pc ON pc.comment_id = ca.comment_id
                WHERE {where} AND ca.toxicity_score > 0""",
            params,
        ).fetchone()[0]
    return {
        "total_comments": total,
        "analyzed": analyzed,
        "sentiment": {row["sentiment"]: row["count"] for row in sentiment_rows},
        "intent": {row["intent"]: row["count"] for row in intent_rows},
        "flagged": flagged,
    }


def add_processing_log(project_id: int, action: str, details: dict[str, Any]) -> None:
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        connection.execute(
            """INSERT INTO processing_logs (project_id, action, details_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (project_id, action, json.dumps(details, ensure_ascii=False), created_at),
        )


def comments_with_channel(
    project_id: int, niche: str | None = None
) -> list[dict[str, Any]]:
    """Restituisce i commenti del progetto arricchiti con il canale del contenuto."""
    clauses = ["pc.project_id = ?"]
    params: list[Any] = [project_id]
    if niche:
        clauses.append("pc.niche = ?")
        params.append(niche)
    where = " AND ".join(clauses)
    with connect() as connection:
        query = f"""SELECT c.author_hash, sc.channel_title
                    FROM social_comments c
                    JOIN project_comments pc ON pc.comment_id = c.id
                    JOIN social_contents sc ON sc.external_id = c.content_id
                        AND sc.platform = c.platform
                    WHERE {where}"""
        return [dict(row) for row in connection.execute(query, params)]


def processing_logs(project_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """SELECT id, project_id, action, details_json, created_at
               FROM processing_logs WHERE project_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "action": row["action"],
                "details": json.loads(row["details_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def demo_comments() -> list[tuple[Any, ...]]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rows: list[tuple[Any, ...]] = []
    topics = {
        "Corsa amatoriale": ["Allenamento", "Recupero", "Scarpe"],
        "Alimentazione vegetale": ["Proteine", "Recupero", "Sostenibilità"],
    }
    texts = {
        "Allenamento": "Come posso impostare il primo allenamento?",
        "Recupero": "Il recupero dopo lo sport è davvero importante.",
        "Scarpe": "Quali scarpe consigliate per iniziare?",
        "Proteine": "Dove trovate proteine vegetali complete?",
        "Sostenibilità": "Interessante il confronto sull'impatto ambientale.",
    }

    counter = 0
    for days_ago in range(1, 15):
        for niche_index, (niche, niche_topics) in enumerate(topics.items()):
            for item in range(3):
                counter += 1
                topic = niche_topics[(days_ago + item) % len(niche_topics)]
                author = f"usr-{(days_ago * 3 + item + niche_index * 7) % 31:03d}"
                published = now - timedelta(days=days_ago, hours=8 - item * 3)
                rows.append((
                    f"comment-{counter}", f"video-{niche_index}-{days_ago % 4}",
                    "Allenarsi senza estremismi" if niche_index == 0 else "Proteine e vita quotidiana",
                    author, f"{texts[topic]} Esperienza {days_ago}-{item}.",
                    published.isoformat(), "YouTube", niche, topic,
                ))

    burst_start = now - timedelta(hours=5)
    repeated = [
        "Questo profilo mente, segnalatelo subito!",
        "Questo profilo mente segnalatelo subito",
        "Segnalate questo profilo, sta mentendo!",
    ]
    for index in range(36):
        author = f"burst-{index % 9:03d}"
        rows.append((
            f"burst-{index}", "video-investigation", "Integratori: cosa dicono i dati",
            author, repeated[index % len(repeated)],
            (burst_start + timedelta(minutes=index % 12, seconds=index * 7)).isoformat(),
            "YouTube", "Corsa amatoriale", "Integratori",
        ))
    return rows


def demo_contents() -> list[tuple[Any, ...]]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows: list[tuple[Any, ...]] = []
    niches = [
        ("Corsa amatoriale", ["RunLab", "Passo Lento", "Coach Marta"], ["Recupero", "Allenamento", "Scarpe"]),
        ("Alimentazione vegetale", ["Piatto Verde", "Nutrizione Chiara", "Plant Lab"], ["Proteine", "Recupero", "Sostenibilità"]),
    ]
    for niche_index, (niche, channels, topics) in enumerate(niches):
        for index in range(15):
            topic = topics[index % len(topics)]
            channel = channels[index % len(channels)]
            views = 4200 + index * 1700 + niche_index * 900
            if index in {3, 11}:
                views *= 4
            published = now - timedelta(days=index * 2 + niche_index)
            rows.append((
                f"demo-video-{niche_index}-{index}", "YouTube",
                f"{topic}: guida ed esperienza #{index + 1}",
                f"Conversazione pubblica su {topic.lower()}.",
                json.dumps([topic.lower(), niche.lower(), "community"], ensure_ascii=False),
                f"channel-{niche_index}-{index % len(channels)}", channel,
                published.isoformat(), 240 + index * 18, views,
                int(views * (0.045 + (index % 3) * 0.008)), int(views * 0.006),
                0, niche, topic, niche.lower(), now.isoformat(),
            ))
    return rows


def seed_demo_snapshots(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = connection.execute(
        """SELECT external_id, platform, published_at, views, likes, comments
           FROM social_contents"""
    ).fetchall()
    snapshots = []
    for row in rows:
        published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published > now - timedelta(hours=12):
            continue
        earlier = max(published + timedelta(hours=1), now - timedelta(days=3))
        snapshots.extend([
            (row["external_id"], row["platform"], earlier.isoformat(), int(row["views"] * .68), int(row["likes"] * .7), int(row["comments"] * .72)),
            (row["external_id"], row["platform"], now.isoformat(), row["views"], row["likes"], row["comments"]),
        ])
    connection.executemany(
        """INSERT OR IGNORE INTO content_snapshots
           (external_id, platform, captured_at, views, likes, comments)
           VALUES (?, ?, ?, ?, ?, ?)""",
        snapshots,
    )


def _entity_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        mentions = row["mentions"]
    except (KeyError, IndexError):
        mentions = 0
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "type": row["type"],
        "sector": row["sector"],
        "aliases": json.loads(row["aliases_json"] or "[]"),
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "mentions": mentions,
    }


def create_entity(
    project_id: int,
    name: str,
    type: str = "brand",
    sector: str = "",
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            """INSERT INTO entities (
                project_id, name, type, sector, aliases_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, name.strip(), type.strip(), sector.strip(),
                json.dumps(aliases or [], ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                now, now,
            ),
        )
        row = connection.execute("SELECT * FROM entities WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        if row is None:
            raise RuntimeError("Entità appena creata non recuperabile")
        return _entity_from_row(row)


def get_entity(entity_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """SELECT e.*, COUNT(m.id) AS mentions
               FROM entities e
               LEFT JOIN content_entity_mentions m ON m.entity_id = e.id
               WHERE e.id = ? GROUP BY e.id""",
            (entity_id,),
        ).fetchone()
        return _entity_from_row(row) if row else None


def list_entities(
    project_id: int,
    type: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = ["e.project_id = ?"]
    parameters: list[Any] = [project_id]
    if type:
        clauses.append("e.type = ?")
        parameters.append(type)
    if search:
        clauses.append("(LOWER(e.name) LIKE LOWER(?) OR LOWER(e.aliases_json) LIKE LOWER(?))")
        parameters.extend([f"%{search}%", f"%{search}%"])
    parameters.extend([limit, offset])
    query = f"""SELECT e.*, COUNT(m.id) AS mentions
                FROM entities e
                LEFT JOIN content_entity_mentions m ON m.entity_id = e.id
                WHERE {' AND '.join(clauses)}
                GROUP BY e.id
                ORDER BY mentions DESC, e.name
                LIMIT ? OFFSET ?"""
    with connect() as connection:
        return [_entity_from_row(row) for row in connection.execute(query, parameters)]


def update_entity(
    entity_id: int,
    name: str | None = None,
    type: str | None = None,
    sector: str | None = None,
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    fields: list[str] = []
    parameters: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        parameters.append(name.strip())
    if type is not None:
        fields.append("type = ?")
        parameters.append(type.strip())
    if sector is not None:
        fields.append("sector = ?")
        parameters.append(sector.strip())
    if aliases is not None:
        fields.append("aliases_json = ?")
        parameters.append(json.dumps(aliases, ensure_ascii=False))
    if metadata is not None:
        fields.append("metadata_json = ?")
        parameters.append(json.dumps(metadata, ensure_ascii=False))
    if not fields:
        return get_entity(entity_id)
    fields.append("updated_at = ?")
    parameters.append(now)
    parameters.append(entity_id)
    with connect() as connection:
        connection.execute(f"UPDATE entities SET {', '.join(fields)} WHERE id = ?", parameters)
        row = connection.execute(
            """SELECT e.*, COUNT(m.id) AS mentions
               FROM entities e
               LEFT JOIN content_entity_mentions m ON m.entity_id = e.id
               WHERE e.id = ? GROUP BY e.id""",
            (entity_id,),
        ).fetchone()
        return _entity_from_row(row) if row else None


def delete_entity(entity_id: int) -> bool:
    with connect() as connection:
        connection.execute("DELETE FROM content_entity_mentions WHERE entity_id = ?", (entity_id,))
        cursor = connection.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        return bool(cursor.rowcount)


def merge_entities(project_id: int, target_id: int, source_ids: list[int]) -> dict[str, Any]:
    """Unisce le entità source in target, spostando le menzioni e aggiornando alias."""
    with connect() as connection:
        target = connection.execute("SELECT * FROM entities WHERE id = ?", (target_id,)).fetchone()
        if not target or target["project_id"] != project_id:
            raise ValueError("Entità target non trovata")
        sources = connection.execute(
            "SELECT * FROM entities WHERE id IN ({}) AND project_id = ?".format(
                ",".join("?" * len(source_ids))
            ),
            (*source_ids, project_id),
        ).fetchall()
        if len(sources) != len(source_ids):
            raise ValueError("Alcune entità sorgente non trovate")

        aliases = set(json.loads(target["aliases_json"] or "[]"))
        aliases.add(target["name"])
        for source in sources:
            aliases.add(source["name"])
            aliases.update(json.loads(source["aliases_json"] or "[]"))

        # Sposta le menzioni dalle sorgenti al target.
        for source in sources:
            mentions = connection.execute(
                "SELECT * FROM content_entity_mentions WHERE entity_id = ?", (source["id"],)
            ).fetchall()
            for mention in mentions:
                connection.execute(
                    """INSERT OR IGNORE INTO content_entity_mentions (
                        project_id, content_id, entity_id, mention_text, context, confidence, source, extracted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mention["project_id"], mention["content_id"], target_id,
                        mention["mention_text"], mention["context"], mention["confidence"],
                        mention["source"], mention["extracted_at"],
                    ),
                )
            connection.execute("DELETE FROM content_entity_mentions WHERE entity_id = ?", (source["id"],))
            connection.execute("DELETE FROM entities WHERE id = ?", (source["id"],))

        connection.execute(
            "UPDATE entities SET aliases_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(sorted(aliases), ensure_ascii=False), datetime.now(timezone.utc).replace(microsecond=0).isoformat(), target_id),
        )

    return {"merged": len(sources), "target_id": target_id, "aliases": sorted(aliases)}


def upsert_entity_mentions(
    project_id: int,
    mentions: list[dict[str, Any]],
) -> dict[str, int]:
    """Salva menzioni entità, creando le entità mancanti e deduplicando.

    Ogni mention deve contenere: content_id, name, mention_text.
    Opzionali: type, context, confidence, source.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    created = 0
    stored = 0
    with connect() as connection:
        for mention in mentions:
            name = mention["name"].strip()
            if not name:
                continue
            canonical = name.lower()
            existing = connection.execute(
                """SELECT id FROM entities
                   WHERE project_id = ? AND (LOWER(name) = ? OR LOWER(aliases_json) LIKE ?)""",
                (project_id, canonical, f"%{canonical}%"),
            ).fetchone()
            if existing:
                entity_id = existing["id"]
            else:
                cursor = connection.execute(
                    """INSERT INTO entities (
                        project_id, name, type, sector, aliases_json, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id, name, mention.get("type", "brand"), "",
                        json.dumps([], ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        now, now,
                    ),
                )
                entity_id = int(cursor.lastrowid)
                created += 1

            cursor = connection.execute(
                """INSERT OR IGNORE INTO content_entity_mentions (
                    project_id, content_id, entity_id, mention_text, context, confidence, source, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id, mention["content_id"], entity_id,
                    mention.get("mention_text", name), mention.get("context", ""),
                    float(mention.get("confidence", 0.0)), mention.get("source", "rule"), now,
                ),
            )
            stored += cursor.rowcount
    return {"entities_created": created, "mentions_stored": stored}


def content_entity_mentions(
    project_id: int,
    entity_id: int | None = None,
    content_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["m.project_id = ?"]
    parameters: list[Any] = [project_id]
    if entity_id is not None:
        clauses.append("m.entity_id = ?")
        parameters.append(entity_id)
    if content_id is not None:
        clauses.append("m.content_id = ?")
        parameters.append(content_id)
    parameters.append(limit)
    query = f"""SELECT m.*, e.name AS entity_name, e.type AS entity_type, c.title AS content_title,
                       c.channel_title, c.published_at, c.views
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id
                JOIN social_contents c ON c.id = m.content_id
                WHERE {' AND '.join(clauses)}
                ORDER BY c.published_at DESC
                LIMIT ?"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def upsert_content_ad_signal(
    project_id: int,
    content_id: int,
    platform: str,
    external_id: str,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Salva o aggiorna il segnale AD per un contenuto."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        existing = connection.execute(
            "SELECT id FROM content_ad_signals WHERE project_id = ? AND content_id = ?",
            (project_id, content_id),
        ).fetchone()
        if existing:
            connection.execute(
                """UPDATE content_ad_signals SET
                    platform = ?, external_id = ?, ad_type = ?, confidence = ?,
                    disclosure_quality = ?, is_commercial = ?, is_disclosed = ?,
                    brand_name = ?, evidence_json = ?, affiliate_signals_json = ?,
                    sponsorship_signals_json = ?, risks_json = ?, updated_at = ?
                   WHERE project_id = ? AND content_id = ?""",
                (
                    platform,
                    external_id,
                    assessment["ad_type"],
                    assessment["confidence"],
                    assessment["disclosure_quality"],
                    1 if assessment["is_commercial"] else 0,
                    1 if assessment["is_disclosed"] else 0,
                    assessment.get("brand_name", ""),
                    json.dumps(assessment.get("evidence", []), ensure_ascii=False),
                    json.dumps(assessment.get("affiliate_signals", []), ensure_ascii=False),
                    json.dumps(assessment.get("sponsorship_signals", []), ensure_ascii=False),
                    json.dumps(assessment.get("risks", []), ensure_ascii=False),
                    now,
                    project_id,
                    content_id,
                ),
            )
        else:
            connection.execute(
                """INSERT INTO content_ad_signals (
                    project_id, content_id, platform, external_id, ad_type, confidence,
                    disclosure_quality, is_commercial, is_disclosed, brand_name,
                    evidence_json, affiliate_signals_json, sponsorship_signals_json,
                    risks_json, detected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    content_id,
                    platform,
                    external_id,
                    assessment["ad_type"],
                    assessment["confidence"],
                    assessment["disclosure_quality"],
                    1 if assessment["is_commercial"] else 0,
                    1 if assessment["is_disclosed"] else 0,
                    assessment.get("brand_name", ""),
                    json.dumps(assessment.get("evidence", []), ensure_ascii=False),
                    json.dumps(assessment.get("affiliate_signals", []), ensure_ascii=False),
                    json.dumps(assessment.get("sponsorship_signals", []), ensure_ascii=False),
                    json.dumps(assessment.get("risks", []), ensure_ascii=False),
                    now,
                    now,
                ),
            )
    return {"project_id": project_id, "content_id": content_id, "updated": True}


def get_content_ad_signal(
    project_id: int,
    content_id: int,
) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """SELECT s.*, c.title AS content_title, c.channel_title
               FROM content_ad_signals s
               JOIN social_contents c ON c.id = s.content_id
               WHERE s.project_id = ? AND s.content_id = ?""",
            (project_id, content_id),
        ).fetchone()
        if row is None:
            return None
        return _ad_signal_from_row(dict(row))


def list_ad_signals(
    project_id: int,
    ad_type: str | None = None,
    brand_name: str | None = None,
    disclosure_quality: str | None = None,
    min_confidence: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = ["s.project_id = ?"]
    parameters: list[Any] = [project_id]
    if ad_type:
        clauses.append("s.ad_type = ?")
        parameters.append(ad_type)
    if brand_name:
        clauses.append("LOWER(s.brand_name) = LOWER(?)")
        parameters.append(brand_name)
    if disclosure_quality:
        clauses.append("s.disclosure_quality = ?")
        parameters.append(disclosure_quality)
    if min_confidence is not None:
        clauses.append("s.confidence >= ?")
        parameters.append(min_confidence)
    parameters.extend([limit, offset])
    query = f"""SELECT s.*, c.title AS content_title, c.channel_title, c.published_at, c.views
                 FROM content_ad_signals s
                 JOIN social_contents c ON c.id = s.content_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY s.confidence DESC, c.published_at DESC
                 LIMIT ? OFFSET ?"""
    with connect() as connection:
        return [_ad_signal_from_row(dict(row)) for row in connection.execute(query, parameters)]


def ad_report_summary(
    project_id: int,
    days: int = 90,
    niche: str | None = None,
) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    clauses = ["s.project_id = ?", "c.published_at >= ?"]
    parameters: list[Any] = [project_id, since]
    if niche:
        clauses.append("pc.niche = ?")
        parameters.append(niche)

    with connect() as connection:
        total = connection.execute(
            f"""SELECT COUNT(*) AS n
                FROM content_ad_signals s
                JOIN social_contents c ON c.id = s.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = s.project_id
                WHERE {' AND '.join(clauses)}""",
            parameters,
        ).fetchone()["n"]

        by_type = connection.execute(
            f"""SELECT s.ad_type, COUNT(*) AS n
                FROM content_ad_signals s
                JOIN social_contents c ON c.id = s.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = s.project_id
                WHERE {' AND '.join(clauses)}
                GROUP BY s.ad_type""",
            parameters,
        ).fetchall()

        by_brand = connection.execute(
            f"""SELECT s.brand_name, s.ad_type, COUNT(*) AS n, COUNT(DISTINCT c.channel_id) AS channels
                FROM content_ad_signals s
                JOIN social_contents c ON c.id = s.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = s.project_id
                WHERE {' AND '.join(clauses)} AND s.brand_name != ''
                GROUP BY s.brand_name, s.ad_type
                ORDER BY n DESC
                LIMIT 50""",
            parameters,
        ).fetchall()

        disclosure = connection.execute(
            f"""SELECT s.disclosure_quality, COUNT(*) AS n
                FROM content_ad_signals s
                JOIN social_contents c ON c.id = s.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = s.project_id
                WHERE {' AND '.join(clauses)}
                GROUP BY s.disclosure_quality""",
            parameters,
        ).fetchall()

    return {
        "period_days": days,
        "total_signals": total,
        "by_type": {row["ad_type"]: row["n"] for row in by_type},
        "top_brands": [
            {
                "brand_name": row["brand_name"],
                "ad_type": row["ad_type"],
                "contents": row["n"],
                "channels": row["channels"],
            }
            for row in by_brand
        ],
        "disclosure_quality": {row["disclosure_quality"]: row["n"] for row in disclosure},
    }


def _ad_signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "content_id": row["content_id"],
        "platform": row["platform"],
        "external_id": row["external_id"],
        "ad_type": row["ad_type"],
        "confidence": row["confidence"],
        "disclosure_quality": row["disclosure_quality"],
        "is_commercial": bool(row["is_commercial"]),
        "is_disclosed": bool(row["is_disclosed"]),
        "brand_name": row["brand_name"],
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "affiliate_signals": json.loads(row["affiliate_signals_json"] or "[]"),
        "sponsorship_signals": json.loads(row["sponsorship_signals_json"] or "[]"),
        "risks": json.loads(row["risks_json"] or "[]"),
        "detected_at": row["detected_at"],
        "updated_at": row["updated_at"],
        "content_title": row.get("content_title", ""),
        "channel_title": row.get("channel_title", ""),
        "published_at": row.get("published_at", ""),
        "views": row.get("views", 0),
    }


def run_ad_detection_for_project(
    project_id: int,
    content_ids: list[int] | None = None,
) -> dict[str, int]:
    """Esegue AD detection sui contenuti di un progetto e salva i risultati."""
    from app.ad_detector import detect_ad_for_content

    processed = 0
    stored = 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        if content_ids:
            placeholders = ",".join("?" * len(content_ids))
            rows = connection.execute(
                f"""SELECT c.* FROM social_contents c
                    JOIN project_contents pc ON pc.content_id = c.id
                    WHERE pc.project_id = ? AND c.id IN ({placeholders})""",
                (project_id, *content_ids),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT c.* FROM social_contents c
                    JOIN project_contents pc ON pc.content_id = c.id
                    WHERE pc.project_id = ?""",
                (project_id,),
            ).fetchall()

        for row in rows:
            processed += 1
            content = dict(row)
            assessment = detect_ad_for_content(content, project_id, connection)
            existing = connection.execute(
                "SELECT id FROM content_ad_signals WHERE project_id = ? AND content_id = ?",
                (project_id, content["id"]),
            ).fetchone()
            params = (
                project_id,
                content["id"],
                content.get("platform", "YouTube"),
                content["external_id"],
                assessment["ad_type"],
                assessment["confidence"],
                assessment["disclosure_quality"],
                1 if assessment["is_commercial"] else 0,
                1 if assessment["is_disclosed"] else 0,
                assessment.get("brand_name", ""),
                json.dumps(assessment.get("evidence", []), ensure_ascii=False),
                json.dumps(assessment.get("affiliate_signals", []), ensure_ascii=False),
                json.dumps(assessment.get("sponsorship_signals", []), ensure_ascii=False),
                json.dumps(assessment.get("risks", []), ensure_ascii=False),
                now,
                now,
            )
            if existing:
                connection.execute(
                    """UPDATE content_ad_signals SET
                        platform = ?, external_id = ?, ad_type = ?, confidence = ?,
                        disclosure_quality = ?, is_commercial = ?, is_disclosed = ?,
                        brand_name = ?, evidence_json = ?, affiliate_signals_json = ?,
                        sponsorship_signals_json = ?, risks_json = ?, updated_at = ?
                       WHERE project_id = ? AND content_id = ?""",
                    (*params[2:], now, project_id, content["id"]),
                )
            else:
                connection.execute(
                    """INSERT INTO content_ad_signals (
                        project_id, content_id, platform, external_id, ad_type, confidence,
                        disclosure_quality, is_commercial, is_disclosed, brand_name,
                        evidence_json, affiliate_signals_json, sponsorship_signals_json,
                        risks_json, detected_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    params,
                )
            stored += 1

    return {"processed": processed, "stored": stored}


def entity_mentions_summary(
    project_id: int,
    days: int = 90,
    entity_id: int | None = None,
) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    clauses = ["m.project_id = ?", "c.published_at >= ?"]
    parameters: list[Any] = [project_id, since]
    if entity_id is not None:
        clauses.append("m.entity_id = ?")
        parameters.append(entity_id)
    query = f"""SELECT e.id, e.name, e.type, COUNT(m.id) AS mentions,
                       COUNT(DISTINCT m.content_id) AS contents,
                       COUNT(DISTINCT c.channel_title) AS channels,
                       COUNT(DISTINCT pc.niche) AS niches,
                       SUM(c.views) AS total_views
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id
                JOIN social_contents c ON c.id = m.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = m.project_id
                WHERE {' AND '.join(clauses)}
                GROUP BY e.id, e.name, e.type
                ORDER BY mentions DESC"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def sponsored_channels_by_entity(
    project_id: int,
    entity_id: int,
    *,
    since: str | None = None,
    niche: str | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Canali attribuiti a uno sponsor, raggruppati per piattaforma e ID."""
    clauses = [
        "m.project_id = ?", "m.entity_id = ?",
        "e.project_id = m.project_id", "e.type IN ('brand', 'organization')",
    ]
    parameters: list[Any] = [project_id, entity_id]
    if since:
        clauses.append("c.published_at >= ?")
        parameters.append(since)
    if niche:
        clauses.append("pc.niche = ?")
        parameters.append(niche)
    if platform:
        clauses.append("c.platform = ?")
        parameters.append(platform)
    query = f"""SELECT c.platform, c.channel_id, MAX(c.channel_title) AS channel_title,
                       COUNT(DISTINCT c.id) AS sponsored_contents,
                       MIN(c.published_at) AS first_sponsored_at,
                       MAX(c.published_at) AS last_sponsored_at,
                       SUM(c.views) AS sponsored_views,
                       SUM(c.likes) AS sponsored_likes,
                       SUM(c.comments) AS sponsored_comments,
                       AVG(m.confidence) AS average_confidence,
                       MAX(c.has_paid_product_placement) AS has_declared_placement
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id
                JOIN social_contents c ON c.id = m.content_id
                JOIN project_contents pc
                  ON pc.content_id = c.id AND pc.project_id = m.project_id
                WHERE {' AND '.join(clauses)}
                GROUP BY c.platform, c.channel_id
                ORDER BY sponsored_contents DESC, sponsored_views DESC"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def sponsor_basin_contents(
    project_id: int,
    entity_id: int,
    *,
    since: str | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Tutto il corpus osservato dei canali sponsorizzati dall'entità."""
    clauses = ["m.project_id = ?", "m.entity_id = ?"]
    parameters: list[Any] = [project_id, entity_id]
    if since:
        clauses.append("sponsored.published_at >= ?")
        parameters.append(since)
    if platform:
        clauses.append("sponsored.platform = ?")
        parameters.append(platform)
    query = f"""SELECT DISTINCT observed.id, observed.external_id, observed.platform,
                       observed.title, observed.description, observed.tags_json,
                       observed.channel_id, observed.channel_title, observed.published_at,
                       observed.duration_seconds, observed.views, observed.likes,
                       observed.comments, observed.has_paid_product_placement,
                       observed.acquired_at, opc.niche, opc.topic, opc.source_query
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id AND e.project_id = m.project_id
                JOIN social_contents sponsored ON sponsored.id = m.content_id
                JOIN social_contents observed
                  ON observed.platform = sponsored.platform
                 AND observed.channel_id = sponsored.channel_id
                JOIN project_contents opc
                  ON opc.content_id = observed.id AND opc.project_id = m.project_id
                WHERE {' AND '.join(clauses)}
                  AND e.type IN ('brand', 'organization')
                ORDER BY observed.published_at DESC"""
    with connect() as connection:
        rows = [dict(row) for row in connection.execute(query, parameters)]
    for row in rows:
        row["tags"] = json.loads(row.pop("tags_json") or "[]")
    return rows


def brands_by_niche(
    project_id: int,
    niche: str,
    *,
    since: str | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    clauses = [
        "m.project_id = ?", "pc.niche = ?",
        "e.type IN ('brand', 'organization')",
    ]
    parameters: list[Any] = [project_id, niche]
    if since:
        clauses.append("c.published_at >= ?")
        parameters.append(since)
    if platform:
        clauses.append("c.platform = ?")
        parameters.append(platform)
    query = f"""SELECT e.id AS entity_id, e.name, e.sector,
                       COUNT(DISTINCT m.content_id) AS sponsored_contents,
                       COUNT(DISTINCT c.platform || ':' || c.channel_id) AS channels,
                       SUM(c.views) AS total_views,
                       MIN(c.published_at) AS first_seen_at,
                       MAX(c.published_at) AS last_seen_at
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id AND e.project_id = m.project_id
                JOIN social_contents c ON c.id = m.content_id
                JOIN project_contents pc
                  ON pc.content_id = c.id AND pc.project_id = m.project_id
                WHERE {' AND '.join(clauses)}
                GROUP BY e.id, e.name, e.sector
                ORDER BY sponsored_contents DESC, total_views DESC"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def delete_all_entity_mentions(project_id: int) -> int:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM content_entity_mentions WHERE project_id = ?", (project_id,))
        return cursor.rowcount


def adv_entity_data(
    project_id: int,
    days: int = 90,
    niche: str | None = None,
) -> list[dict[str, Any]]:
    """Restituisce tutte le menzioni entità con i metadati dei contenuti associati.

    Usato da Adv Intelligence per costruire il report da entità persistenti.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    clauses = ["m.project_id = ?", "c.published_at >= ?"]
    parameters: list[Any] = [project_id, since]
    if niche:
        clauses.append("pc.niche = ?")
        parameters.append(niche)
    query = f"""SELECT m.id, m.entity_id, e.name AS entity_name, e.type AS entity_type,
                       m.mention_text, m.context, m.confidence, m.source, m.extracted_at,
                       c.id AS content_id, c.external_id, c.title, c.channel_title,
                       c.published_at, c.views, c.likes, c.comments,
                       pc.niche
                FROM content_entity_mentions m
                JOIN entities e ON e.id = m.entity_id
                JOIN social_contents c ON c.id = m.content_id
                JOIN project_contents pc ON pc.content_id = c.id AND pc.project_id = m.project_id
                WHERE {' AND '.join(clauses)}
                ORDER BY c.published_at DESC"""
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def upsert_transcript(project_id: int, entry: dict[str, Any]) -> None:
    """Salva il risultato di un'indagine trascrizione (anche errori/no captions)."""
    extracted_at = entry.get("extracted_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        connection.execute(
            """INSERT INTO content_transcripts (
                project_id, external_id, platform, language, kind, status, error,
                text, segments_json, analysis_json, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, platform, external_id) DO UPDATE SET
                language=excluded.language, kind=excluded.kind, status=excluded.status,
                error=excluded.error, text=excluded.text,
                segments_json=excluded.segments_json, analysis_json=excluded.analysis_json,
                extracted_at=excluded.extracted_at""",
            (
                project_id, entry["external_id"], entry.get("platform", "YouTube"),
                entry.get("language", ""), entry.get("kind", ""),
                entry.get("status", "ok"), entry.get("error", ""),
                entry.get("text", ""),
                json.dumps(entry.get("segments", []), ensure_ascii=False),
                json.dumps(entry.get("analysis", {}), ensure_ascii=False),
                extracted_at,
            ),
        )


def _transcript_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "external_id": row["external_id"],
        "platform": row["platform"],
        "language": row["language"],
        "kind": row["kind"],
        "status": row["status"],
        "error": row["error"],
        "text": row["text"],
        "segments": json.loads(row["segments_json"] or "[]"),
        "analysis": json.loads(row["analysis_json"] or "{}"),
        "extracted_at": row["extracted_at"],
        "title": row["title"] if "title" in row.keys() else "",
        "channel": row["channel_title"] if "channel_title" in row.keys() else "",
    }


def list_transcripts(project_id: int, only_ad_reads: bool = False) -> list[dict[str, Any]]:
    query = """SELECT t.*, c.title, c.channel_title
               FROM content_transcripts t
               LEFT JOIN social_contents c
                   ON c.platform = t.platform AND c.external_id = t.external_id
               WHERE t.project_id = ?
               ORDER BY t.extracted_at DESC"""
    with connect() as connection:
        items = [_transcript_from_row(row) for row in connection.execute(query, (project_id,))]
    if only_ad_reads:
        items = [item for item in items if item["analysis"].get("ad_read_detected")]
    return items


def transcribed_external_ids(project_id: int) -> set[str]:
    """Video già investigati con successo: non vanno riaddebitati né rianalizzati."""
    with connect() as connection:
        rows = connection.execute(
            "SELECT external_id FROM content_transcripts WHERE project_id = ? AND status = 'ok'",
            (project_id,),
        )
        return {row[0] for row in rows}


def get_transcription_credits(project_id: int) -> int:
    with connect() as connection:
        row = connection.execute(
            "SELECT transcription_credits FROM research_projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return int(row[0]) if row else 0


def decrement_transcription_credits(project_id: int, amount: int = 1) -> bool:
    """Scala crediti in modo atomico. False se il saldo non è sufficiente."""
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE research_projects
               SET transcription_credits = transcription_credits - ?
               WHERE id = ? AND transcription_credits >= ?""",
            (amount, project_id, amount),
        )
        return bool(cursor.rowcount)


def add_transcription_credits(project_id: int, amount: int) -> int:
    """Ricarica i crediti del progetto (es. dopo un pagamento). Ritorna il saldo."""
    with connect() as connection:
        connection.execute(
            """UPDATE research_projects
               SET transcription_credits = transcription_credits + ?
               WHERE id = ?""",
            (amount, project_id),
        )
        row = connection.execute(
            "SELECT transcription_credits FROM research_projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return int(row[0]) if row else 0


# --- Quota API stimata -------------------------------------------------

def record_api_usage(operation: str, units: int, day: str | None = None) -> None:
    """Registra unità di quota stimate per un'operazione API.

    Il contatore è giornaliero e per tipo di chiamata: serve a rendere
    visibile il consumo stimato prima che la quota reale si esaurisca.
    """
    if units <= 0:
        return
    day = day or datetime.now(timezone.utc).date().isoformat()
    with connect() as connection:
        connection.execute(
            """INSERT INTO api_usage (day, operation, units) VALUES (?, ?, ?)
               ON CONFLICT(day, operation) DO UPDATE SET
                   units = units + excluded.units""",
            (day, operation, units),
        )


def api_usage_summary(days: int = 1) -> dict[str, Any]:
    """Riepilogo del consumo stimato: totale di oggi e serie recente."""
    today = datetime.now(timezone.utc).date().isoformat()
    since = (datetime.now(timezone.utc) - timedelta(days=max(days - 1, 0))).date().isoformat()
    with connect() as connection:
        today_rows = connection.execute(
            "SELECT operation, units FROM api_usage WHERE day = ? ORDER BY units DESC",
            (today,),
        ).fetchall()
        daily_rows = connection.execute(
            """SELECT day, SUM(units) AS units FROM api_usage
               WHERE day >= ? GROUP BY day ORDER BY day""",
            (since,),
        ).fetchall()
    by_operation = {row["operation"]: int(row["units"]) for row in today_rows}
    return {
        "day": today,
        "used_today": sum(by_operation.values()),
        "by_operation": by_operation,
        "daily": [{"day": row["day"], "units": int(row["units"])} for row in daily_rows],
    }


# --- Account: password e sessioni ---------------------------------------

def user_by_id(user_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, email, password_hash, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def update_user_password(user_id: int, password_hash: str) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )


def list_user_sessions(user_id: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with connect() as connection:
        rows = connection.execute(
            """SELECT token_hash, created_at, expires_at FROM user_sessions
               WHERE user_id = ? AND expires_at > ?
               ORDER BY created_at DESC""",
            (user_id, now),
        ).fetchall()
        return [dict(row) for row in rows]


def delete_user_sessions_except(user_id: int, keep_token_hash: str | None = None) -> int:
    """Revoca le sessioni dell'utente, opzionalmente mantenendo quella corrente."""
    with connect() as connection:
        if keep_token_hash:
            cursor = connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ? AND token_hash != ?",
                (user_id, keep_token_hash),
            )
        else:
            cursor = connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ?", (user_id,)
            )
        return int(cursor.rowcount)
