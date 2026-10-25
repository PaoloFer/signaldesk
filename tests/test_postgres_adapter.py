import unittest

from app.database import HybridRow, PostgresConnection
from app.settings import parse_bool


class Description:
    def __init__(self, name):
        self.name = name


class FakeCursor:
    def __init__(self):
        self.sql = ""
        self.parameters = ()
        self.description = None
        self.rowcount = 1
        self.rows = []

    def execute(self, sql, parameters=()):
        self.sql = sql
        self.parameters = parameters
        if "RETURNING id" in sql:
            self.description = [Description("id")]
            self.rows = [(42,)]

    def executemany(self, sql, parameters):
        self.sql = sql
        self.parameters = parameters

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


class FakeConnection:
    def __init__(self):
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor


class PostgresAdapterTest(unittest.TestCase):
    def test_translates_placeholders_conflict_and_returning(self):
        raw = FakeConnection()
        connection = PostgresConnection(raw)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO organizations (id, name) VALUES (?, ?)",
            (1, "Test"),
        )
        sql = raw.cursors[0].sql
        self.assertIn("VALUES (%s, %s)", sql)
        self.assertIn("ON CONFLICT DO NOTHING", sql)
        self.assertIn("RETURNING id", sql)
        self.assertEqual(cursor.lastrowid, 42)

    def test_escapes_literal_percent_for_psycopg(self):
        raw = FakeConnection()
        connection = PostgresConnection(raw)
        connection.execute(
            "SELECT external_id FROM social_contents WHERE external_id NOT LIKE 'demo-%' AND id = ?",
            (4,),
        )
        self.assertIn("NOT LIKE 'demo-%%'", raw.cursors[0].sql)
        self.assertIn("id = %s", raw.cursors[0].sql)

    def test_hybrid_row_supports_index_and_mapping_access(self):
        row = HybridRow(["id", "name"], (7, "SignalDesk"))
        self.assertEqual(row[0], 7)
        self.assertEqual(row["name"], "SignalDesk")
        self.assertEqual(dict(row), {"id": 7, "name": "SignalDesk"})

    def test_boolean_settings_are_strict(self):
        self.assertTrue(parse_bool("yes"))
        self.assertFalse(parse_bool("off"))
        with self.assertRaises(ValueError):
            parse_bool("maybe")


if __name__ == "__main__":
    unittest.main()
