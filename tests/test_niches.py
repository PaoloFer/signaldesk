import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import database
from app.auth import register
from app.main import NichePreviewRequest, preview_niche
from app.youtube import YouTubeAPIError


class NicheEntityTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "niches.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_create_and_retrieve_niche(self):
        niche = database.create_niche(
            project_id=1,
            name="Corsa amatoriale",
            description="Bacino dedicato alla corsa non professionale",
            status="active",
            seed_channels=[{"channel_id": "UCrun", "channel_title": "RunLab"}],
            seed_videos=[{"video_id": "abc123", "title": "Prima corsa"}],
            include_keywords=["allenamento", "principianti"],
            exclude_keywords=["maratona"],
            filters={"min_views": 1000},
        )
        self.assertEqual(niche["name"], "Corsa amatoriale")
        self.assertEqual(niche["status"], "active")
        self.assertEqual(len(niche["seed_channels"]), 1)
        self.assertEqual(niche["filters"]["min_views"], 1000)

        retrieved = database.get_niche(niche["id"])
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], niche["name"])

    def test_list_niche_entities_is_project_isolated(self):
        database.create_niche(project_id=1, name="Niche A")
        project = database.create_project("Altro progetto")
        database.create_niche(project_id=project["id"], name="Niche B")

        project_one = database.list_niche_entities(1)
        project_two = database.list_niche_entities(project["id"])
        self.assertEqual(len(project_one), 1)
        self.assertEqual(project_one[0]["name"], "Niche A")
        self.assertEqual(len(project_two), 1)
        self.assertEqual(project_two[0]["name"], "Niche B")

    def test_update_niche_partial(self):
        niche = database.create_niche(project_id=1, name="Da aggiornare")
        updated = database.update_niche(
            niche_id=niche["id"],
            description="Nuova descrizione",
            include_keywords=["keyword1"],
        )
        self.assertEqual(updated["description"], "Nuova descrizione")
        self.assertEqual(updated["include_keywords"], ["keyword1"])
        self.assertEqual(updated["name"], "Da aggiornare")

    def test_delete_niche(self):
        niche = database.create_niche(project_id=1, name="Da eliminare")
        self.assertTrue(database.delete_niche(niche["id"]))
        self.assertIsNone(database.get_niche(niche["id"]))
        self.assertFalse(database.delete_niche(niche["id"]))

    def test_unique_name_per_project(self):
        database.create_niche(project_id=1, name="Unica")
        with self.assertRaises(Exception):
            database.create_niche(project_id=1, name="Unica")

        project = database.create_project("Altro")
        # Stesso nome in progetto diverso deve essere consentito.
        database.create_niche(project_id=project["id"], name="Unica")


def _preview_content(external_id="vid1", channel_id="UCseed"):
    return {
        "external_id": external_id,
        "platform": "YouTube",
        "title": "Video candidato",
        "description": "Desc",
        "tags": [],
        "channel_id": channel_id,
        "channel_title": "Canale Seed",
        "published_at": "2026-09-01T10:00:00Z",
        "duration_seconds": 120,
        "views": 1000,
        "likes": 50,
        "comments": 5,
        "acquired_at": "2026-09-10T10:00:00Z",
    }


class NichePreviewApiTest(unittest.TestCase):
    """L'endpoint preview non deve mai rispondere con un 500 grezzo:
    errori YouTube → 502 con dettaglio, errori imprevisti → 500 leggibile."""

    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "niches_api.db"
        database.initialize()
        user, _ = register("preview@example.com", "password-molto-sicura", "Preview Org")
        self.request = SimpleNamespace(state=SimpleNamespace(user={"id": user["id"]}))
        self.niche = database.create_niche(
            project_id=1, name="Preview niche",
            seed_channels=[{"channel_id": "UCseed", "channel_title": ""}],
        )

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def _call_preview(self, connector):
        with patch("app.main.YouTubeConnector", return_value=connector):
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
                return preview_niche(
                    self.niche["id"],
                    NichePreviewRequest(filters={"max_results": 10}),
                    self.request,
                )

    def test_preview_returns_items_and_source_stats(self):
        class OkConnector:
            def resolve_channel(self, ref):
                return ref

            def search(self, **kwargs):
                return ["vid1"]

            def fetch_details(self, content_ids, **kwargs):
                return [_preview_content()]

        payload = self._call_preview(OkConnector())
        self.assertEqual(payload["items"][0]["external_id"], "vid1")
        self.assertEqual(payload["stats"]["sources"][0]["found"], 1)
        self.assertEqual(payload["stats"]["kept"], 1)

    def test_preview_youtube_error_becomes_json_502(self):
        class FailingConnector:
            def resolve_channel(self, ref):
                return ref

            def search(self, **kwargs):
                raise YouTubeAPIError("risposta API non valida")

        with self.assertRaises(HTTPException) as caught:
            self._call_preview(FailingConnector())
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(caught.exception.detail, "risposta API non valida")

    def test_preview_quota_error_becomes_json_503(self):
        """C3: la quota esaurita produce 503 con messaggio chiaro, non 502."""
        class QuotaConnector:
            def resolve_channel(self, ref):
                return ref

            def search(self, **kwargs):
                raise YouTubeAPIError("The request cannot be completed because you have exceeded your quota")

        with self.assertRaises(HTTPException) as caught:
            self._call_preview(QuotaConnector())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("Quota giornaliera YouTube API esaurita", caught.exception.detail)

    def test_preview_unexpected_error_becomes_readable_json_500(self):
        class BrokenConnector:
            def resolve_channel(self, ref):
                return ref

            def search(self, **kwargs):
                raise RuntimeError("boom")

        with self.assertRaises(HTTPException) as caught:
            self._call_preview(BrokenConnector())
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIn("Errore interno: RuntimeError: boom", caught.exception.detail)

    def test_preview_rejects_users_without_project_access(self):
        outsider, _ = register("outsider@example.com", "password-molto-sicura", "Altra Org")
        foreign_request = SimpleNamespace(state=SimpleNamespace(user={"id": outsider["id"]}))
        with self.assertRaises(HTTPException) as caught:
            preview_niche(self.niche["id"], NichePreviewRequest(filters={}), foreign_request)
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
