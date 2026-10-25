import unittest
from datetime import datetime, timezone

from app.adv_intelligence import (
    build_adv_report,
    build_suspicion_report,
    detect_weak_signals,
    extract_gift_sponsor_candidates,
    extract_sponsor_candidates,
    search_sponsor,
)


class AdvIntelligenceTest(unittest.TestCase):
    def _fixture(self, now=None):
        now = now or datetime.now(timezone.utc)
        return [
            {
                "external_id": "vid-1",
                "title": "Recensione scarpe Nike",
                "description": "Video sponsorizzato da Nike. Grazie a Nike per il supporto.",
                "tags_json": '["running"]',
                "channel_id": "UC1", "channel_title": "RunLab",
                "published_at": now.isoformat(), "duration_seconds": 600,
                "views": 5000, "likes": 200, "comments": 50,
                "niche": "Corsa", "topic": "Recensione",
                "source_query": "scarpe", "acquired_at": now.isoformat(),
            },
            {
                "external_id": "vid-2",
                "title": "Allenamento con Garmin",
                "description": "In collaborazione con Garmin. #ad #Garmin",
                "tags_json": '["fitness"]',
                "channel_id": "UC2", "channel_title": "FitChannel",
                "published_at": now.isoformat(), "duration_seconds": 900,
                "views": 8000, "likes": 300, "comments": 80,
                "niche": "Fitness", "topic": "Allenamento",
                "source_query": "allenamento", "acquired_at": now.isoformat(),
            },
            {
                "external_id": "vid-3",
                "title": "Integratori per runner",
                "description": "Link affiliato in descrizione. Codice sconto PROTEIN20 per MyProtein.",
                "tags_json": '["integratori"]',
                "channel_id": "UC1", "channel_title": "RunLab",
                "published_at": now.isoformat(), "duration_seconds": 480,
                "views": 3000, "likes": 100, "comments": 30,
                "niche": "Corsa", "topic": "Nutrizione",
                "source_query": "integratori", "acquired_at": now.isoformat(),
            },
            {
                "external_id": "vid-4",
                "title": "Garmin per la corsa",
                "description": "Sponsorizzato da Garmin. #running",
                "tags_json": '["running"]',
                "channel_id": "UC3", "channel_title": "CorsaChannel",
                "published_at": now.isoformat(), "duration_seconds": 700,
                "views": 4000, "likes": 150, "comments": 40,
                "niche": "Corsa", "topic": "Recensione",
                "source_query": "garmin", "acquired_at": now.isoformat(),
            },
        ]

    def test_extract_sponsor_candidates_finds_direct_sponsors(self):
        text = "sponsorizzato da Nike e in collaborazione con Apple"
        sponsors = extract_sponsor_candidates(text)
        self.assertIn("Nike", sponsors)
        self.assertIn("Apple", sponsors)

    def test_build_adv_report_aggregates_sponsors(self):
        contents = self._fixture()
        report = build_adv_report(contents, days=90)
        self.assertEqual(report["metrics"]["contents_with_ads"], 4)
        names = [s["name"] for s in report["top_sponsors"]]
        self.assertIn("Nike", names)
        self.assertIn("Garmin", names)
        self.assertIn("MyProtein", names)

    def test_build_adv_report_detects_cross_niche_bridges(self):
        contents = self._fixture()
        report = build_adv_report(contents, days=90)
        bridges = report["cross_niche_bridges"]
        garmin_bridge = next((b for b in bridges if b["sponsor"] == "Garmin"), None)
        self.assertIsNotNone(garmin_bridge)
        self.assertIn("Corsa", garmin_bridge["niches"])
        self.assertIn("Fitness", garmin_bridge["niches"])

    def test_build_adv_report_builds_indirect_niches(self):
        contents = self._fixture()
        report = build_adv_report(contents, days=90)
        indirect = report["indirect_niches"]
        garmin_niche = next((n for n in indirect if n["seed_sponsor"] == "Garmin"), None)
        self.assertIsNotNone(garmin_niche)
        self.assertEqual(garmin_niche["contents"], 2)
        self.assertIn("FitChannel", garmin_niche["channels"])
        self.assertIn("CorsaChannel", garmin_niche["channels"])

    def test_search_sponsor_filters_by_brand(self):
        contents = self._fixture()
        result = search_sponsor(contents, query="Nike")
        self.assertEqual(result["metrics"]["matches"], 1)
        self.assertEqual(result["matches"][0]["title"], "Recensione scarpe Nike")

    def test_search_sponsor_is_case_insensitive(self):
        contents = self._fixture()
        result = search_sponsor(contents, query="nike")
        self.assertEqual(result["metrics"]["matches"], 1)


class WeakSignalsTest(unittest.TestCase):
    def test_gift_language_detected(self):
        item = {
            "title": "Nuove scarpe",
            "description": "Mi hanno inviato queste scarpe, che ne pensate?",
            "tags_json": "[]",
        }
        types = [signal["type"] for signal in detect_weak_signals(item)]
        self.assertIn("gift_language", types)

    def test_affiliate_domain_detected(self):
        item = {
            "title": "Link utili",
            "description": "Trovi tutto qui https://linktr.ee/mionome",
            "tags_json": "[]",
        }
        signals = detect_weak_signals(item)
        affiliate = next(signal for signal in signals if signal["type"] == "affiliate_link")
        self.assertIn("linktr.ee", affiliate["evidence"])

    def test_utm_tracking_detected(self):
        item = {
            "title": "Shop",
            "description": "Visita https://shop.example.it/?utm_source=youtube&utm_medium=video",
            "tags_json": "[]",
        }
        types = [signal["type"] for signal in detect_weak_signals(item)]
        self.assertIn("affiliate_link", types)

    def test_paid_placement_flag_is_certain(self):
        item = {"title": "Video", "description": "", "tags_json": "[]", "has_paid_product_placement": 1}
        signals = detect_weak_signals(item)
        self.assertEqual(signals[0]["type"], "paid_placement_flag")
        self.assertEqual(signals[0]["weight"], 1.0)

    def test_no_signals_on_clean_content(self):
        item = {
            "title": "Allenamento libero",
            "description": "Oggi ci alleniamo insieme all'aperto",
            "tags_json": "[]",
        }
        self.assertEqual(detect_weak_signals(item), [])

    def test_gift_sponsor_extraction(self):
        candidates = extract_gift_sponsor_candidates("Ho ricevuto in omaggio da Garmin il nuovo orologio")
        self.assertIn("Garmin", candidates)
        candidates = extract_gift_sponsor_candidates("Nike mi ha inviato le scarpe")
        self.assertIn("Nike", candidates)


class SuspicionReportTest(unittest.TestCase):
    def _fixture(self, now=None):
        now = now or datetime.now(timezone.utc)
        gift_videos = [
            {
                "external_id": f"sus-{index}",
                "title": f"Unboxing {index}",
                "description": "Mi hanno inviato da ProteinCo il nuovo prodotto",
                "tags_json": "[]",
                "channel_id": "UC9", "channel_title": "FitReviews",
                "published_at": now.isoformat(), "duration_seconds": 600,
                "views": 1000 + index * 100, "likes": 50, "comments": 10,
                "niche": "Fitness", "topic": "", "source_query": "",
                "acquired_at": now.isoformat(),
            }
            for index in range(3)
        ]
        return gift_videos + [
            {
                "external_id": "decl-1",
                "title": "Recensione dichiarata",
                "description": "Video sponsorizzato da Nike",
                "tags_json": "[]",
                "channel_id": "UC1", "channel_title": "RunLab",
                "published_at": now.isoformat(), "duration_seconds": 600,
                "views": 1200, "likes": 60, "comments": 12,
                "niche": "Fitness", "topic": "", "source_query": "",
                "acquired_at": now.isoformat(),
            },
            {
                "external_id": "clean-1",
                "title": "Allenamento libero",
                "description": "Oggi ci alleniamo insieme",
                "tags_json": "[]",
                "channel_id": "UC2", "channel_title": "FitChannel",
                "published_at": now.isoformat(), "duration_seconds": 600,
                "views": 800, "likes": 40, "comments": 8,
                "niche": "Fitness", "topic": "", "source_query": "",
                "acquired_at": now.isoformat(),
            },
        ]

    def test_flags_undeclared_sponsor_with_repetition(self):
        report = build_suspicion_report(self._fixture(), days=90)
        self.assertEqual(report["metrics"]["suspects"], 3)
        self.assertEqual(report["metrics"]["declared_excluded"], 1)
        for entry in report["items"]:
            self.assertEqual(entry["classification"], "sospetto")
            self.assertIn("ProteinCo", entry["suspected_brands"])
            types = {signal["type"] for signal in entry["signals"]}
            self.assertIn("gift_language", types)
            self.assertIn("brand_repetition", types)
        self.assertEqual(report["top_suspected_brands"][0]["name"], "ProteinCo")

    def test_declared_included_on_request(self):
        report = build_suspicion_report(self._fixture(), days=90, include_declared=True)
        declared = next((entry for entry in report["items"] if entry["external_id"] == "decl-1"), None)
        self.assertIsNotNone(declared)
        self.assertEqual(declared["classification"], "dichiarato")
        self.assertEqual(report["metrics"]["declared_included"], 1)

    def test_paid_placement_flag_makes_probable(self):
        contents = self._fixture()
        contents[0]["has_paid_product_placement"] = 1
        report = build_suspicion_report(contents, days=90)
        entry = next(item for item in report["items"] if item["external_id"] == "sus-0")
        self.assertEqual(entry["classification"], "probabile")
        self.assertGreaterEqual(report["metrics"]["probable"], 1)

    def test_clean_content_excluded(self):
        report = build_suspicion_report(self._fixture(), days=90)
        ids = [entry["external_id"] for entry in report["items"]]
        self.assertNotIn("clean-1", ids)


if __name__ == "__main__":
    unittest.main()
