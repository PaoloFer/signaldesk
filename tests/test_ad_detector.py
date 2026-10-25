import tempfile
import unittest
from pathlib import Path

from app import database
from app.ad_detector import detect_ad, detect_main_brand


class AdDetectorTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "ad_detector.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def content(self, **kwargs):
        defaults = {
            "external_id": "vid1",
            "platform": "YouTube",
            "title": "",
            "description": "",
            "tags_json": "[]",
            "channel_id": "UCxxx",
            "channel_title": "Test Channel",
            "published_at": "2026-09-01T10:00:00+00:00",
            "duration_seconds": 600,
            "views": 1000,
            "likes": 50,
            "comments": 10,
            "has_paid_product_placement": 0,
        }
        defaults.update(kwargs)
        return defaults

    def test_sponsorship_directa_chiara(self):
        content = self.content(
            title="Come risparmio con Revolut",
            description="Grazie a Revolut per aver sponsorizzato questo video. Codice MARIO10.",
            tags_json='["finanza", "#ad"]',
            has_paid_product_placement=1,
            transcript="grazie a Revolut per aver sponsorizzato questo video",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "sponsorship")
        self.assertGreaterEqual(result["confidence"], 0.90)
        self.assertEqual(result["disclosure_quality"], "clear")
        self.assertEqual(result["brand_name"], "Revolut")
        self.assertTrue(result["is_commercial"])
        self.assertTrue(result["is_disclosed"])

    def test_affiliate_puro(self):
        content = self.content(
            title="I miei attrezzi",
            description="Tutti i prodotti: amzn.to/xyz123?tag=mario-21 (link affiliato).",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "affiliate")
        self.assertGreaterEqual(result["confidence"], 0.75)
        self.assertEqual(result["disclosure_quality"], "clear")
        self.assertEqual(result["brand_name"], "Amazon")

    def test_product_placement(self):
        content = self.content(
            title="Unboxing Samsung",
            description="Samsung mi ha inviato questo telefono in omaggio.",
            has_paid_product_placement=1,
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "product_placement")
        self.assertEqual(result["brand_name"], "Samsung")
        self.assertTrue(result["is_commercial"])

    def test_hidden_ad_pattern(self):
        content = self.content(
            title="L'app che uso per investire",
            description="Link in descrizione per scaricare Trade Republic. traderepublic.com/r/mario",
            transcript="Uso Trade Republic da mesi, trovate il link in descrizione.",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "sponsorship")
        self.assertEqual(result["disclosure_quality"], "missing")
        self.assertEqual(result["brand_name"], "Trade Republic")

    def test_recensione_genuina_non_e_ad(self):
        content = self.content(
            title="Recensione iPhone 16",
            description="Ho comprato l'iPhone 16 con i miei soldi. Questa è la mia opinione sincera.",
            transcript="Non mi ha pagato nessuno. Questo è il mio parere.",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "none")
        self.assertLess(result["confidence"], 0.20)
        self.assertFalse(result["is_commercial"])

    def test_news_context_non_e_ad(self):
        content = self.content(
            title="Apple licenzia 100 dipendenti",
            description="Analisi delle ultime notizie su Apple.",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "none")
        self.assertLess(result["confidence"], 0.20)

    def test_mixed_sponsor_e_affiliate(self):
        content = self.content(
            title="Routine skincare",
            description="Grazie a The Ordinary per aver sponsorizzato questo video. Link prodotti: amzn.to/abc?tag=mario-21",
            has_paid_product_placement=1,
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "mixed")
        self.assertGreaterEqual(result["confidence"], 0.90)

    def test_confronto_multi_brand_senza_link(self):
        content = self.content(
            title="Revolut vs N26 vs Wise",
            description="Confronto oggettivo. Nessun link affiliato.",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "organic_uncertain")
        self.assertLess(result["confidence"], 0.40)

    def test_affiliate_con_codice_generico(self):
        content = self.content(
            title="Libri che mi hanno cambiato",
            description="Tutti i libri linkati in descrizione (Amazon affiliate). amazon.it/libri?tag=mario-21",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "affiliate")
        self.assertGreaterEqual(result["confidence"], 0.80)

    def test_sponsor_disclosure_ambigua(self):
        content = self.content(
            title="Come organizzo i miei soldi",
            description="#partner",
            transcript="Uso questa app da un po'... N26",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "sponsorship")
        self.assertEqual(result["disclosure_quality"], "ambiguous")

    def test_negative_brand_mention_non_e_ad(self):
        content = self.content(
            title="Perché non uso più Revolut",
            description="Revolut fa schifo, non usatela.",
        )
        result = detect_ad(content)
        self.assertEqual(result["ad_type"], "none")
        self.assertLess(result["confidence"], 0.20)

    def test_detect_main_brand(self):
        content = self.content(
            title="Come risparmio con Revolut",
            description="Grazie a Revolut per aver sponsorizzato questo video.",
        )
        brand = detect_main_brand(content, [])
        self.assertEqual(brand, "Revolut")

    def test_database_upsert_and_retrieve_signal(self):
        project = database.create_project("AD Test", "")
        content = {
            "external_id": "ad1", "platform": "YouTube", "title": "Sponsor",
            "description": "Grazie a Nike per aver sponsorizzato questo video.",
            "tags_json": "[]", "channel_id": "UCx", "channel_title": "Ch",
            "published_at": "2026-09-01T10:00:00+00:00", "duration_seconds": 300,
            "views": 100, "likes": 5, "comments": 1, "has_paid_product_placement": 0,
            "niche": "", "topic": "", "source_query": "", "acquired_at": "2026-09-01T10:00:00+00:00",
        }
        database.upsert_contents([content], project_id=project["id"])
        stored = database.all_contents(project["id"])
        self.assertEqual(len(stored), 1)

        assessment = detect_ad(stored[0])
        database.upsert_content_ad_signal(
            project["id"], stored[0]["id"], "YouTube", stored[0]["external_id"], assessment
        )

        signal = database.get_content_ad_signal(project["id"], stored[0]["id"])
        self.assertIsNotNone(signal)
        self.assertEqual(signal["ad_type"], "sponsorship")
        self.assertEqual(signal["brand_name"], "Nike")

    def test_database_run_ad_detection_for_project(self):
        project = database.create_project("AD Batch", "")
        contents = [
            {
                "external_id": "b1", "platform": "YouTube", "title": "Affiliate",
                "description": "Link affiliato amazon.it/prod?tag=x",
                "tags_json": "[]", "channel_id": "UCx", "channel_title": "Ch",
                "published_at": "2026-09-01T10:00:00+00:00", "duration_seconds": 300,
                "views": 100, "likes": 5, "comments": 1, "has_paid_product_placement": 0,
                "niche": "", "topic": "", "source_query": "", "acquired_at": "2026-09-01T10:00:00+00:00",
            },
            {
                "external_id": "b2", "platform": "YouTube", "title": "No ad",
                "description": "Video senza pubblicità.",
                "tags_json": "[]", "channel_id": "UCx", "channel_title": "Ch",
                "published_at": "2026-09-01T10:00:00+00:00", "duration_seconds": 300,
                "views": 100, "likes": 5, "comments": 1, "has_paid_product_placement": 0,
                "niche": "", "topic": "", "source_query": "", "acquired_at": "2026-09-01T10:00:00+00:00",
            },
        ]
        database.upsert_contents(contents, project_id=project["id"])
        result = database.run_ad_detection_for_project(project["id"])
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["stored"], 2)

        signals = database.list_ad_signals(project["id"])
        self.assertEqual(len(signals), 2)
        types = {s["ad_type"] for s in signals}
        self.assertIn("affiliate", types)
        self.assertIn("none", types)


if __name__ == "__main__":
    unittest.main()
