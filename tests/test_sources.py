import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database
from app.worker import enqueue_due_sources


class ProjectSourcesTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "sources.db"
        database.initialize()
        self.config = {"query": "corsa lenta", "niche": "Running", "days": 30}

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_upsert_deduplicates_and_reactivates_source(self):
        first = database.upsert_project_source(1, "youtube_search", "Query: corsa", self.config)
        paused = database.update_project_source(first["id"], status="paused")
        self.assertEqual(paused["status"], "paused")
        second = database.upsert_project_source(1, "youtube_search", "Query: corsa", self.config)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["status"], "active")
        self.assertEqual(len(database.project_sources(1)), 1)

    def test_due_sources_only_returns_active_expired_sources(self):
        source = database.upsert_project_source(1, "youtube_search", "Query: corsa", self.config)
        database.update_project_source(source["id"], status="paused")
        now = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.assertEqual(database.due_project_sources(now), [])
        database.update_project_source(source["id"], status="active", refresh_hours=1)
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        due = database.due_project_sources(future)
        self.assertEqual([item["id"] for item in due], [source["id"]])

    def test_enqueue_due_sources_creates_job_and_reschedules(self):
        source = database.upsert_project_source(
            1, "youtube_search", "Query: corsa", self.config, refresh_hours=1
        )
        before = datetime.now(timezone.utc).replace(microsecond=0)
        future = before + timedelta(hours=2)
        self.assertEqual(enqueue_due_sources(future), 1)
        jobs = database.background_jobs(1)
        self.assertEqual(len(jobs), 1)
        payload = jobs[0]["payload_json"]
        self.assertIn('"source_id"', payload)
        updated = database.project_source(source["id"])
        self.assertGreaterEqual(updated["next_run_at"], (before + timedelta(hours=1)).isoformat())

    def test_finish_source_run_records_error_and_next_run(self):
        source = database.upsert_project_source(1, "youtube_search", "Query: corsa", self.config)
        database.finish_source_run(source["id"], error="quota esaurita")
        updated = database.project_source(source["id"])
        self.assertEqual(updated["last_error"], "quota esaurita")
        self.assertIsNotNone(updated["last_run_at"])
        self.assertIsNotNone(updated["next_run_at"])

    def test_deleting_project_removes_sources(self):
        project = database.create_project("Con fonte")
        database.upsert_project_source(project["id"], "youtube_search", "Query: test", self.config)
        self.assertTrue(database.delete_project(project["id"]))
        self.assertEqual(database.project_sources(project["id"]), [])


if __name__ == "__main__":
    unittest.main()
