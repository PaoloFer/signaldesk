"""Test anti-deriva dello schema (D2).

Esegue ``alembic upgrade head`` su un database SQLite temporaneo (processo
separato, così ``DATABASE_URL`` viene letta dall'ambiente come in produzione)
e confronta tabelle, colonne e indici con ``Base.metadata``: lo schema
versionato deve coincidere con quello atteso dai modelli.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.models import Base


ROOT = Path(__file__).resolve().parent.parent


def _upgrade(database_path: Path, *targets: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", *targets],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def _schema(connection: sqlite3.Connection) -> dict[str, dict[str, set[str]]]:
    tables: dict[str, dict[str, set[str]]] = {}
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (table,) in rows:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        indexes = {
            row[1]
            for row in connection.execute(f"PRAGMA index_list({table})")
            if row[1] and not row[1].startswith("sqlite_autoindex")
        }
        tables[table] = {"columns": columns, "indexes": indexes}
    return tables


class MigrationSchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "migrated.db"

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_upgrade_head_matches_models(self):
        result = _upgrade(self.database_path)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        connection = sqlite3.connect(self.database_path)
        try:
            migrated = _schema(connection)
        finally:
            connection.close()
        expected_tables = set(Base.metadata.tables) | {"alembic_version"}
        self.assertEqual(set(migrated), expected_tables)
        for table_name, table in Base.metadata.tables.items():
            expected_columns = {column.name for column in table.columns}
            self.assertEqual(
                migrated[table_name]["columns"], expected_columns,
                msg=f"Colonne diverse per {table_name}",
            )
            expected_indexes = {index.name for index in table.indexes}
            self.assertEqual(
                migrated[table_name]["indexes"], expected_indexes,
                msg=f"Indici diversi per {table_name}",
            )

    def test_downgrade_removes_latest_revisions(self):
        result = _upgrade(self.database_path)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        env = dict(os.environ)
        env["DATABASE_URL"] = f"sqlite:///{self.database_path.as_posix()}"
        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "-2"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(downgrade.returncode, 0, msg=downgrade.stderr)
        connection = sqlite3.connect(self.database_path)
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        # 0010 (panorama) e 0009 (indici) rimosse; 0008 (api_usage) resta.
        self.assertNotIn("channel_profiles", names)
        self.assertNotIn("niche_channels", names)
        self.assertIn("api_usage", names)


if __name__ == "__main__":
    unittest.main()
