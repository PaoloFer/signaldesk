import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import database
from app.sponsor_niches import build_sponsor_basin_profile, compare_sponsor_basins
from app.main import (
    SponsorNicheCreate,
    adv_compare_brands,
    entity_sponsor_basin,
    niche_from_sponsor,
)


def _content(external_id, channel_id, channel_title, niche, views=1000):
    return {
        "external_id": external_id,
        "platform": "YouTube",
        "title": f"Video {external_id}",
        "description": "sponsorizzato",
        "tags": ["cucina", "ricetta"],
        "channel_id": channel_id,
        "channel_title": channel_title,
        "published_at": "2026-09-17T00:00:00+00:00",
        "duration_seconds": 300,
        "views": views,
        "likes": 50,
        "comments": 10,
        "niche": niche,
        "topic": "",
        "source_query": "test",
        "acquired_at": "2026-09-17T01:00:00+00:00",
    }


class SponsorNichesTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "sponsor_niches.db"
        database.initialize()
        self.project = database.create_project("Sponsor project")
        self.nike = database.create_entity(self.project["id"], "Nike", type="brand")
        self.adidas = database.create_entity(self.project["id"], "Adidas", type="brand")
        database.upsert_contents([
            _content("nike-1", "UCshared", "Shared", "Running", 5000),
            _content("nike-2", "UCnike", "Nike Creator", "Running", 3000),
            _content("organic", "UCnike", "Nike Creator", "Cucina", 2000),
            _content("adidas-1", "UCshared", "Shared", "Running", 4000),
            _content("adidas-2", "UCadidas", "Adidas Creator", "Fitness", 2500),
        ], self.project["id"])
        by_external = {item["external_id"]: item["id"] for item in database.all_contents(self.project["id"])}
        database.upsert_entity_mentions(self.project["id"], [
            {"content_id": by_external["nike-1"], "name": "Nike", "mention_text": "Nike", "confidence": 0.9},
            {"content_id": by_external["nike-2"], "name": "Nike", "mention_text": "Nike", "confidence": 0.8},
            {"content_id": by_external["adidas-1"], "name": "Adidas", "mention_text": "Adidas", "confidence": 0.9},
            {"content_id": by_external["adidas-2"], "name": "Adidas", "mention_text": "Adidas", "confidence": 0.8},
        ])

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_exact_sponsor_channels_and_full_basin_corpus(self):
        rows = database.sponsored_channels_by_entity(
            self.project["id"], self.nike["id"],
        )
        self.assertEqual({row["channel_id"] for row in rows}, {"UCshared", "UCnike"})
        corpus = database.sponsor_basin_contents(self.project["id"], self.nike["id"])
        # Include anche il contenuto organico del creator Nike.
        self.assertEqual({item["external_id"] for item in corpus}, {"nike-1", "nike-2", "organic", "adidas-1"})

    def test_basin_profile_aggregates_channels_and_themes_without_connector(self):
        database.upsert_channel_profiles(self.project["id"], [{
            "platform": "YouTube", "channel_id": "UCnike", "channel_title": "Nike Creator",
            "country": "IT", "language": "it", "subscribers": 150000,
            "declared_video_count": 20, "themes": [],
        }])
        profile = build_sponsor_basin_profile(self.project["id"], self.nike["id"])
        self.assertEqual(profile["metrics"]["channels"], 2)
        self.assertEqual(profile["metrics"]["sponsored_contents"], 2)
        self.assertEqual(profile["metrics"]["observed_contents"], 4)
        self.assertTrue(profile["dominant_themes"])
        nike_creator = next(c for c in profile["channels"] if c["channel_id"] == "UCnike")
        self.assertEqual(nike_creator["subscribers"], 150000)

    def test_brands_by_niche_and_comparison(self):
        brands = database.brands_by_niche(self.project["id"], "Running")
        self.assertEqual({row["name"] for row in brands}, {"Nike", "Adidas"})
        left = build_sponsor_basin_profile(self.project["id"], self.nike["id"])
        right = build_sponsor_basin_profile(self.project["id"], self.adidas["id"])
        comparison = compare_sponsor_basins(left, right)
        self.assertEqual(comparison["overlap"]["channels"], 1)
        self.assertGreater(comparison["overlap"]["jaccard"], 0)

    def test_non_brand_is_rejected(self):
        person = database.create_entity(self.project["id"], "Mario", type="person")
        with self.assertRaises(ValueError):
            build_sponsor_basin_profile(self.project["id"], person["id"])

    def test_api_basin_compare_and_create_niche_use_local_data(self):
        request = SimpleNamespace(state=SimpleNamespace(user={"id": 1}))
        with patch("app.main.require_project_access"):
            basin = entity_sponsor_basin(self.nike["id"], request, days=3650)
            comparison = adv_compare_brands(
                request, self.nike["id"], self.adidas["id"],
                project_id=self.project["id"], days=3650,
            )
            niche = niche_from_sponsor(
                SponsorNicheCreate(
                    project_id=self.project["id"], entity_id=self.nike["id"],
                    name="Bacino Nike", days=3650,
                ),
                request,
            )
        self.assertEqual(basin["entity"]["name"], "Nike")
        self.assertEqual(comparison["overlap"]["channels"], 1)
        self.assertEqual(niche["kind"], "panorama")
        self.assertEqual(niche["channels"], 2)
        persisted = database.get_niche(niche["id"])
        self.assertEqual(persisted["definition"]["source"], "sponsor")


if __name__ == "__main__":
    unittest.main()
