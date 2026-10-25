"""Motori semantici opzionali per il panorama delle nicchie (N8)."""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any, ClassVar
from urllib.request import Request, urlopen

from app.channel_profiling import (
    DEPTHS,
    compute_channel_profiles,
    cosine,
    text_vector,
)


ThemeMatch = dict[str, Any]


class SemanticEngine(ABC):
    """Interfaccia uniforme per profili e match nicchia-canale."""

    name = "base"

    def profiles(
        self, channels: list[dict[str, Any]], *, depth: str = "P2"
    ) -> tuple[list[dict[str, Any]], dict[str, float], int]:
        # I profili TF-IDF restano la base spiegabile per temi e cerchi.
        return compute_channel_profiles(channels, depth=depth)

    @abstractmethod
    def theme_matches(
        self,
        query_text: str,
        channels: list[dict[str, Any]],
        *,
        depth: str,
        idf: dict[str, float],
        n_docs: int,
    ) -> dict[str, ThemeMatch]:
        """Restituisce score 0-1 e feature esplicative per channel_id."""


def _tfidf_matches(
    query_text: str,
    channels: list[dict[str, Any]],
    idf: dict[str, float],
    n_docs: int,
) -> dict[str, ThemeMatch]:
    query = text_vector(query_text, idf, n_docs) if query_text.strip() else {}
    matches: dict[str, ThemeMatch] = {}
    for channel in channels:
        vector = channel.get("vector") or {}
        shared = [
            {
                "term": term,
                "weight": round(vector[term], 4),
                "query_weight": round(query[term], 4),
            }
            for term in query
            if term in vector
        ]
        shared.sort(key=lambda item: -(item["weight"] * item["query_weight"]))
        matches[channel.get("channel_id", "")] = {
            "score": cosine(query, vector) if query else 0.0,
            "shared_terms": shared[:15],
        }
    return matches


class TfidfEngine(SemanticEngine):
    """Motore predefinito, identico alla pipeline TF-IDF storica."""

    name = "tfidf"

    def theme_matches(
        self,
        query_text: str,
        channels: list[dict[str, Any]],
        *,
        depth: str,
        idf: dict[str, float],
        n_docs: int,
    ) -> dict[str, ThemeMatch]:
        del depth
        return _tfidf_matches(query_text, channels, idf, n_docs)


def _channel_text(channel: dict[str, Any], depth: str) -> str:
    depth = depth if depth in DEPTHS else "P2"
    parts = [channel.get("description", "") or ""]
    for video in channel.get("videos", []):
        parts.append(video.get("title", "") or "")
        parts.extend(str(tag) for tag in (video.get("tags") or []))
        if depth in ("P2", "P3"):
            parts.append((video.get("description", "") or "")[:500])
        if depth == "P3":
            parts.append(video.get("comments_text", "") or "")
    return "\n".join(part for part in parts if part)


def _dense_cosine(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) == 0 or len(second) == 0 or len(first) != len(second):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(first, second))
    norm_a = math.sqrt(sum(float(value) ** 2 for value in first))
    norm_b = math.sqrt(sum(float(value) ** 2 for value in second))
    if not norm_a or not norm_b:
        return 0.0
    # Negative cosine is not useful as a relevance component.
    return max(0.0, min(dot / (norm_a * norm_b), 1.0))


class EmbeddingEngine(SemanticEngine):
    """Sentence-transformers multilingua, caricato solo al primo match."""

    name = "embeddings"

    def __init__(self, model_name: str, encoder: Any | None = None) -> None:
        self.model_name = model_name
        self._encoder = encoder

    @property
    def encoder(self) -> Any:
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def theme_matches(
        self,
        query_text: str,
        channels: list[dict[str, Any]],
        *,
        depth: str,
        idf: dict[str, float],
        n_docs: int,
    ) -> dict[str, ThemeMatch]:
        if not query_text.strip():
            return _tfidf_matches(query_text, channels, idf, n_docs)
        texts = [query_text, *(_channel_text(channel, depth) for channel in channels)]
        encoded = self.encoder.encode(texts)
        query_embedding = encoded[0]
        explanations = _tfidf_matches(query_text, channels, idf, n_docs)
        for channel, embedding in zip(channels, encoded[1:]):
            channel_id = channel.get("channel_id", "")
            explanations[channel_id]["score"] = _dense_cosine(
                query_embedding, embedding
            )
        return explanations


def make_semantic_engine(kind: str, model_name: str) -> SemanticEngine:
    if (kind or "").strip().lower() == "embeddings":
        return EmbeddingEngine(model_name)
    return TfidfEngine()


HttpPost = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def _http_post(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> dict[str, Any]:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL configurata
        return json.loads(response.read().decode("utf-8"))


class OpenAICompatibleCircleLabeler:
    """Label opzionali con cache process-local e fallback non distruttivo."""

    _cache: ClassVar[dict[tuple[str, str, tuple[str, ...]], str]] = {}

    def __init__(
        self,
        url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 10.0,
        http_post: HttpPost | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._http_post = http_post or _http_post

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.model)

    def label(self, terms: list[str]) -> str | None:
        terms_key = tuple(terms)
        if not self.enabled or not terms_key:
            return None
        key = (self.url, self.model, terms_key)
        if key in self._cache:
            return self._cache[key]
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 30,
            "messages": [{
                "role": "user",
                "content": (
                    "Dai un'etichetta italiana breve (massimo 6 parole) a questi "
                    f"temi, senza virgolette: {'; '.join(terms)}"
                ),
            }],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self._http_post(
                self.url, headers, json.dumps(payload).encode("utf-8"), self.timeout
            )
            value = str(response["choices"][0]["message"]["content"]).strip()
            value = value.strip('"').strip("'")
            if not value:
                return None
        except Exception:
            return None
        self._cache[key] = value
        return value

    def apply(self, circles: list[dict[str, Any]]) -> None:
        for circle in circles:
            label = self.label(circle.get("label_terms") or [])
            if label:
                circle["label"] = f"{label} ({circle['channel_count']} canali)"
