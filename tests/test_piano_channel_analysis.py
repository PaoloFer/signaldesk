import unittest

from app.niche_discovery import aggregate_channel_pool
from scripts.analyze_piano_channels import _matches_italian_market


class PianoChannelAnalysisTest(unittest.TestCase):
    def test_channel_creation_date_is_preserved_in_aggregation(self):
        contents = [{
            "external_id": "v1", "platform": "YouTube", "channel_id": "UC1",
            "channel_title": "Piano", "title": "Lezione", "description": "",
            "tags": [], "published_at": "2026-01-02T00:00:00Z", "views": 10,
            "likes": 1, "comments": 1, "duration_seconds": 60,
        }]
        channels = aggregate_channel_pool(contents, {
            "UC1": {"published_at": "2025-06-01T00:00:00Z"},
        })
        self.assertEqual(channels[0]["channel_published_at"], "2025-06-01T00:00:00Z")

    def test_italian_filter_accepts_declared_or_textual_evidence(self):
        self.assertTrue(_matches_italian_market({"country": "IT"}))
        self.assertTrue(_matches_italian_market({"language": "it"}))
        self.assertTrue(_matches_italian_market({
            "country": "", "language": "", "channel_title": "Lezioni di pianoforte",
            "description": "Imparare a suonare con esercizi e spartiti", "videos": [],
        }))

    def test_italian_filter_rejects_english_false_positive(self):
        self.assertFalse(_matches_italian_market({
            "country": "US", "language": "en", "channel_title": "Piano Steps",
            "description": "Easy beginner piano tutorials and favorite songs", "videos": [],
        }))


if __name__ == "__main__":
    unittest.main()
