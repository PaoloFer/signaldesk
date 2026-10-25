import unittest
from datetime import datetime, timedelta, timezone

from app.content_intelligence import build_content_report, classify_content


class ContentIntelligenceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 17, tzinfo=timezone.utc)

    def content(self, identifier, days_ago, niche="Running", channel="Run Lab", views=1000, title=None):
        return {
            "external_id": identifier, "platform": "YouTube", "title": title or f"Video {identifier}",
            "description": "", "channel_id": channel, "channel_title": channel,
            "published_at": (self.now - timedelta(days=days_ago)).isoformat(),
            "duration_seconds": 300, "views": views, "likes": 50, "comments": 10,
            "niche": niche, "topic": "Recupero", "source_query": "running",
            "acquired_at": self.now.isoformat(),
        }

    def test_aggregates_content_landscape(self):
        contents = [self.content("a", 1), self.content("b", 2, views=3000)]
        report = build_content_report(contents, self.now)
        self.assertEqual(report["metrics"]["contents"], 2)
        self.assertEqual(report["metrics"]["views"], 4000)
        self.assertEqual(report["channels"][0]["average_views"], 2000)
        self.assertEqual(report["durations"][2]["contents"], 2)

    def test_filters_period_and_niche(self):
        contents = [
            self.content("a", 2), self.content("b", 2, niche="Food"),
            self.content("c", 40),
        ]
        report = build_content_report(contents, self.now, days=7, niche="Running")
        self.assertEqual(report["metrics"]["contents"], 1)

    def test_extracts_language_and_compares_niches(self):
        contents = [
            self.content("a", 1, niche="Running", title="Recupero muscolare corsa"),
            self.content("b", 1, niche="Running", title="Allenamento corsa lenta"),
            self.content("c", 1, niche="Food", title="Recupero con proteine vegetali"),
            self.content("d", 1, niche="Food", title="Ricette proteine vegetali"),
        ]
        report = build_content_report(contents, self.now, comparison_names=("Running", "Food"))
        self.assertIn("recupero", [item["name"] for item in report["terms"]])
        self.assertIn("recupero", report["comparison"]["shared_terms"])
        self.assertIn("corsa", report["comparison"]["distinctive_left"])

    def test_calculates_trajectory_from_snapshots(self):
        contents = [self.content("a", 5, views=2000)]
        snapshots = [
            {"external_id": "a", "captured_at": (self.now - timedelta(days=2)).isoformat(), "views": 1000},
            {"external_id": "a", "captured_at": self.now.isoformat(), "views": 2000},
        ]
        report = build_content_report(contents, self.now, raw_snapshots=snapshots)
        self.assertEqual(report["metrics"]["tracked"], 1)
        self.assertEqual(report["trajectories"][0]["views_per_day"], 500)
        self.assertEqual(report["trajectories"][0]["growth_percent"], 100.0)

    def test_classifies_format_purpose_and_commercial_signals(self):
        content = self.content("sponsor", 1, title="Podcast in collaborazione con RunFast")
        content["duration_seconds"] = 1800
        content["description"] = "Usa il codice sconto RUN10 #adv"
        content["tags_json"] = '["intervista", "running"]'
        classification = classify_content(content)
        self.assertEqual(classification["format"], "Lungo >15 min")
        self.assertIn("Podcast", classification["purposes"])
        self.assertIn("Intervista", classification["purposes"])
        self.assertIn("codice promozionale", classification["commercial_signals"])

        report = build_content_report([content], self.now)
        self.assertEqual(report["commercial_signals"]["contents"], 1)
        self.assertEqual(report["taxonomy"]["tags"][0]["documents"], 1)

    def test_graph_exposes_channels_bridging_niches(self):
        contents = [
            self.content("a", 1, niche="Running", channel="Bridge Channel"),
            self.content("b", 1, niche="Food", channel="Bridge Channel"),
            self.content("c", 1, niche="Food", channel="Food Only"),
        ]
        graph = build_content_report(contents, self.now)["graph"]
        bridge = next(item for item in graph["bridges"] if item["name"] == "Bridge Channel")
        self.assertEqual(bridge["type"], "channel")
        self.assertEqual(bridge["niches"], ["Food", "Running"])
        self.assertTrue(any(node["type"] == "niche" for node in graph["nodes"]))
        self.assertGreater(len(graph["edges"]), 0)

    def test_compares_language_across_platforms(self):
        contents = [
            self.content("a", 1, title="Recupero corsa YouTube"),
            self.content("b", 1, title="Allenamento corsa YouTube"),
            self.content("c", 1, title="Recupero corsa TikTok"),
            self.content("d", 1, title="Challenge corsa TikTok"),
        ]
        contents[2]["platform"] = "TikTok"
        contents[3]["platform"] = "TikTok"
        report = build_content_report(contents, self.now)
        self.assertEqual(len(report["platforms"]["items"]), 2)
        self.assertIn("recupero", report["platforms"]["comparison"]["shared_terms"])
        self.assertIn("allenamento", report["platforms"]["comparison"]["distinctive_left"])


if __name__ == "__main__":
    unittest.main()
