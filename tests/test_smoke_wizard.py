"""Smoke test end-to-end del flusso wizard (H1).

Progetto → nicchia → preview → populate (job) → report, usando gli endpoint
reali chiamati direttamente con un connettore YouTube finto, secondo il
pattern già usato in ``test_niches.py``.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import database
from app import jobs
from app import main
from app.auth import register


def _content(external_id: str) -> dict:
    return {
        "external_id": external_id,
        "platform": "YouTube",
        "title": f"Video {external_id}",
        "description": "Descrizione pubblica",
        "tags": ["corsa"],
        "channel_id": "UCseed",
        "channel_title": "Canale Seed",
        "published_at": "2026-09-01T10:00:00+00:00",
        "duration_seconds": 300,
        "views": 1000,
        "likes": 50,
        "comments": 5,
        "relevance_score": 1.0,
        "acquired_at": "2026-09-10T10:00:00+00:00",
    }


class FakeConnector:
    def resolve_channel(self, reference):
        return reference

    def search(self, **kwargs):
        return ["smoke-vid-1"]

    def fetch_details(self, content_ids, **kwargs):
        return [_content(video_id) for video_id in content_ids]

    def fetch_comments(self, content_id, **kwargs):
        return {"video_id": content_id, "title": f"Video {content_id}", "channel": "Canale"}, [
            {
                "external_id": f"{content_id}-comment-1",
                "content_id": content_id,
                "content_title": f"Video {content_id}",
                "author_hash": "smoke-author",
                "text": "Commento pubblico di prova",
                "published_at": "2026-09-05T10:00:00+00:00",
                "platform": "YouTube",
                "niche": kwargs.get("niche", ""),
                "topic": kwargs.get("topic", ""),
            }
        ]


class WizardSmokeTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "smoke.db"
        database.initialize()
        user, _ = register("smoke@example.com", "password-molto-sicura", "Smoke Org")
        self.request = SimpleNamespace(
            state=SimpleNamespace(user={"id": user["id"]}),
            client=SimpleNamespace(host="127.0.0.1"),
            cookies={},
        )

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_project_niche_preview_populate_report(self):
        # 1. Crea il progetto dall'endpoint reale.
        project = main.project_create(
            main.ProjectCreate(name="Smoke Project", description=""), self.request
        )
        self.assertGreater(project["id"], 0)

        # 2. Crea la nicchia con un canale seed.
        niche = main.niche_create(
            main.NicheCreate(
                project_id=project["id"],
                name="Corsa smoke",
                status="active",
                seed_channels=[main.NicheSeedChannel(channel_id="UCseed")],
                include_keywords=["corsa"],
            ),
            self.request,
        )
        self.assertEqual(niche["project_id"], project["id"])

        # 3. Preview con connettore finto: nessuna quota reale consumata.
        with patch("app.main.YouTubeConnector", return_value=FakeConnector()):
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
                preview = main.preview_niche(
                    niche["id"], main.NichePreviewRequest(filters={}), self.request
                )
        self.assertEqual(preview["total"], 1)
        self.assertEqual(preview["items"][0]["external_id"], "smoke-vid-1")

        # 4. Populate: l'endpoint accoda il job, il worker finto lo esegue.
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
            queued = main.populate_niche(
                niche["id"],
                main.NichePopulateRequest(
                    content_ids=["smoke-vid-1"], auto_fetch_comments=True,
                    max_comment_videos=1, comments_per_video=10,
                ),
                self.request,
            )
        with patch("app.jobs.YouTubeConnector", return_value=FakeConnector()):
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
                self.assertTrue(jobs.process_next_job())
        job = main.job_detail(queued["job"]["id"], self.request)
        self.assertEqual(job["status"], "completed", msg=job.get("error"))

        # 5. Il progetto contiene video e commenti, i report rispondono.
        contents = database.all_contents(project["id"])
        self.assertEqual(len(contents), 1)
        comments = database.all_comments(project["id"])
        self.assertEqual(len(comments), 1)

        report = main.report(self.request, project_id=project["id"], days=90)
        self.assertEqual(report["metrics"]["comments"], 1)
        content_report = main.content_report(self.request, project_id=project["id"], days=365)
        self.assertEqual(content_report["metrics"]["contents"], 1)


if __name__ == "__main__":
    unittest.main()
