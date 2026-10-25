"""Test per C1/C2 (quota stimata), B1 (push-down SQL), B2 (cancellazione
contenuti), E4 (edit fonte) e F3 (job stallati)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from app import database
from app import main


class ApiUsageTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "quota.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_usage_is_accumulated_per_day_and_operation(self):
        database.record_api_usage("search.list", 100)
        database.record_api_usage("search.list", 100)
        database.record_api_usage("videos.list", 1)
        summary = database.api_usage_summary(days=7)
        self.assertEqual(summary["used_today"], 201)
        self.assertEqual(summary["by_operation"]["search.list"], 200)
        self.assertEqual(summary["by_operation"]["videos.list"], 1)
        self.assertEqual(len(summary["daily"]), 1)

    def test_zero_or_negative_units_are_ignored(self):
        database.record_api_usage("videos.list", 0)
        database.record_api_usage("videos.list", -5)
        self.assertEqual(database.api_usage_summary()["used_today"], 0)

    def test_quota_guard_blocks_when_budget_exceeded(self):
        database.record_api_usage("search.list", 10000)
        with self.assertRaises(HTTPException) as caught:
            main.ensure_quota_available(1)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("Quota stimata insufficiente", caught.exception.detail)

    def test_quota_guard_allows_within_budget(self):
        database.record_api_usage("videos.list", 50)
        main.ensure_quota_available(101)

    def test_quota_error_detection(self):
        from app.youtube import YouTubeAPIError

        self.assertTrue(main.is_quota_error(YouTubeAPIError("The request ... exceeded your quota")))
        self.assertTrue(main.is_quota_error(YouTubeAPIError("quotaExceeded")))
        self.assertFalse(main.is_quota_error(YouTubeAPIError("video non trovato")))


class ReportPushDownTest(unittest.TestCase):
    """B1: il filtro temporale arriva in SQL, la shape dei dati non cambia."""

    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "pushdown.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_all_comments_since_filters_old_rows(self):
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=60)).replace(microsecond=0).isoformat()
        database.insert_comments([
            {"external_id": "c-old", "content_id": "v1", "author_hash": "a1",
             "text": "vecchio", "published_at": old},
            {"external_id": "c-new", "content_id": "v1", "author_hash": "a2",
             "text": "nuovo", "published_at": recent},
        ], project_id=1)
        since = (datetime.now(timezone.utc) - timedelta(days=7)).replace(microsecond=0).isoformat()
        rows = database.all_comments(1, since=since)
        texts = {row["text"] for row in rows}
        self.assertIn("nuovo", texts)
        self.assertNotIn("vecchio", texts)
        # Senza filtro entrambi restano visibili.
        all_texts = {row["text"] for row in database.all_comments(1)}
        self.assertIn("vecchio", all_texts)

    def test_project_snapshots_limited_to_external_ids(self):
        # demo-video-0-3 è pubblicato 6 giorni fa: ha snapshot seedati.
        rows = database.project_snapshots(external_ids=["demo-video-0-3"])
        self.assertTrue(rows)
        self.assertEqual({row["external_id"] for row in rows}, {"demo-video-0-3"})
        self.assertEqual(database.project_snapshots(external_ids=[]), [])


class DeleteProjectContentsTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "delete_contents.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_delete_by_niche_detaches_and_removes_orphans(self):
        total_before = len(database.all_contents(1))
        niche = database.all_contents(1)[0]["niche"]
        expected = len([c for c in database.all_contents(1) if c["niche"] == niche])
        result = database.delete_project_contents(1, niche=niche)
        self.assertEqual(result["detached"], expected)
        remaining = database.all_contents(1)
        self.assertEqual(len(remaining), total_before - expected)
        self.assertEqual({c["niche"] for c in remaining} | {niche}, {c["niche"] for c in remaining} | {niche})
        self.assertNotIn(niche, {c["niche"] for c in remaining})

    def test_contents_shared_with_other_project_survive(self):
        project = database.create_project("Secondo osservatorio")
        content = database.all_contents(1)[0]
        database.upsert_contents([content], project["id"])
        niche = content["niche"]
        result = database.delete_project_contents(1, niche=niche)
        self.assertGreater(result["detached"], 0)
        # Il contenuto condiviso non diventa orfano: resta nel secondo progetto.
        self.assertEqual(len(database.all_contents(project["id"])), 1)


class StalledJobsTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "stalled.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_running_jobs_older_than_timeout_are_failed(self):
        job = database.enqueue_background_job(1, "comment_analysis", {"limit": 10})
        claimed = database.claim_background_job()
        self.assertEqual(claimed["id"], job["id"])
        stale = (datetime.now(timezone.utc) - timedelta(hours=8)).replace(microsecond=0).isoformat()
        with database.connect() as connection:
            connection.execute(
                "UPDATE background_jobs SET started_at = ? WHERE id = ?", (stale, job["id"])
            )
        self.assertEqual(database.reap_stalled_jobs(timeout_hours=6), 1)
        updated = database.background_job(job["id"])
        self.assertEqual(updated["status"], "failed")
        self.assertIn("interrotto", updated["error"])

    def test_recent_running_jobs_are_untouched(self):
        database.enqueue_background_job(1, "comment_analysis", {"limit": 10})
        database.claim_background_job()
        self.assertEqual(database.reap_stalled_jobs(timeout_hours=6), 0)


class CsvImportIdempotencyTest(unittest.TestCase):
    """F4: reimportare lo stesso file non duplica nulla."""

    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "csv_idem.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_reimporting_same_rows_inserts_nothing(self):
        rows = [
            {"external_id": "csv-c1", "content_id": "csv-v1", "author_hash": "auth-1",
             "text": "primo", "published_at": "2026-09-10T10:00:00+00:00"},
            {"external_id": "csv-c2", "content_id": "csv-v1", "author_hash": "auth-2",
             "text": "secondo", "published_at": "2026-09-10T11:00:00+00:00"},
        ]
        self.assertEqual(database.insert_comments(rows, project_id=1), 2)
        self.assertEqual(database.insert_comments(rows, project_id=1), 0)
        texts = [c["text"] for c in database.all_comments(1) if c["content_id"] == "csv-v1"]
        self.assertEqual(sorted(texts), ["primo", "secondo"])


class SourceUpdateNameTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "source_edit.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_update_name(self):
        source = database.upsert_project_source(1, "youtube_search", "Query: corsa", {"query": "corsa"})
        updated = database.update_project_source(source["id"], name="Fonte rinominata")
        self.assertEqual(updated["name"], "Fonte rinominata")
        self.assertEqual(database.project_source(source["id"])["name"], "Fonte rinominata")


if __name__ == "__main__":
    unittest.main()
