import tempfile
import unittest
from pathlib import Path

from app import database


class BackgroundJobsTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "jobs.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_deduplicates_active_jobs_and_tracks_completion(self):
        payload = {"query": "running", "niche": "Corsa"}
        first = database.enqueue_background_job(1, "youtube_discovery", payload)
        duplicate = database.enqueue_background_job(1, "youtube_discovery", payload)
        self.assertEqual(first["id"], duplicate["id"])
        claimed = database.claim_background_job()
        self.assertEqual(claimed["status"], "running")
        database.update_background_job(claimed["id"], 55)
        database.finish_background_job(claimed["id"], "completed", {"stored": 10})
        completed = database.background_job(claimed["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 100)

    def test_running_job_returns_to_queue_after_restart(self):
        job = database.enqueue_background_job(1, "youtube_discovery", {"query": "test"})
        database.claim_background_job()
        database.initialize()
        recovered = database.background_job(job["id"])
        self.assertEqual(recovered["status"], "queued")

    def test_queued_job_can_be_cancelled(self):
        job = database.enqueue_background_job(1, "youtube_discovery", {"query": "cancel"})
        self.assertTrue(database.cancel_background_job(job["id"]))
        self.assertEqual(database.background_job(job["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
