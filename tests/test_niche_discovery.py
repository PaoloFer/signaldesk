import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from app import database
from app.connectors import SocialConnector
from app.jobs import _run_niche_discovery, _run_niche_populate
from app.niche_discovery import expand_niche


class FakeConnector(SocialConnector):
    name = "Fake"
    platform = "Fake"

    def __init__(self, responses, comments=None):
        self._responses = responses
        self._comments = comments or []

    def is_configured(self) -> bool:
        return True

    def search(self, *, query=None, channel_id=None, days=30, max_results=50,
               region_code=None, relevance_language=None, now=None):
        if channel_id == "UCrun":
            return ["videoA", "videoB"]
        if query == "allenamento":
            return ["videoB", "videoC"]
        return []

    def fetch_details(self, content_ids, *, niche="", topic="", source_query="", acquired_at=""):
        items = [item for item in self._responses if item["external_id"] in content_ids]
        return items

    def fetch_comments(self, content_id, *, niche, topic="", max_comments=200, include_replies=False, content_title=None):
        comments = [c for c in self._comments if c["content_id"] == content_id]
        return ({"video_id": content_id, "title": content_title or "Video"}, comments[:max_comments])

    def refresh_metrics(self, content_ids):
        return []


def _video(external_id, channel_id, channel_title, views=5000):
    return {
        "external_id": external_id,
        "platform": "YouTube",
        "title": f"Video {external_id}",
        "description": "Desc",
        "tags": [],
        "channel_id": channel_id,
        "channel_title": channel_title,
        "published_at": "2026-09-01T10:00:00Z",
        "duration_seconds": 120,
        "views": views,
        "likes": 50,
        "comments": 5,
        "acquired_at": "2026-09-10T10:00:00Z",
    }


class FakeGeoConnector(SocialConnector):
    """Connettore finto con metadati di canale e panorama popolare."""

    name = "FakeGeo"
    platform = "Fake"

    def __init__(self, contents, channels, popular=None, resolutions=None):
        self._contents = contents
        self._channels = channels
        self._popular = popular or []
        self._resolutions = resolutions or {}
        self.search_calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def resolve_channel(self, channel_reference):
        return self._resolutions.get(channel_reference, channel_reference)

    def search(self, *, query=None, channel_id=None, days=30, max_results=50,
               region_code=None, relevance_language=None, now=None):
        self.search_calls.append({"query": query, "channel_id": channel_id})
        return [item["external_id"] for item in self._contents]

    def fetch_details(self, content_ids, *, niche="", topic="", source_query="", acquired_at=""):
        return [item for item in self._contents if item["external_id"] in content_ids]

    def fetch_channels(self, channel_ids):
        return {cid: self._channels[cid] for cid in channel_ids if cid in self._channels}

    def fetch_popular(self, *, region_code, max_results=50):
        return self._popular[:max_results]

    def fetch_comments(self, content_id, *, niche, topic="", max_comments=200, include_replies=False, content_title=None):
        return ({"video_id": content_id, "title": "Video"}, [])

    def refresh_metrics(self, content_ids):
        return []


class NicheGeoDiscoveryTest(unittest.TestCase):
    channels = {
        "UCit": {"title": "Creator IT", "country": "IT", "default_language": "it",
                 "subscribers": 900000, "video_count": 200},
        "UCus": {"title": "Creator US", "country": "US", "default_language": "en",
                 "subscribers": 5000000, "video_count": 500},
        "UCsmall": {"title": "Piccolo IT", "country": "IT", "default_language": "it",
                    "subscribers": 3000, "video_count": 20},
        "UCghost": {"title": "Senza dichiarazioni", "country": "", "default_language": "",
                    "subscribers": 150000, "video_count": 60},
    }

    def _niche(self, filters, with_seed=True):
        return {
            "name": "Influencer italiani",
            "description": "Panorama creator italiani",
            # Il seed fittizio attiva la raccolta: il connettore finto
            # restituisce tutti i contenuti per qualsiasi ricerca.
            "seed_channels": [{"channel_id": "UCseed", "channel_title": ""}] if with_seed else [],
            "seed_videos": [],
            "include_keywords": [],
            "exclude_keywords": [],
            "filters": filters,
        }

    def test_geo_boost_and_metadata_attached(self):
        contents = [_video("vIT", "UCit", "Creator IT"), _video("vUS", "UCus", "Creator US")]
        niche = self._niche({
            "region_code": "IT", "channel_country": "IT",
            "relevance_language": "it", "channel_language": "it",
        })
        results = expand_niche(niche, connector=FakeGeoConnector(contents, self.channels))
        by_id = {item["external_id"]: item for item in results}
        # Il canale italiano riceve il boost paese + lingua, l'altro no.
        self.assertGreater(by_id["vIT"]["relevance_score"], by_id["vUS"]["relevance_score"])
        self.assertEqual(by_id["vIT"]["channel_country"], "IT")
        self.assertEqual(by_id["vIT"]["channel_subscribers"], 900000)
        # Modalità non restrittiva: il canale US resta comunque osservabile.
        self.assertIn("vUS", by_id)

    def test_strict_geo_excludes_declared_mismatches_only(self):
        contents = [
            _video("vIT", "UCit", "Creator IT"),
            _video("vUS", "UCus", "Creator US"),
            _video("vGhost", "UCghost", "Senza dichiarazioni"),
        ]
        niche = self._niche({
            "channel_country": "IT", "channel_language": "it", "strict_geo": True,
        })
        ids = {item["external_id"] for item in expand_niche(niche, connector=FakeGeoConnector(contents, self.channels))}
        self.assertIn("vIT", ids)
        self.assertNotIn("vUS", ids)      # paese dichiarato diverso
        self.assertIn("vGhost", ids)      # nulla di dichiarato: nessuna esclusione

    def test_min_subscribers_excludes_small_channels(self):
        contents = [_video("vIT", "UCit", "Creator IT"), _video("vSmall", "UCsmall", "Piccolo IT")]
        niche = self._niche({"min_subscribers": 100000})
        ids = {item["external_id"] for item in expand_niche(niche, connector=FakeGeoConnector(contents, self.channels))}
        self.assertIn("vIT", ids)
        self.assertNotIn("vSmall", ids)

    def test_harvest_popular_marks_panorama_contents(self):
        contents = [_video("vPop", "UCit", "Creator IT"), _video("vOther", "UCus", "Creator US")]
        niche = self._niche({"region_code": "IT", "harvest_popular": True})
        connector = FakeGeoConnector(contents, self.channels, popular=["vPop"])
        results = expand_niche(niche, connector=connector)
        by_id = {item["external_id"]: item for item in results}
        self.assertEqual(by_id["vPop"]["matched_seed"], "popular")
        self.assertEqual(by_id["vPop"]["matched_value"], "IT")
        self.assertNotEqual(by_id["vOther"]["matched_seed"], "popular")

    def test_harvest_popular_alone_can_feed_a_niche(self):
        contents = [_video("vPop", "UCit", "Creator IT")]
        niche = self._niche({"region_code": "IT", "harvest_popular": True}, with_seed=False)
        connector = FakeGeoConnector(contents, self.channels, popular=["vPop"])
        ids = {item["external_id"] for item in expand_niche(niche, connector=connector)}
        self.assertEqual(ids, {"vPop"})

    def test_stats_report_sources_order_and_exclusions(self):
        contents = [
            _video("vPop", "UCit", "Creator IT"),
            _video("vIT", "UCit", "Creator IT"),
            _video("vUS", "UCus", "Creator US"),
        ]
        niche = self._niche({
            "region_code": "IT", "harvest_popular": True,
            "channel_country": "IT", "strict_geo": True,
        })
        niche["include_keywords"] = ["video"]
        stats: dict = {}
        expand_niche(niche, connector=FakeGeoConnector(contents, self.channels, popular=["vPop"]), stats=stats)
        # Le fonti mantengono l'ordine di raccolta anche con chiamate parallele.
        self.assertEqual([s["type"] for s in stats["sources"]], ["popular", "channel", "keyword"])
        self.assertEqual(stats["sources"][0], {"type": "popular", "value": "IT", "found": 1})
        self.assertEqual(stats["excluded_geo"], 1)   # vUS: paese dichiarato diverso
        self.assertEqual(stats["channels_checked"], 2)
        self.assertEqual(stats["candidates"], 3)
        self.assertEqual(stats["kept"], 2)

    def test_channel_handle_is_resolved_before_searching(self):
        contents = [_video("vIT", "UCmarcello", "Marcello Ascani")]
        niche = self._niche({})
        niche["seed_channels"] = [{"channel_id": "@marcelloascani", "channel_title": ""}]
        connector = FakeGeoConnector(
            contents, self.channels, resolutions={"@marcelloascani": "UCmarcello"},
        )
        stats: dict = {}
        results = expand_niche(niche, connector=connector, stats=stats)
        # La ricerca usa l'ID risolto, non l'handle: nessun errore 400.
        self.assertEqual(connector.search_calls[0]["channel_id"], "UCmarcello")
        self.assertEqual(stats["unresolved_channels"], [])
        self.assertEqual([c["external_id"] for c in results], ["vIT"])
        # Il contenuto del canale risolto ottiene il match di seed canale.
        self.assertEqual(results[0]["matched_seed"], "channel")

    def test_unresolvable_channel_is_skipped_and_reported(self):
        niche = self._niche({})
        niche["seed_channels"] = [{"channel_id": "Nome Libero Con Spazi", "channel_title": ""}]
        connector = FakeGeoConnector([], self.channels, resolutions={"Nome Libero Con Spazi": None})
        stats: dict = {}
        results = expand_niche(niche, connector=connector, stats=stats)
        # Nessuna ricerca lanciata con un riferimento invalido: quota risparmiata.
        self.assertEqual(connector.search_calls, [])
        self.assertEqual(results, [])
        self.assertEqual(stats["unresolved_channels"], ["Nome Libero Con Spazi"])

    def test_invalid_video_seed_is_reported_not_silently_dropped(self):
        niche = self._niche({}, with_seed=False)
        niche["seed_videos"] = [
            {"video_id": "marcelloascani", "title": ""},
            {"video_id": "https://youtu.be/5HaN675MGkE", "title": ""},
        ]
        contents = [_video("5HaN675MGkE", "UCit", "Creator IT")]
        stats: dict = {}
        results = expand_niche(niche, connector=FakeGeoConnector(contents, self.channels), stats=stats)
        self.assertEqual(stats["invalid_video_seeds"], ["marcelloascani"])
        self.assertEqual([c["external_id"] for c in results], ["5HaN675MGkE"])

    def test_search_budget_skips_sources_beyond_ten(self):
        contents = [_video("vIT", "UCit", "Creator IT")]
        niche = self._niche({})
        niche["include_keywords"] = [f"kw{i}" for i in range(12)]
        stats: dict = {}
        expand_niche(niche, connector=FakeGeoConnector(contents, self.channels), stats=stats)
        # Budget di 10 ricerche: 1 canale seed + 9 keyword eseguite, 3 keyword saltate.
        self.assertEqual(len(stats["sources"]), 10)
        self.assertEqual(stats["sources"][0]["type"], "channel")
        self.assertEqual(len(stats["sources_skipped"]), 3)
        self.assertTrue(all(s["type"] == "keyword" for s in stats["sources_skipped"]))


class NicheDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "niche_discovery.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    @staticmethod
    def _fake_request(url: str) -> dict:
        if "/search?" in url:
            if "channelId=UCrun" in url:
                return {"items": [{"id": {"videoId": "videoA"}}, {"id": {"videoId": "videoB"}}]}
            if "q=allenamento" in url:
                return {"items": [{"id": {"videoId": "videoB"}}, {"id": {"videoId": "videoC"}}]}
            return {"items": []}
        if "/videos?" in url:
            return {
                "items": [
                    {
                        "id": "videoA",
                        "snippet": {
                            "title": "Allenamento principianti",
                            "description": "Guida",
                            "tags": ["corsa", "allenamento"],
                            "channelId": "UCrun",
                            "channelTitle": "RunLab",
                            "publishedAt": "2026-09-01T10:00:00Z",
                        },
                        "statistics": {"viewCount": "5000", "likeCount": "200", "commentCount": "30"},
                        "contentDetails": {"duration": "PT8M"},
                    },
                    {
                        "id": "videoB",
                        "snippet": {
                            "title": "Maratona professionisti",
                            "description": "Elite",
                            "tags": ["maratona"],
                            "channelId": "UCrun",
                            "channelTitle": "RunLab",
                            "publishedAt": "2026-09-02T10:00:00Z",
                        },
                        "statistics": {"viewCount": "3000", "likeCount": "100", "commentCount": "10"},
                        "contentDetails": {"duration": "PT15M"},
                    },
                    {
                        "id": "videoC",
                        "snippet": {
                            "title": "Scarpe per allenamento",
                            "description": "Recensione",
                            "tags": ["scarpe", "allenamento"],
                            "channelId": "UCother",
                            "channelTitle": "Other",
                            "publishedAt": "2026-09-03T10:00:00Z",
                        },
                        "statistics": {"viewCount": "800", "likeCount": "50", "commentCount": "5"},
                        "contentDetails": {"duration": "PT5M"},
                    },
                ]
            }
        return {}

    def test_expand_filters_excludes_and_scores(self):
        responses = [
            {
                "external_id": "videoA",
                "platform": "YouTube",
                "title": "Allenamento principianti",
                "description": "Guida",
                "tags": ["corsa", "allenamento"],
                "channel_id": "UCrun",
                "channel_title": "RunLab",
                "published_at": "2026-09-01T10:00:00Z",
                "duration_seconds": 480,
                "views": 5000,
                "likes": 200,
                "comments": 30,
                "acquired_at": "2026-09-10T10:00:00Z",
            },
            {
                "external_id": "videoB",
                "platform": "YouTube",
                "title": "Maratona professionisti",
                "description": "Elite",
                "tags": ["maratona"],
                "channel_id": "UCrun",
                "channel_title": "RunLab",
                "published_at": "2026-09-02T10:00:00Z",
                "duration_seconds": 900,
                "views": 3000,
                "likes": 100,
                "comments": 10,
                "acquired_at": "2026-09-10T10:00:00Z",
            },
            {
                "external_id": "videoC",
                "platform": "YouTube",
                "title": "Scarpe per allenamento",
                "description": "Recensione",
                "tags": ["scarpe", "allenamento"],
                "channel_id": "UCother",
                "channel_title": "Other",
                "published_at": "2026-09-03T10:00:00Z",
                "duration_seconds": 300,
                "views": 800,
                "likes": 50,
                "comments": 5,
                "acquired_at": "2026-09-10T10:00:00Z",
            },
        ]
        niche = {
            "name": "Corsa amatoriale",
            "description": "",
            "seed_channels": [{"channel_id": "UCrun", "channel_title": "RunLab"}],
            "seed_videos": [],
            "include_keywords": ["allenamento"],
            "exclude_keywords": ["maratona"],
            "filters": {"min_views": 1000, "max_results": 10},
        }
        contents = expand_niche(niche, connector=FakeConnector(responses))
        ids = {c["external_id"] for c in contents}
        self.assertIn("videoA", ids)
        self.assertNotIn("videoB", ids)  # escluso per keyword "maratona"
        self.assertNotIn("videoC", ids)  # escluso per min_views

        video_a = next(c for c in contents if c["external_id"] == "videoA")
        self.assertGreater(video_a["relevance_score"], 1.0)  # channel + keyword
        self.assertEqual(video_a["matched_seed"], "channel")

    def test_upsert_contents_for_niche_links_project_and_niche(self):
        niche = database.create_niche(project_id=1, name="Test Niche")
        contents = [
            {
                "external_id": "demo-niche-1",
                "platform": "YouTube",
                "title": "Titolo",
                "description": "Desc",
                "tags": ["tag"],
                "channel_id": "UCx",
                "channel_title": "Canale",
                "published_at": "2026-09-01T10:00:00Z",
                "duration_seconds": 120,
                "views": 1000,
                "likes": 50,
                "comments": 5,
                "acquired_at": "2026-09-10T10:00:00Z",
                "relevance_score": 1.5,
                "matched_seed": "channel",
                "matched_value": "UCx",
            }
        ]
        result = database.upsert_contents_for_niche(1, niche["id"], niche["name"], contents)
        self.assertEqual(result["stored"], 1)
        self.assertEqual(result["project_linked"], 1)

        project_contents = database.all_contents(1)
        self.assertTrue(any(c["external_id"] == "demo-niche-1" and c["niche"] == "Test Niche" for c in project_contents))

        niche_entities = database.list_niche_entities(1)
        self.assertEqual(len(niche_entities), 1)

    def test_job_auto_fetches_comments_and_analyzes(self):
        niche = database.create_niche(
            project_id=1, name="Auto comments",
            seed_channels=[{"channel_id": "UCrun", "channel_title": "RunLab"}],
            include_keywords=["allenamento"],
            filters={
                "auto_fetch_comments": True,
                "max_comment_videos": 2,
                "comments_per_video": 5,
                "include_replies": False,
            },
        )
        responses = [
            {
                "external_id": "videoA",
                "platform": "YouTube",
                "title": "Video A",
                "description": "Desc",
                "tags": ["tag"],
                "channel_id": "UCrun",
                "channel_title": "RunLab",
                "published_at": "2026-09-01T10:00:00Z",
                "duration_seconds": 120,
                "views": 5000,
                "likes": 50,
                "comments": 5,
                "acquired_at": "2026-09-10T10:00:00Z",
                "relevance_score": 1.5,
                "matched_seed": "channel",
                "matched_value": "UCrun",
            },
        ]
        comments = [
            {
                "external_id": "c1",
                "content_id": "videoA",
                "content_title": "Video A",
                "author_hash": "yt-abc",
                "text": "Ottimo video, grazie!",
                "published_at": "2026-09-10T10:00:00Z",
                "platform": "YouTube",
                "niche": "Auto comments",
                "topic": "",
            }
        ]
        with patch("app.jobs.YouTubeConnector", return_value=FakeConnector(responses, comments)):
            with patch("app.jobs._api_key", return_value="fake-key"):
                result = _run_niche_discovery(1, 1, {"niche_id": niche["id"]})

        self.assertEqual(result["stored"], 1)
        self.assertEqual(result["comments_imported"], 1)
        self.assertGreaterEqual(result["comments_analyzed"], 1)

        # Verifica che il commento sia stato salvato nel progetto
        project_comments = database.all_comments(1)
        self.assertTrue(any(c["external_id"] == "c1" for c in project_comments))

    def test_populate_saves_only_selected_contents(self):
        project = database.create_project(name="Populate test")
        niche = database.create_niche(
            project_id=project["id"], name="Populate niche",
            seed_channels=[{"channel_id": "UCrun", "channel_title": "RunLab"}],
            include_keywords=["allenamento"],
        )
        responses = [
            {
                "external_id": "videoA",
                "platform": "YouTube",
                "title": "Video A",
                "description": "Desc",
                "tags": ["tag"],
                "channel_id": "UCrun",
                "channel_title": "RunLab",
                "published_at": "2026-09-01T10:00:00Z",
                "duration_seconds": 120,
                "views": 5000,
                "likes": 50,
                "comments": 5,
                "acquired_at": "2026-09-10T10:00:00Z",
                "relevance_score": 1.5,
                "matched_seed": "channel",
                "matched_value": "UCrun",
            },
            {
                "external_id": "videoB",
                "platform": "YouTube",
                "title": "Video B",
                "description": "Desc",
                "tags": ["tag"],
                "channel_id": "UCrun",
                "channel_title": "RunLab",
                "published_at": "2026-09-01T10:00:00Z",
                "duration_seconds": 120,
                "views": 3000,
                "likes": 30,
                "comments": 3,
                "acquired_at": "2026-09-10T10:00:00Z",
                "relevance_score": 1.0,
                "matched_seed": "channel",
                "matched_value": "UCrun",
            },
        ]
        with patch("app.jobs.YouTubeConnector", return_value=FakeConnector(responses)):
            with patch("app.jobs._api_key", return_value="fake-key"):
                result = _run_niche_populate(1, project["id"], {
                    "niche_id": niche["id"],
                    "content_ids": ["videoA"],
                    "auto_fetch_comments": False,
                })

        self.assertEqual(result["stored"], 1)
        self.assertEqual(result["project_linked"], 1)
        project_contents = database.all_contents(project["id"])
        self.assertEqual(len(project_contents), 1)
        self.assertEqual(project_contents[0]["external_id"], "videoA")


if __name__ == "__main__":
    unittest.main()
