import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.main import PublicPreviewRequest, public_preview
from app.ratelimit import FixedWindowRateLimiter


def sample_channel():
    return {
        "channel_id": "UCsample",
        "channel_title": "Piano Lab",
        "custom_url": "@pianolab",
        "channel_published_at": "2025-01-01T00:00:00Z",
        "country": "IT",
        "language": "it",
        "subscribers": 1200,
        "declared_video_count": 30,
        "video_count": 2,
        "total_views": 3000,
        "avg_views": 1500,
        "engagement_rate": 0.025,
        "last_published_at": "2026-09-01T00:00:00Z",
        "candidate_level": "matched",
        "videos": [
            {
                "external_id": "v1", "platform": "YouTube", "title": "Lezione pianoforte",
                "description": "Tutorial per principianti", "tags": ["piano"],
                "published_at": "2026-09-01T00:00:00Z", "duration_seconds": 180,
                "views": 2000, "likes": 50, "comments": 10,
                "has_paid_product_placement": False, "niche": "Pianoforte",
                "topic": "Pianoforte", "source_query": "pianoforte",
                "acquired_at": "2026-09-02T00:00:00Z",
            },
            {
                "external_id": "v2", "platform": "YouTube", "title": "Accordi facili",
                "description": "Impara gli accordi", "tags": [],
                "published_at": "2026-08-20T00:00:00Z", "duration_seconds": 400,
                "views": 1000, "likes": 20, "comments": 5,
                "has_paid_product_placement": False, "niche": "Pianoforte",
                "topic": "Pianoforte", "source_query": "pianoforte",
                "acquired_at": "2026-09-02T00:00:00Z",
            },
        ],
    }


class PublicPreviewTest(unittest.TestCase):
    def setUp(self):
        self.request = SimpleNamespace(client=SimpleNamespace(host=f"203.0.113.{id(self) % 200 + 1}"))
        self.settings = SimpleNamespace(
            public_preview_enabled=True,
            public_preview_max_channels=100,
        )

    def test_builds_non_persisted_public_report(self):
        payload = PublicPreviewRequest(topic="pianoforte", max_channels=25)
        with (
            patch("app.main.settings", self.settings),
            patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}),
            patch("app.main.ensure_quota_available"),
            patch("app.main.expand_niche_channels", return_value=[sample_channel()]),
            patch("app.main.public_preview_rate_limiter", FixedWindowRateLimiter(2, 86400)),
        ):
            result = public_preview(payload, self.request)

        self.assertEqual(result["coverage"]["channels"], 1)
        self.assertEqual(result["coverage"]["videos"], 2)
        self.assertEqual(result["channels"][0]["title"], "Piano Lab")
        self.assertEqual(result["channels"][0]["engagement_rate"], 2.5)
        self.assertNotIn("description", result["channels"][0])
        self.assertTrue(result["account_required_for"])

    def test_rejects_excess_seed_cardinality(self):
        payload = PublicPreviewRequest(topic="piano", channels=["a", "b", "c"])
        with patch("app.main.settings", self.settings), patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}):
            with self.assertRaises(HTTPException) as context:
                public_preview(payload, self.request)
        self.assertEqual(context.exception.status_code, 400)

    def test_requires_explicit_feature_enablement(self):
        disabled = SimpleNamespace(public_preview_enabled=False, public_preview_max_channels=100)
        with patch("app.main.settings", disabled):
            with self.assertRaises(HTTPException) as context:
                public_preview(PublicPreviewRequest(topic="piano"), self.request)
        self.assertEqual(context.exception.status_code, 503)

    def test_daily_limit_returns_429(self):
        limiter = FixedWindowRateLimiter(1, 86400)
        with (
            patch("app.main.settings", self.settings),
            patch.dict(os.environ, {"YOUTUBE_API_KEY": "key"}),
            patch("app.main.ensure_quota_available"),
            patch("app.main.expand_niche_channels", return_value=[]),
            patch("app.main.public_preview_rate_limiter", limiter),
        ):
            public_preview(PublicPreviewRequest(topic="piano"), self.request)
            with self.assertRaises(HTTPException) as context:
                public_preview(PublicPreviewRequest(topic="piano"), self.request)
        self.assertEqual(context.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
