import copy
import json
import unittest
from unittest.mock import patch

from app.channel_profiling import compute_channel_profiles, score_channels
from app.panorama import build_panorama
from app.semantic_engine import (
    EmbeddingEngine,
    OpenAICompatibleCircleLabeler,
    TfidfEngine,
)


def _channels():
    return [
        {
            "channel_id": "food",
            "channel_title": "Cucina",
            "description": "Ricette italiane facili",
            "videos": [
                {"title": "Pasta e dolci", "tags": ["cucina"], "description": "Ricetta"},
                {"title": "Cucina romana", "tags": ["pasta"], "description": "Carbonara"},
            ],
            "avg_views": 10,
        },
        {
            "channel_id": "music",
            "channel_title": "Musica",
            "description": "Concerti rock dal vivo",
            "videos": [
                {"title": "Band live", "tags": ["musica"], "description": "Concerto"},
                {"title": "Festival rock", "tags": ["live"], "description": "Musica"},
            ],
            "avg_views": 10,
        },
    ]


class FakeEncoder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [
            [1.0, 0.0] if any(word in text.lower() for word in ("musica", "rock", "live"))
            else [0.0, 1.0]
            for text in texts
        ]


class ArrayLikeVector(list):
    def __bool__(self):
        raise ValueError("array truth value is ambiguous")


class SemanticEngineTest(unittest.TestCase):
    def test_tfidf_engine_preserves_historical_score_output(self):
        channels = _channels()
        profiles, idf, n_docs = compute_channel_profiles(channels)
        vectors = {profile["channel_id"]: profile["vector"] for profile in profiles}
        for channel in channels:
            channel["vector"] = vectors[channel["channel_id"]]

        expected = score_channels(channels, query_text="ricette pasta", idf=idf, n_docs=n_docs)
        matches = TfidfEngine().theme_matches(
            "ricette pasta", channels, depth="P2", idf=idf, n_docs=n_docs
        )
        actual = score_channels(
            channels,
            query_text="ricette pasta",
            idf=idf,
            n_docs=n_docs,
            theme_matches=matches,
        )
        self.assertEqual(actual, expected)

    def test_embedding_engine_uses_injected_encoder_and_keeps_explanations(self):
        channels = _channels()
        engine = EmbeddingEngine("never-downloaded", encoder=FakeEncoder())
        profiles, idf, n_docs = engine.profiles(channels)
        vectors = {profile["channel_id"]: profile["vector"] for profile in profiles}
        for channel in channels:
            channel["vector"] = vectors[channel["channel_id"]]

        matches = engine.theme_matches(
            "musica dal vivo", channels, depth="P2", idf=idf, n_docs=n_docs
        )
        tfidf_matches = TfidfEngine().theme_matches(
            "musica dal vivo", channels, depth="P2", idf=idf, n_docs=n_docs
        )
        self.assertEqual(len(engine.encoder.calls), 1)
        self.assertGreater(matches["music"]["score"], matches["food"]["score"])
        self.assertGreater(
            tfidf_matches["music"]["score"], tfidf_matches["food"]["score"]
        )
        self.assertTrue(matches["music"]["shared_terms"])

    def test_embedding_vectors_do_not_require_boolean_coercion(self):
        class ArrayEncoder:
            def encode(self, texts):
                return [ArrayLikeVector([1.0, 0.0]) for _ in texts]

        channels = _channels()
        engine = EmbeddingEngine("never-downloaded", encoder=ArrayEncoder())
        profiles, idf, n_docs = engine.profiles(channels)
        for channel, profile in zip(channels, profiles):
            channel["vector"] = profile["vector"]
        matches = engine.theme_matches(
            "musica", channels, depth="P2", idf=idf, n_docs=n_docs
        )
        self.assertEqual(matches["music"]["score"], 1.0)

    def test_panorama_falls_back_when_embedding_encoder_fails(self):
        class BrokenEncoder:
            def encode(self, texts):
                raise RuntimeError("model unavailable")

        niche = {"name": "Test", "description": "ricette pasta", "filters": {}}
        baseline_pool = _channels()
        broken_pool = copy.deepcopy(baseline_pool)
        with patch("app.panorama.expand_niche_channels", return_value=baseline_pool):
            expected = build_panorama(niche, object(), semantic_engine=TfidfEngine())
        with patch("app.panorama.expand_niche_channels", return_value=broken_pool):
            actual = build_panorama(
                niche,
                object(),
                semantic_engine=EmbeddingEngine("unused", encoder=BrokenEncoder()),
            )
        self.assertEqual(actual, expected)


class CircleLabelerTest(unittest.TestCase):
    def test_openai_compatible_label_is_cached(self):
        calls = []

        def fake_post(url, headers, body, timeout):
            calls.append((url, headers, json.loads(body), timeout))
            return {"choices": [{"message": {"content": "Musica rock italiana"}}]}

        labeler = OpenAICompatibleCircleLabeler(
            "https://llm.example/v1/chat/completions",
            "secret",
            "test-model",
            http_post=fake_post,
        )
        circles = [{"label_terms": ["maneskin", "live"], "channel_count": 2, "label": "fallback"}]
        labeler.apply(circles)
        labeler.apply(circles)

        self.assertEqual(circles[0]["label"], "Musica rock italiana (2 canali)")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0][2]["temperature"], 0)

    def test_http_error_keeps_deterministic_label(self):
        def failing_post(*args):
            raise OSError("offline")

        labeler = OpenAICompatibleCircleLabeler(
            "https://llm.example/v1/chat/completions",
            "",
            "test-model",
            http_post=failing_post,
        )
        circles = [{"label_terms": ["pasta", "ricette"], "channel_count": 1,
                    "label": "pasta · ricette (1 canali)"}]
        labeler.apply(circles)
        self.assertEqual(circles[0]["label"], "pasta · ricette (1 canali)")


if __name__ == "__main__":
    unittest.main()
