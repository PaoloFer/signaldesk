import tempfile
import unittest
from pathlib import Path

from app import database
from app.entity_extraction import extract_entities_from_contents


class EntityTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "entities.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_create_and_retrieve_entity(self):
        entity = database.create_entity(1, "Nike", type="brand", sector="Sportswear")
        self.assertEqual(entity["name"], "Nike")
        self.assertEqual(entity["type"], "brand")
        found = database.get_entity(entity["id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Nike")

    def test_list_entities_with_search(self):
        database.create_entity(1, "Nike")
        database.create_entity(1, "Adidas")
        database.create_entity(1, "Puma")
        all_items = database.list_entities(1)
        self.assertEqual(len(all_items), 3)
        filtered = database.list_entities(1, search="nik")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Nike")

    def test_update_entity(self):
        entity = database.create_entity(1, "Nike")
        updated = database.update_entity(entity["id"], sector="Sportswear", aliases=["Nike Inc"])
        self.assertEqual(updated["sector"], "Sportswear")
        self.assertIn("Nike Inc", updated["aliases"])

    def test_delete_entity_removes_mentions(self):
        entity = database.create_entity(1, "Nike")
        database.upsert_entity_mentions(1, [
            {"content_id": 1, "name": "Nike", "mention_text": "Nike", "confidence": 0.9, "source": "rule"},
        ])
        self.assertTrue(database.delete_entity(entity["id"]))
        self.assertIsNone(database.get_entity(entity["id"]))
        self.assertEqual(len(database.content_entity_mentions(1)), 0)

    def test_upsert_entity_mentions_deduplicates(self):
        result = database.upsert_entity_mentions(1, [
            {"content_id": 1, "name": "Nike", "mention_text": "Nike", "confidence": 0.9, "source": "rule"},
            {"content_id": 1, "name": "nike", "mention_text": "nike", "confidence": 0.8, "source": "rule"},
        ])
        self.assertEqual(result["entities_created"], 1)
        self.assertEqual(result["mentions_stored"], 1)
        summary = database.entity_mentions_summary(1)
        self.assertEqual(len(summary), 1)

    def test_merge_entities(self):
        nike = database.create_entity(1, "Nike", aliases=["Nike Inc"])
        nike_running = database.create_entity(1, "Nike Running")
        database.upsert_entity_mentions(1, [
            {"content_id": 1, "name": "Nike", "mention_text": "Nike", "confidence": 0.9},
            {"content_id": 2, "name": "Nike Running", "mention_text": "Nike Running", "confidence": 0.8},
        ])
        result = database.merge_entities(1, nike["id"], [nike_running["id"]])
        self.assertEqual(result["merged"], 1)
        self.assertIn("Nike Running", result["aliases"])
        target = database.get_entity(nike["id"])
        self.assertEqual(target["mentions"], 2)
        self.assertIsNone(database.get_entity(nike_running["id"]))

    def test_extract_entities_from_contents_creates_mentions(self):
        contents = [
            {
                "id": 1, "title": "Recensione Nike", "description": "sponsorizzato da Nike",
                "tags_json": "[]", "published_at": "2024-01-01T00:00:00+00:00",
                "views": 1000, "likes": 50, "comments": 10,
            }
        ]
        mentions = extract_entities_from_contents(contents, 1)
        self.assertTrue(any(m["name"] == "Nike" for m in mentions))

    def test_entity_extraction_job_processes_project_contents(self):
        from app.jobs import process_next_job
        contents = [
            {
                "external_id": "vid-test-1", "platform": "YouTube",
                "title": "Recensione Nike", "description": "sponsorizzato da Nike",
                "tags": [], "published_at": "2026-09-17T00:00:00+00:00",
                "duration_seconds": 600, "views": 1000, "likes": 50, "comments": 10,
                "niche": "Corsa", "topic": "Recensione", "source_query": "test",
                "acquired_at": "2026-09-17T00:00:00+00:00",
            }
        ]
        database.upsert_contents(contents, 1)
        job = database.enqueue_background_job(1, "entity_extraction", {"full_refresh": True})
        processed = process_next_job()
        self.assertTrue(processed)
        finished = database.background_job(job["id"])
        self.assertEqual(finished["status"], "completed")
        summary = database.entity_mentions_summary(1)
        self.assertTrue(any(item["name"] == "Nike" for item in summary))


if __name__ == "__main__":
    unittest.main()
