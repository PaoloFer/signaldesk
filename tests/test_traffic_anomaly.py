import unittest
from datetime import datetime, timedelta, timezone

from app.traffic_anomaly import (
    GROWTH_INSUFFICIENT_DATA,
    GROWTH_LATE_SPIKE,
    GROWTH_LINEAR,
    GROWTH_ORGANIC,
    classify_growth_shape,
    compute_channel_baselines,
    detect_traffic_anomalies,
)


def _content(external_id, channel_id, views, likes=0, comments=0):
    now = datetime.now(timezone.utc)
    return {
        "external_id": external_id,
        "title": f"Video {external_id}",
        "description": "",
        "tags_json": "[]",
        "channel_id": channel_id,
        "channel_title": "Canale Test",
        "published_at": now.isoformat(),
        "duration_seconds": 600,
        "views": views,
        "likes": likes,
        "comments": comments,
        "niche": "Test",
        "topic": "",
        "source_query": "",
        "acquired_at": now.isoformat(),
    }


def _snapshots(external_id, views_series):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [
        {
            "external_id": external_id,
            "platform": "YouTube",
            "captured_at": (start + timedelta(days=index)).isoformat(),
            "views": views,
            "likes": 0,
            "comments": 0,
        }
        for index, views in enumerate(views_series)
    ]


class GrowthShapeTest(unittest.TestCase):
    def test_organic_decay(self):
        # Delta: 900, 60, 40 -> il primo intervallo copre oltre il 60%.
        shape = classify_growth_shape(_snapshots("v1", [1000, 1900, 1960, 2000]))
        self.assertEqual(shape, GROWTH_ORGANIC)

    def test_linear_growth(self):
        # Delta uniformi 100/100/100: tipico boost prolungato.
        shape = classify_growth_shape(_snapshots("v1", [1000, 1100, 1200, 1300]))
        self.assertEqual(shape, GROWTH_LINEAR)

    def test_late_spike(self):
        # Delta: 50, 50, 400 -> salto anomalo dopo il primo intervallo.
        shape = classify_growth_shape(_snapshots("v1", [1000, 1050, 1100, 1500]))
        self.assertEqual(shape, GROWTH_LATE_SPIKE)

    def test_insufficient_data(self):
        shape = classify_growth_shape(_snapshots("v1", [1000, 2000]))
        self.assertEqual(shape, GROWTH_INSUFFICIENT_DATA)


class BaselineTest(unittest.TestCase):
    def test_channel_baseline_requires_min_videos(self):
        contents = [_content(f"v{index}", "UC1", 1000) for index in range(4)]
        contents += [_content(f"w{index}", "UC2", 500) for index in range(2)]
        baselines = compute_channel_baselines(contents)
        self.assertIn("UC1", baselines["channels"])
        self.assertNotIn("UC2", baselines["channels"])
        self.assertIsNotNone(baselines["global"])

    def test_median_and_mad(self):
        contents = [
            _content("v1", "UC1", 1000),
            _content("v2", "UC1", 2000),
            _content("v3", "UC1", 3000),
        ]
        stats = compute_channel_baselines(contents)["channels"]["UC1"]
        self.assertEqual(stats["views_median"], 2000)
        self.assertEqual(stats["views_mad"], 1000)


class AnomalyDetectionTest(unittest.TestCase):
    def test_views_outlier_flagged(self):
        contents = [_content(f"v{index}", "UC1", 1000, likes=50, comments=10) for index in range(4)]
        contents.append(_content("outlier", "UC1", 10000, likes=500, comments=100))
        results = {entry["external_id"]: entry for entry in detect_traffic_anomalies(contents)}
        self.assertIn("views_fuori_scala", results["outlier"]["anomalies"])
        self.assertGreaterEqual(results["outlier"]["score"], 0.4)
        self.assertEqual(results["v0"]["score"], 0.0)

    def test_engagement_anomaly_flagged(self):
        contents = [
            _content("v1", "UC1", 1000, likes=35, comments=5),
            _content("v2", "UC1", 1200, likes=66, comments=6),
            _content("v3", "UC1", 900, likes=36, comments=5),
            _content("v4", "UC1", 1100, likes=55, comments=6),
            _content("outlier", "UC1", 3000, likes=5, comments=1),
        ]
        results = {entry["external_id"]: entry for entry in detect_traffic_anomalies(contents)}
        self.assertIn("engagement_basso", results["outlier"]["anomalies"])

    def test_growth_shape_contributes_to_score(self):
        contents = [_content(f"v{index}", "UC1", 1000) for index in range(3)]
        contents.append(_content("boosted", "UC1", 1000))
        snapshots = _snapshots("boosted", [1000, 1050, 1100, 1500])
        results = {entry["external_id"]: entry for entry in detect_traffic_anomalies(contents, snapshots)}
        self.assertEqual(results["boosted"]["growth_shape"], GROWTH_LATE_SPIKE)
        self.assertIn("spike_tardivo", results["boosted"]["anomalies"])

    def test_results_sorted_by_score(self):
        contents = [_content(f"v{index}", "UC1", 1000) for index in range(4)]
        contents.append(_content("outlier", "UC1", 10000))
        results = detect_traffic_anomalies(contents)
        self.assertEqual(results[0]["external_id"], "outlier")


if __name__ == "__main__":
    unittest.main()
