import unittest
from datetime import datetime, timedelta, timezone

from app.intelligence import build_intelligence_report, normalize_text


class IntelligenceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 20, tzinfo=timezone.utc)

    def comment(self, identifier, published_at, text="Commento normale", **values):
        return {
            "id": identifier,
            "content_id": values.get("content_id", "video-1"),
            "content_title": values.get("content_title", "Video di test"),
            "author_hash": values.get("author_hash", f"user-{identifier}"),
            "text": text,
            "published_at": published_at.isoformat(),
            "niche": values.get("niche", "Running"),
            "topic": values.get("topic", "Recupero"),
        }

    def test_normalizes_equivalent_text(self):
        self.assertEqual(normalize_text("Ciao, MONDO!"), "ciao mondo")

    def test_detects_hourly_anomaly_and_explains_it(self):
        comments = []
        for day in range(1, 8):
            comments.append(self.comment(day, self.now - timedelta(days=day)))
        for index in range(12):
            comments.append(self.comment(100 + index, self.now - timedelta(minutes=index), "Testo coordinato"))
        report = build_intelligence_report(comments, self.now)
        self.assertEqual(report["metrics"]["anomalies"], 1)
        self.assertGreaterEqual(report["events"][0]["multiplier"], 10)
        self.assertIn("rispetto", report["events"][0]["calculated"])

    def test_compares_niches_using_aggregated_audience(self):
        comments = [
            self.comment(1, self.now, author_hash="shared", niche="Running", topic="Recupero"),
            self.comment(2, self.now, author_hash="runner", niche="Running", topic="Scarpe"),
            self.comment(3, self.now, author_hash="shared", niche="Food", topic="Recupero"),
            self.comment(4, self.now, author_hash="cook", niche="Food", topic="Proteine"),
        ]
        comparison = build_intelligence_report(comments, self.now)["niches"]["comparison"]
        self.assertEqual(comparison["audience_overlap"], 33)
        self.assertEqual(comparison["shared_topics"], ["Recupero"])

    def test_filters_by_period_and_niche(self):
        comments = [
            self.comment(1, self.now - timedelta(days=2), niche="Running"),
            self.comment(2, self.now - timedelta(days=2), niche="Food"),
            self.comment(3, self.now - timedelta(days=20), niche="Running"),
        ]
        report = build_intelligence_report(comments, self.now, days=7, niche="Running")
        self.assertEqual(report["metrics"]["comments"], 1)
        self.assertEqual(report["niches"]["items"][0]["name"], "Running")

    def test_compares_requested_niches(self):
        comments = [
            self.comment(1, self.now, niche="Running", topic="Recupero"),
            self.comment(2, self.now, niche="Food", topic="Recupero"),
            self.comment(3, self.now, niche="Gaming", topic="Hardware"),
        ]
        report = build_intelligence_report(
            comments, self.now, comparison_names=("Food", "Gaming")
        )
        comparison = report["niches"]["comparison"]
        self.assertEqual(comparison["left"], "Food")
        self.assertEqual(comparison["right"], "Gaming")


if __name__ == "__main__":
    unittest.main()
