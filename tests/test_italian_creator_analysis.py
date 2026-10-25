import unittest

from scripts.analyze_italian_creators import (
    _subscriber_distribution,
    build_niche,
    creator_evidence,
    italian_evidence,
)


class ItalianCreatorAnalysisTest(unittest.TestCase):
    def test_build_niche_applies_italy_and_10k_filters(self):
        niche = build_niche(
            ["vlog italiano"], anchor_channels=[("UC1", "Creator")], days=365, max_results=300,
            min_subscribers=10_000, include_popular=False,
        )
        filters = niche["filters"]
        self.assertEqual(filters["region_code"], "IT")
        self.assertEqual(filters["channel_country"], "IT")
        self.assertEqual(filters["channel_language"], "it")
        self.assertFalse(filters["strict_geo"])
        self.assertEqual(filters["min_subscribers"], 10_000)
        self.assertEqual(filters["evidence_depth"], "P2")
        self.assertTrue(filters["cross_theme_ranking"])
        self.assertEqual(niche["seed_channels"][0]["channel_id"], "UC1")

    def test_italianity_is_confirmed_by_declared_metadata(self):
        result = italian_evidence({"country": "IT", "language": ""})
        self.assertEqual(result["status"], "confirmed")
        self.assertIn("paese dichiarato IT", result["reasons"])

    def test_italianity_can_be_probable_from_content(self):
        result = italian_evidence({
            "country": "", "language": "", "channel_title": "Vita in Italia",
            "description": "Oggi vi racconto come fare tutto nella mia vita italiana",
            "videos": [{"title": "Cosa fare prima e dopo", "description": "Questo video è per voi"}],
        })
        self.assertEqual(result["status"], "probable")

    def test_conflicting_declared_country_is_excluded(self):
        result = italian_evidence({
            "country": "US", "language": "en", "channel_title": "Italian food",
            "description": "", "videos": [],
        })
        self.assertEqual(result["status"], "excluded")

    def test_curated_anchor_overrides_conflicting_public_geo(self):
        result = italian_evidence({
            "country": "US", "language": "en", "matched_seed": "channel",
            "anchor_name": "Creator italiano", "channel_title": "Creator",
            "description": "", "videos": [],
        })
        self.assertEqual(result["status"], "confirmed")
        self.assertIn("anchor presente nel registry curato", result["reasons"])

    def test_subscriber_bands_start_at_10k(self):
        channels = [
            {"subscribers": 10_000}, {"subscribers": 49_999},
            {"subscribers": 50_000}, {"subscribers": 1_500_000},
        ]
        distribution = {item["label"]: item["channels"] for item in _subscriber_distribution(channels)}
        self.assertEqual(distribution["10K-50K"], 2)
        self.assertEqual(distribution["50K-100K"], 1)
        self.assertEqual(distribution["1M+"], 1)

    def test_publisher_and_individual_creator_are_separated(self):
        publisher = creator_evidence({
            "channel_title": "Daily News", "description": "Testata giornalistica nazionale",
        })
        individual = creator_evidence({
            "channel_title": "Marco", "description": "Sono un creator e racconto la mia vita",
        })
        title_only_publisher = creator_evidence({
            "channel_title": "Il Messaggero", "description": "",
        })
        self.assertEqual(publisher["status"], "publisher")
        self.assertEqual(individual["status"], "individual")
        self.assertEqual(title_only_publisher["status"], "publisher")


if __name__ == "__main__":
    unittest.main()
