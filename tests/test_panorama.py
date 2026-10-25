"""Test del pool canali (N1) e della pipeline panorama (N1–N4)."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import database
from app.auth import register
from app.connectors import SocialConnector
from app.main import NichePreviewRequest, preview_niche
from app.niche_discovery import aggregate_channel_pool, expand_niche_channels
from app.panorama import build_panorama


def _video(external_id, channel_id, channel_title, title=None, views=5000,
           likes=50, comments=10, tags=None, description="Desc"):
    return {
        "external_id": external_id,
        "platform": "YouTube",
        "title": title or f"Video {external_id}",
        "description": description,
        "tags": tags or [],
        "channel_id": channel_id,
        "channel_title": channel_title,
        "published_at": "2026-09-01T10:00:00Z",
        "duration_seconds": 120,
        "views": views,
        "likes": likes,
        "comments": comments,
        "acquired_at": "2026-09-10T10:00:00Z",
    }


class FakePoolConnector(SocialConnector):
    """Connettore finto con metadati canale e seconda ondata configurabile."""

    name = "FakePool"
    platform = "Fake"

    def __init__(self, contents, channels, popular=None, wave=None):
        self._contents = contents
        self._channels = channels
        self._popular = popular or []
        # Seconda ondata: {channel_id: [contenuti extra]} servita solo
        # quando la search arriva con quel channel_id esplicito.
        self._wave = wave or {}
        self.search_calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def resolve_channel(self, channel_reference):
        return channel_reference

    def search(self, *, query=None, channel_id=None, days=30, max_results=50,
               region_code=None, relevance_language=None, now=None):
        self.search_calls.append({"query": query, "channel_id": channel_id})
        if channel_id and channel_id in self._wave:
            return [item["external_id"] for item in self._wave[channel_id]]
        return [item["external_id"] for item in self._contents]

    def fetch_details(self, content_ids, *, niche="", topic="", source_query="", acquired_at=""):
        available = list(self._contents)
        for wave_contents in self._wave.values():
            available.extend(wave_contents)
        return [item for item in available if item["external_id"] in content_ids]

    def fetch_channels(self, channel_ids):
        return {cid: self._channels[cid] for cid in channel_ids if cid in self._channels}

    def fetch_popular(self, *, region_code, max_results=50):
        return self._popular[:max_results]

    def fetch_comments(self, content_id, *, niche, topic="", max_comments=200,
                       include_replies=False, content_title=None):
        return ({"video_id": content_id, "title": "Video"}, [])

    def refresh_metrics(self, content_ids):
        return []


def _niche(filters=None, keywords=None, seed_channels=None, description=""):
    return {
        "name": "Panorama test",
        "description": description,
        "seed_channels": seed_channels or [],
        "seed_videos": [],
        "include_keywords": keywords or [],
        "exclude_keywords": [],
        "filters": filters or {},
    }


class AggregateChannelPoolTest(unittest.TestCase):
    def test_aggregates_metrics_and_attaches_meta(self):
        contents = [
            {**_video("v1", "UCa", "Canale A", views=1000, likes=40, comments=10),
             "relevance_score": 1.0, "matched_seed": "channel", "matched_value": "UCa"},
            {**_video("v2", "UCa", "Canale A", views=3000, likes=110, comments=40),
             "relevance_score": 0.5, "matched_seed": "keyword", "matched_value": "x"},
            {**_video("v3", "UCb", "Canale B", views=9000),
             "relevance_score": 0.05, "matched_seed": "keyword", "matched_value": ""},
        ]
        meta = {
            "UCa": {"title": "Canale A", "country": "IT", "default_language": "it",
                    "subscribers": 120000, "video_count": 40, "custom_url": "@canalea",
                    "description": "Descrizione del canale A"},
        }
        pool = aggregate_channel_pool(contents, meta)
        self.assertEqual(len(pool), 2)
        # Ordinati per views osservate totali.
        self.assertEqual(pool[0]["channel_id"], "UCb")
        canale_a = pool[1]
        self.assertEqual(canale_a["video_count"], 2)
        self.assertEqual(canale_a["total_views"], 4000)
        self.assertEqual(canale_a["avg_views"], 2000)
        self.assertEqual(canale_a["engagement_rate"], round(200 / 4000, 5))
        self.assertEqual(canale_a["country"], "IT")
        self.assertEqual(canale_a["subscribers"], 120000)
        self.assertEqual(canale_a["description"], "Descrizione del canale A")
        # I video sono evidenza, ordinati per views decrescenti.
        self.assertEqual([v["external_id"] for v in canale_a["videos"]], ["v2", "v1"])
        # Il match migliore del canale è quello del video con score più alto.
        self.assertEqual(canale_a["matched_seed"], "channel")
        self.assertEqual(canale_a["relevance_score"], 1.0)


class ExpandNicheChannelsTest(unittest.TestCase):
    channels = {
        "UCa": {"title": "Canale A", "country": "IT", "default_language": "it",
                "subscribers": 120000, "video_count": 40, "custom_url": "@a",
                "description": "Canale A di cucina italiana"},
        "UCb": {"title": "Canale B", "country": "IT", "default_language": "it",
                "subscribers": 80000, "video_count": 30, "custom_url": "@b",
                "description": "Canale B di musica dal vivo"},
    }

    def test_pool_channels_with_evidence_and_meta(self):
        """N1: la preview a livello canale restituisce canali, non video."""
        contents = [
            _video("v1", "UCa", "Canale A", views=1000),
            _video("v2", "UCa", "Canale A", views=2000),
            _video("v3", "UCb", "Canale B", views=9000),
        ]
        niche = _niche(seed_channels=[{"channel_id": "UCa", "channel_title": ""}])
        stats: dict = {}
        pool = expand_niche_channels(niche, connector=FakePoolConnector(contents, self.channels), stats=stats)
        self.assertEqual({c["channel_id"] for c in pool}, {"UCa", "UCb"})
        canale_a = next(c for c in pool if c["channel_id"] == "UCa")
        self.assertEqual(canale_a["video_count"], 2)
        self.assertEqual(canale_a["candidate_level"], "matched")
        self.assertEqual(canale_a["description"], "Canale A di cucina italiana")
        self.assertEqual(stats["channels"], 2)
        self.assertEqual(stats["channels_checked"], 2)

    def test_include_top_channels_promotes_observed_channels(self):
        """I canali più visti diventano candidati di primo livello."""
        contents = [
            _video("v1", "UCa", "Canale A", views=500),
            _video("v2", "UCb", "Canale B", views=90000),
        ]
        niche = _niche(
            filters={"include_top_channels": True},
            seed_channels=[{"channel_id": "UCa", "channel_title": ""}],
        )
        stats: dict = {}
        pool = expand_niche_channels(niche, connector=FakePoolConnector(contents, self.channels), stats=stats)
        by_id = {c["channel_id"]: c for c in pool}
        # UCb non ha match (score 0.05) ma è il più visto: promosso.
        self.assertEqual(by_id["UCb"]["candidate_level"], "top_channels")
        self.assertTrue(by_id["UCb"]["promoted"])
        # UCa ha il match di seed: resta "matched", non conta come promosso.
        self.assertEqual(by_id["UCa"]["candidate_level"], "matched")
        self.assertEqual(stats["channels_promoted"], 1)

    def test_second_wave_is_opt_in_and_reports_budget(self):
        """La seconda ondata raccoglie solo se richiesta, budget visibile."""
        contents = [
            _video("v1", "UCa", "Canale A", views=9000),
            _video("v2", "UCb", "Canale B", views=1000),
        ]
        wave = {
            "UCa": [
                _video("w1", "UCa", "Canale A", title="Video recente wave 1", views=300),
                _video("w2", "UCa", "Canale A", title="Video recente wave 2", views=200),
            ],
        }
        connector = FakePoolConnector(contents, self.channels, wave=wave)
        niche = _niche(keywords=["video"])

        # Default: nessuna seconda ondata, nessuna search extra.
        pool = expand_niche_channels(niche, connector=connector, stats={})
        self.assertEqual(len(connector.search_calls), 1)
        canale_a = next(c for c in pool if c["channel_id"] == "UCa")
        self.assertEqual(canale_a["video_count"], 1)

        # Opt-in: 1 canale × 100 unità dichiarate, video recenti aggiunti.
        wave_connector = FakePoolConnector(contents, self.channels, wave=wave)
        niche_wave = _niche(filters={"second_wave_top_k": 1}, keywords=["video"])
        stats: dict = {}
        pool = expand_niche_channels(niche_wave, connector=wave_connector, stats=stats)
        self.assertEqual(len(wave_connector.search_calls), 2)
        self.assertEqual(stats["second_wave"]["channels"], 1)
        self.assertEqual(stats["second_wave"]["estimated_units"], 100)
        self.assertEqual(stats["second_wave"]["videos_added"], 2)
        canale_a = next(c for c in pool if c["channel_id"] == "UCa")
        wave_videos = [v for v in canale_a["videos"] if v["matched_seed"] == "second_wave"]
        self.assertEqual(len(wave_videos), 2)


def _semantic_pool():
    """Pool coerente per la pipeline completa: cucina vs musica."""
    contents = [
        _video("c1", "UCcucina", "Fornello", title="Pasta carbonara ricetta",
               tags=["cucina", "pasta", "italia"], description="Ricetta di cucina romana",
               views=8000),
        _video("c2", "UCcucina", "Fornello", title="Ricetta tiramisù dolci",
               tags=["cucina", "dolci", "italia"], description="Ricetta dolce di cucina",
               views=6000),
        _video("m1", "UCmusica", "Palco", title="Maneskin live sanremo",
               tags=["musica", "live", "italia"], description="Concerto di musica dal vivo",
               views=50000),
        _video("m2", "UCmusica", "Palco", title="Concerto rock musica live",
               tags=["musica", "concerto", "italia"], description="Serata di musica rock",
               views=30000),
    ]
    channels = {
        "UCcucina": {"title": "Fornello", "country": "IT", "default_language": "it",
                     "subscribers": 90000, "video_count": 50, "custom_url": "@fornello",
                     "description": "Ricette di cucina italiana"},
        "UCmusica": {"title": "Palco", "country": "IT", "default_language": "it",
                     "subscribers": 500000, "video_count": 120, "custom_url": "@palco",
                     "description": "Musica dal vivo e concerti"},
    }
    return contents, channels


class BuildPanoramaTest(unittest.TestCase):
    def test_channels_have_themes_scores_and_circles(self):
        """N2–N4: temi, score composito con breakdown, cerchi emergenti."""
        contents, channels = _semantic_pool()
        niche = _niche(keywords=["ricetta", "musica"],
                       description="ricette di cucina italiana")
        stats: dict = {}
        panorama = build_panorama(niche, connector=FakePoolConnector(contents, channels), stats=stats)

        self.assertEqual(len(panorama["channels"]), 2)
        for channel in panorama["channels"]:
            self.assertIn("score", channel)
            self.assertEqual(
                set(channel["score_breakdown"]),
                {"theme", "geo", "size", "popularity", "engagement", "velocity"},
            )
            self.assertIn("shared_terms", channel)
            self.assertIn("themes", channel)
            self.assertIn("circles", channel)
            self.assertNotIn("vector", channel)  # il vettore non esce
        # La descrizione semantica premia il canale di cucina.
        first = panorama["channels"][0]
        self.assertEqual(first["channel_id"], "UCcucina")
        self.assertGreater(first["score_breakdown"]["theme"], 0.0)
        shared = {t["term"] for t in first["shared_terms"]}
        self.assertTrue(shared & {"cucina", "ricetta"})
        # Temi estratti con profondità di evidenza.
        theme_terms = {t["term"] for t in first["themes"]}
        self.assertTrue(theme_terms & {"cucina", "ricetta"})
        self.assertTrue(all(t["depth"] in {"P1", "P2", "P3"} for t in first["themes"]))
        # Cerchi emergenti con label leggibili.
        self.assertTrue(panorama["circles"])
        for circle in panorama["circles"]:
            self.assertIn("canali)", circle["label"])
            self.assertTrue(circle["channel_count"] >= 1)
        # Temi del pool presenti.
        self.assertTrue(panorama["pool_themes"])
        self.assertEqual(stats["channels"], 2)

    def test_empty_pool_returns_empty_panorama(self):
        niche = _niche()
        panorama = build_panorama(niche, connector=FakePoolConnector([], {}))
        self.assertEqual(panorama, {"channels": [], "circles": [], "pool_themes": []})


class PanoramaPreviewApiTest(unittest.TestCase):
    """La preview in modalità ``channels`` restituisce il panorama (N1)."""

    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "panorama_api.db"
        database.initialize()
        user, _ = register("panorama@example.com", "password-molto-sicura", "Panorama Org")
        self.request = SimpleNamespace(state=SimpleNamespace(user={"id": user["id"]}))
        self.niche = database.create_niche(
            project_id=1, name="Panorama niche",
            description="ricette di cucina italiana",
            include_keywords=["ricetta", "musica"],
        )

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_preview_channels_mode_returns_panorama(self):
        contents, channels = _semantic_pool()
        connector = FakePoolConnector(contents, channels)
        with patch("app.main.YouTubeConnector", return_value=connector):
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
                payload = preview_niche(
                    self.niche["id"],
                    NichePreviewRequest(filters={"max_results": 10}, mode="channels"),
                    self.request,
                )
        self.assertEqual(payload["mode"], "channels")
        self.assertEqual(payload["total"], 2)
        self.assertIn("circles", payload)
        self.assertIn("pool_themes", payload)
        first = payload["channels"][0]
        self.assertEqual(first["channel_id"], "UCcucina")
        self.assertIn("score_breakdown", first)
        self.assertIn("shared_terms", first)
        # Diagnostica per fonte e quota visibile come nella preview video.
        self.assertIn("sources", payload["stats"])

    def test_preview_default_mode_stays_videos(self):
        contents, channels = _semantic_pool()
        connector = FakePoolConnector(contents, channels)
        with patch("app.main.YouTubeConnector", return_value=connector):
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake-key"}):
                payload = preview_niche(
                    self.niche["id"],
                    NichePreviewRequest(filters={"max_results": 10}),
                    self.request,
                )
        self.assertEqual(payload["mode"], "videos")
        self.assertIn("items", payload)
        self.assertNotIn("channels", payload)


if __name__ == "__main__":
    unittest.main()
