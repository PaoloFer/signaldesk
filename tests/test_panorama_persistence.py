import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.jobs import _run_panorama_materialize
from tests.test_panorama import FakePoolConnector, _semantic_pool


def _channel(channel_id, platform="YouTube", score=0.7, theme="cucina"):
    return {
        "platform": platform,
        "channel_id": channel_id,
        "channel_title": f"Canale {channel_id}",
        "description": f"Profilo {theme}",
        "country": "IT",
        "language": "it",
        "subscribers": 120000,
        "declared_video_count": 50,
        "video_count": 2,
        "total_views": 3000,
        "avg_views": 1500,
        "engagement_rate": 0.05,
        "themes": [{"term": theme, "weight": 1.2, "depth": "P1"}],
        "score": score,
        "score_breakdown": {"theme": score},
        "circles": [theme],
    }


class PanoramaPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "panorama_persistence.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_legacy_niche_defaults_to_topic(self):
        niche = database.create_niche(1, "Legacy")
        self.assertEqual(niche["kind"], "topic")
        self.assertEqual(niche["definition"], {})

    def test_panorama_definition_round_trip(self):
        niche = database.create_niche(
            1, "Panorama", kind="panorama",
            definition={"membership_mode": "rule_based", "description": "cucina"},
        )
        self.assertEqual(niche["kind"], "panorama")
        self.assertEqual(niche["definition"]["membership_mode"], "rule_based")
        updated = database.update_niche(
            niche["id"], definition={"membership_mode": "curated"},
        )
        self.assertEqual(updated["definition"]["membership_mode"], "curated")

    def test_profiles_are_platform_and_project_scoped(self):
        project = database.create_project("Altro progetto")
        first = database.upsert_channel_profiles(1, [_channel("same", "YouTube")])
        second = database.upsert_channel_profiles(1, [_channel("same", "TikTok")])
        third = database.upsert_channel_profiles(project["id"], [_channel("same", "YouTube")])
        self.assertEqual(len(first), 1)
        self.assertNotEqual(first[0]["id"], second[0]["id"])
        self.assertNotEqual(first[0]["id"], third[0]["id"])
        self.assertEqual(len(database.list_channel_profiles(1)), 2)

    def test_membership_sync_is_idempotent_and_replaces_stale_members(self):
        niche = database.create_niche(1, "Persistente", kind="panorama")
        database.sync_niche_channels(
            1, niche["id"], [_channel("A"), _channel("B", score=0.4)],
        )
        database.sync_niche_channels(
            1, niche["id"], [_channel("A", score=0.9)],
        )
        members = database.list_niche_channels(niche["id"])
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["channel_id"], "A")
        self.assertEqual(members[0]["relevance_score"], 0.9)

        # Lo stesso DB viene riaperto come dopo un riavvio.
        database.initialize()
        after_restart = database.list_niche_channels(niche["id"])
        self.assertEqual(after_restart[0]["channel_id"], "A")

    def test_manual_creator_link_connects_cross_platform_profiles(self):
        profiles = database.upsert_channel_profiles(1, [
            _channel("creator-youtube", "YouTube"),
            _channel("creator-tiktok", "TikTok"),
        ])
        creator = database.create_creator_link(
            1, "Creator Uno", [profile["id"] for profile in profiles],
        )
        self.assertEqual(creator["display_name"], "Creator Uno")
        self.assertEqual({p["platform"] for p in creator["profiles"]}, {"YouTube", "TikTok"})

    def test_delete_niche_removes_memberships(self):
        niche = database.create_niche(1, "Delete", kind="panorama")
        database.sync_niche_channels(1, niche["id"], [_channel("A")])
        self.assertTrue(database.delete_niche(niche["id"]))
        self.assertEqual(database.list_niche_channels(niche["id"]), [])

    def test_materialize_job_persists_selected_members_and_contents(self):
        contents, metadata = _semantic_pool()
        niche = database.create_niche(
            1, "Materializzata", kind="panorama",
            description="ricette di cucina italiana",
            include_keywords=["ricetta", "musica"],
            definition={"membership_mode": "curated"},
        )
        with patch("app.jobs.YouTubeConnector", return_value=FakePoolConnector(contents, metadata)):
            with patch("app.jobs._api_key", return_value="fake-key"):
                result = _run_panorama_materialize(
                    1, 1, {
                        "niche_id": niche["id"],
                        "channel_ids": ["UCcucina"],
                        "membership_mode": "curated",
                    },
                )
        self.assertEqual(result["channels"], 1)
        members = database.list_niche_channels(niche["id"])
        self.assertEqual([member["channel_id"] for member in members], ["UCcucina"])
        linked = [
            item for item in database.all_contents(1)
            if item["channel_id"] == "UCcucina" and item["niche"] == "Materializzata"
        ]
        self.assertEqual(len(linked), 2)


if __name__ == "__main__":
    unittest.main()
