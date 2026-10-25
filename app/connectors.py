"""Framework per connettori social multipiattaforma.

Ogni connettore espone le operazioni di base necessarie a SignalDesk:
ricerca contenuti, recupero dettagli, commenti e metriche. L'implementazione
YouTube è la prima; nuove piattaforme possono essere aggiunte ereditando
:class:`SocialConnector` e registrandosi in :data:`CONNECTOR_REGISTRY`.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable

from app.youtube import (
    discover_videos,
    fetch_channel_details,
    fetch_channel_upload_video_ids,
    fetch_popular_video_ids,
    fetch_video_comments,
    fetch_video_details,
    fetch_video_metrics,
    resolve_channel_id,
    search_videos,
)


class SocialConnector(ABC):
    """Interfaccia comune per ogni fonte social supportata."""

    name: str = ""
    platform: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """True se il connettore ha le credenziali necessarie per operare."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        *,
        query: str | None = None,
        channel_id: str | None = None,
        days: int = 30,
        max_results: int = 50,
        region_code: str | None = None,
        relevance_language: str | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Restituisce una lista di ID contenuto rilevanti."""
        raise NotImplementedError

    def resolve_channel(self, channel_reference: str) -> str | None:
        """Risolve un riferimento a canale (ID, handle, URL) in un ID.

        Metodo opzionale: l'implementazione predefinita restituisce il
        riferimento così com'è, assumendo che sia già un identificativo
        valido per la piattaforma.
        """
        return channel_reference

    def fetch_channels(self, channel_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Recupera metadati dei canali (paese, lingua, iscritti).

        Metodo opzionale: i connettori che non espongono questi dati
        restituiscono un dizionario vuoto e i filtri geo-linguistici
        vengono ignorati.
        """
        return {}

    def fetch_popular(
        self,
        *,
        region_code: str,
        max_results: int = 50,
    ) -> list[str]:
        """Restituisce gli ID dei contenuti più popolari in una regione.

        Metodo opzionale, usato per osservare il panorama generale di un
        paese senza consumare quota di ricerca.
        """
        return []

    def fetch_channel_uploads(
        self, channel_ids: list[str], *, max_results_per_channel: int = 10,
    ) -> dict[str, list[str]]:
        """Recupera contenuti recenti direttamente dagli upload del canale."""
        return {}

    @abstractmethod
    def fetch_details(
        self,
        content_ids: list[str],
        *,
        niche: str = "",
        topic: str = "",
        source_query: str = "",
        acquired_at: str,
    ) -> list[dict[str, Any]]:
        """Recupera metadati e metriche per gli ID contenuto."""
        raise NotImplementedError

    @abstractmethod
    def fetch_comments(
        self,
        content_id: str,
        *,
        niche: str,
        topic: str = "",
        max_comments: int = 200,
        include_replies: bool = False,
        content_title: str | None = None,
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """Recupera i commenti pubblici di un contenuto."""
        raise NotImplementedError

    @abstractmethod
    def refresh_metrics(self, content_ids: list[str]) -> list[dict[str, Any]]:
        """Recupera le metriche aggiornate per gli ID contenuto."""
        raise NotImplementedError


class YouTubeConnector(SocialConnector):
    """Connettore per YouTube Data API v3."""

    name = "YouTube Data API v3"
    platform = "YouTube"

    def __init__(self, api_key: str | None = None, salt: str | None = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY", "")
        self.salt = salt or os.getenv("PSEUDONYM_SALT", "signaldesk-development-only")
        self._request_json: Callable[[str], dict[str, Any]] | None = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        *,
        query: str | None = None,
        channel_id: str | None = None,
        days: int = 30,
        max_results: int = 50,
        region_code: str | None = None,
        relevance_language: str | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        return search_videos(
            api_key=self.api_key,
            query=query,
            channel_id=channel_id,
            days=days,
            max_results=max_results,
            region_code=region_code,
            relevance_language=relevance_language,
            now=now,
        )

    def resolve_channel(self, channel_reference: str) -> str | None:
        return resolve_channel_id(api_key=self.api_key, reference=channel_reference)

    def fetch_channels(self, channel_ids: list[str]) -> dict[str, dict[str, Any]]:
        return fetch_channel_details(api_key=self.api_key, channel_ids=channel_ids)

    def fetch_popular(
        self,
        *,
        region_code: str,
        max_results: int = 50,
    ) -> list[str]:
        return fetch_popular_video_ids(
            api_key=self.api_key,
            region_code=region_code,
            max_results=max_results,
        )

    def fetch_channel_uploads(
        self, channel_ids: list[str], *, max_results_per_channel: int = 10,
    ) -> dict[str, list[str]]:
        return fetch_channel_upload_video_ids(
            api_key=self.api_key,
            channel_ids=channel_ids,
            max_results_per_channel=max_results_per_channel,
        )

    def fetch_details(
        self,
        content_ids: list[str],
        *,
        niche: str = "",
        topic: str = "",
        source_query: str = "",
        acquired_at: str,
    ) -> list[dict[str, Any]]:
        return fetch_video_details(
            api_key=self.api_key,
            video_ids=content_ids,
            niche=niche,
            topic=topic,
            source_query=source_query,
            acquired_at=acquired_at,
        )

    def fetch_comments(
        self,
        content_id: str,
        *,
        niche: str,
        topic: str = "",
        max_comments: int = 200,
        include_replies: bool = False,
        content_title: str | None = None,
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        return fetch_video_comments(
            api_key=self.api_key,
            video=content_id,
            niche=niche,
            topic=topic,
            max_comments=max_comments,
            salt=self.salt,
            include_replies=include_replies,
            content_title=content_title,
        )

    def refresh_metrics(self, content_ids: list[str]) -> list[dict[str, Any]]:
        return fetch_video_metrics(api_key=self.api_key, video_ids=content_ids)


CONNECTOR_REGISTRY: dict[str, type[SocialConnector]] = {
    "youtube": YouTubeConnector,
}


def get_connector(name: str, **kwargs: Any) -> SocialConnector:
    connector_class = CONNECTOR_REGISTRY.get(name)
    if not connector_class:
        raise ValueError(f"Connettore non supportato: {name}")
    return connector_class(**kwargs)
