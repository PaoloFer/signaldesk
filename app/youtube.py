from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen


API_ROOT = "https://www.googleapis.com/youtube/v3"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
CHANNEL_URL_ID_PATTERN = re.compile(r"/channel/(UC[A-Za-z0-9_-]{22})")
CHANNEL_URL_HANDLE_PATTERN = re.compile(r"youtube\.com/@([A-Za-z0-9._-]{3,30})")
HANDLE_PATTERN = re.compile(r"^@?[A-Za-z0-9._-]{3,30}$")
DURATION_PATTERN = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


class YouTubeAPIError(RuntimeError):
    pass


# Costo documentato in unità di quota per endpoint YouTube Data API v3.
# search.list costa 100 unità, le altre chiamate usate costano 1 unità.
QUOTA_COSTS: dict[str, tuple[str, int]] = {
    "/youtube/v3/search": ("search.list", 100),
    "/youtube/v3/videos": ("videos.list", 1),
    "/youtube/v3/channels": ("channels.list", 1),
    "/youtube/v3/playlistItems": ("playlistItems.list", 1),
    "/youtube/v3/commentThreads": ("commentThreads.list", 1),
    "/youtube/v3/comments": ("comments.list", 1),
}


def _record_quota_usage(url: str) -> None:
    """Registra il consumo stimato di quota della chiamata (C1).

    Non deve mai interrompere il flusso principale: qualunque errore di
    persistenza del contatore viene ignorato.
    """
    try:
        path = urlparse(url).path
        operation, units = QUOTA_COSTS.get(path, ("other", 1))
        from app.database import record_api_usage

        record_api_usage(operation, units)
    except Exception:
        pass


def extract_video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID_PATTERN.fullmatch(value):
        return value
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().removeprefix("www.")
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            candidate = parsed.path.strip("/").split("/")[1]
    if not VIDEO_ID_PATTERN.fullmatch(candidate):
        raise ValueError("Inserisci un URL YouTube valido o un ID video di 11 caratteri")
    return candidate


def pseudonymize(author_id: str, salt: str) -> str:
    digest = hmac.new(salt.encode(), author_id.encode(), hashlib.sha256).hexdigest()
    return f"yt-{digest[:12]}"


def parse_channel_reference(value: str) -> dict[str, str]:
    """Classifica un riferimento a un canale YouTube.

    Gli utenti inseriscono ID (``UC...``), handle (``@nome`` o ``nome``),
    URL di canale oppure nomi liberi. Solo gli ID possono essere usati
    direttamente nelle ricerche: gli handle vanno risolti, i nomi liberi
    non sono risolvibili in modo deterministico.
    """
    value = value.strip()
    if CHANNEL_ID_PATTERN.fullmatch(value):
        return {"kind": "id", "value": value}
    url_id = CHANNEL_URL_ID_PATTERN.search(value)
    if url_id:
        return {"kind": "id", "value": url_id.group(1)}
    url_handle = CHANNEL_URL_HANDLE_PATTERN.search(value)
    if url_handle:
        return {"kind": "handle", "value": url_handle.group(1)}
    if HANDLE_PATTERN.fullmatch(value):
        return {"kind": "handle", "value": value.lstrip("@")}
    return {"kind": "name", "value": value}


def resolve_channel_id(
    api_key: str,
    reference: str,
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> str | None:
    """Risolve un riferimento a canale in un ID ``UC...``.

    Gli ID vengono restituiti senza chiamate API. Gli handle vengono
    risolti con ``channels.list?forHandle=``: una sola unità di quota,
    molto più economica di una ``search.list`` destinata a fallire.
    Restituisce ``None`` quando il riferimento non è risolvibile.
    """
    parsed = parse_channel_reference(reference)
    if parsed["kind"] == "id":
        return parsed["value"]
    if parsed["kind"] != "handle":
        return None
    request = request_json or _request_json
    parameters = {"part": "id", "forHandle": parsed["value"], "key": api_key}
    payload = request(f"{API_ROOT}/channels?{urlencode(parameters)}")
    items = payload.get("items", [])
    return items[0]["id"] if items else None


def parse_duration(value: str) -> int:
    match = DURATION_PATTERN.fullmatch(value)
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _request_json(url: str, max_retries: int = 3) -> dict[str, Any]:
    retryable = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urlopen(url, timeout=20) as response:  # noqa: S310 - fixed Google API host
                _record_quota_usage(url)
                return json.load(response)
        except HTTPError as exc:
            last_error = exc
            if exc.code in retryable and attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt + 1)
                continue
            try:
                detail = json.loads(exc.read().decode())["error"]["message"]
            except (KeyError, ValueError, UnicodeDecodeError):
                detail = f"YouTube API ha risposto con stato {exc.code}"
            raise YouTubeAPIError(detail) from exc
        except URLError as exc:
            raise YouTubeAPIError("YouTube API non raggiungibile") from exc
    raise YouTubeAPIError("YouTube API non disponibile dopo i tentativi") from last_error


def _comment_row(
    comment_id: str,
    video_id: str,
    content_title: str,
    snippet: dict[str, Any],
    salt: str,
    niche: str,
    topic: str,
) -> dict[str, Any]:
    author_channel = snippet.get("authorChannelId", {}).get("value")
    author_source = author_channel or snippet.get("authorDisplayName") or comment_id
    return {
        "external_id": comment_id,
        "content_id": video_id,
        "content_title": content_title,
        "author_hash": pseudonymize(author_source, salt),
        "text": snippet.get("textDisplay", ""),
        "published_at": snippet["publishedAt"],
        "platform": "YouTube",
        "niche": niche.strip(),
        "topic": topic.strip(),
    }


def fetch_video_comments(
    api_key: str,
    video: str,
    niche: str,
    topic: str,
    max_comments: int = 200,
    salt: str = "signaldesk-development-only",
    request_json: Callable[[str], dict[str, Any]] | None = None,
    content_title: str | None = None,
    include_replies: bool = False,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    request = request_json or _request_json
    video_id = extract_video_id(video)
    if content_title is None:
        metadata_url = f"{API_ROOT}/videos?{urlencode({'part': 'snippet', 'id': video_id, 'key': api_key})}"
        metadata_payload = request(metadata_url)
        metadata_items = metadata_payload.get("items", [])
        if not metadata_items:
            raise YouTubeAPIError("Video non trovato o non accessibile con questa chiave API")
        snippet = metadata_items[0]["snippet"]
        metadata = {
            "video_id": video_id,
            "title": snippet.get("title", "Video YouTube"),
            "channel": snippet.get("channelTitle", ""),
        }
    else:
        metadata = {"video_id": video_id, "title": content_title, "channel": ""}

    comments: list[dict[str, Any]] = []
    page_token = ""
    parts = "snippet,replies" if include_replies else "snippet"
    while len(comments) < max_comments:
        parameters = {
            "part": parts,
            "videoId": video_id,
            "maxResults": min(100, max_comments - len(comments)),
            "textFormat": "plainText",
            "order": "time",
            "key": api_key,
        }
        if page_token:
            parameters["pageToken"] = page_token
        payload = request(f"{API_ROOT}/commentThreads?{urlencode(parameters)}")
        for item in payload.get("items", []):
            top_level = item["snippet"]["topLevelComment"]
            top_snippet = top_level["snippet"]
            comments.append(_comment_row(
                top_level["id"], video_id, metadata["title"], top_snippet,
                salt, niche, topic,
            ))
            if include_replies:
                for reply in item.get("replies", {}).get("comments", []):
                    if len(comments) >= max_comments:
                        break
                    reply_snippet = reply["snippet"]
                    comments.append(_comment_row(
                        reply["id"], video_id, metadata["title"], reply_snippet,
                        salt, niche, topic,
                    ))
            if len(comments) >= max_comments:
                break
        page_token = payload.get("nextPageToken", "")
        if not page_token or not payload.get("items"):
            break
    return metadata, comments[:max_comments]


def _video_ids_from_search(payload: dict[str, Any]) -> list[str]:
    return [
        item.get("id", {}).get("videoId")
        for item in payload.get("items", [])
        if item.get("id", {}).get("videoId")
    ]


def _contents_from_video_details(
    payload: dict[str, Any],
    *,
    niche: str = "",
    topic: str = "",
    source_query: str = "",
    acquired_at: str,
) -> list[dict[str, Any]]:
    contents = []
    for item in payload.get("items", []):
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        # Dichiarazione ufficiale del creator ("contenuto promozionale").
        # Il part paidProductPlacementDetails potrebbe mancare su video
        # datati o non idonei: in quel caso il flag resta False.
        paid_placement = item.get("paidProductPlacementDetails", {})
        contents.append({
            "external_id": item["id"],
            "platform": "YouTube",
            "title": snippet.get("title", "Video YouTube"),
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "published_at": snippet["publishedAt"],
            "duration_seconds": parse_duration(item.get("contentDetails", {}).get("duration", "")),
            "views": int(statistics.get("viewCount", 0)),
            "likes": int(statistics.get("likeCount", 0)),
            "comments": int(statistics.get("commentCount", 0)),
            "has_paid_product_placement": bool(paid_placement.get("hasPaidProductPlacement", False)),
            "niche": niche.strip(),
            "topic": topic.strip() or source_query.strip(),
            "source_query": source_query.strip(),
            "acquired_at": acquired_at,
        })
    return contents


def search_videos(
    api_key: str,
    query: str | None = None,
    channel_id: str | None = None,
    days: int = 30,
    max_results: int = 50,
    region_code: str | None = None,
    relevance_language: str | None = None,
    request_json: Callable[[str], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Restituisce una lista di video ID ottenuti da una ricerca YouTube.

    Supporta ricerca per query libera o limitata a un canale. ``region_code``
    (es. ``IT``) e ``relevance_language`` (es. ``it``) orientano il ranking
    verso un'area geografica e una lingua senza escludere altri risultati.
    Non restituisce i dettagli: per quelli usare :func:`fetch_video_details`.
    """
    request = request_json or _request_json
    now = now or datetime.now(timezone.utc)
    published_after = (now - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    search_parameters: dict[str, Any] = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "maxResults": min(max_results, 50),
        "publishedAfter": published_after,
        "key": api_key,
    }
    if query:
        search_parameters["q"] = query.strip()
    if channel_id:
        search_parameters["channelId"] = channel_id.strip()
    if region_code:
        search_parameters["regionCode"] = region_code.strip().upper()
    if relevance_language:
        search_parameters["relevanceLanguage"] = relevance_language.strip().lower()
    search_payload = request(f"{API_ROOT}/search?{urlencode(search_parameters)}")
    return _video_ids_from_search(search_payload)


def fetch_popular_video_ids(
    api_key: str,
    region_code: str,
    max_results: int = 50,
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> list[str]:
    """Restituisce gli ID dei video più popolari in una regione.

    Usa ``videos.list?chart=mostPopular``: ogni pagina costa una sola unità
    di quota, a differenza di ``search.list`` che ne costa 100. È la fonte
    ideale per osservare il panorama generale di un paese.
    """
    request = request_json or _request_json
    video_ids: list[str] = []
    page_token = ""
    while len(video_ids) < max_results:
        parameters: dict[str, Any] = {
            "part": "id",
            "chart": "mostPopular",
            "regionCode": region_code.strip().upper(),
            "maxResults": min(50, max_results - len(video_ids)),
            "key": api_key,
        }
        if page_token:
            parameters["pageToken"] = page_token
        payload = request(f"{API_ROOT}/videos?{urlencode(parameters)}")
        video_ids.extend(item["id"] for item in payload.get("items", []) if item.get("id"))
        page_token = payload.get("nextPageToken", "")
        if not page_token or not payload.get("items"):
            break
    return video_ids[:max_results]


def fetch_channel_details(
    api_key: str,
    channel_ids: list[str],
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Recupera paese, lingua predefinita e iscritti per una lista di canali.

    ``snippet.country`` e ``snippet.defaultLanguage`` sono dichiarati dal
    creator e possono mancare: in quel caso i valori restano stringhe vuote
    e i filtri geo-linguistici devono trattare il dato come "non noto".
    """
    request = request_json or _request_json
    details: dict[str, dict[str, Any]] = {}
    for start in range(0, len(channel_ids), 50):
        chunk = channel_ids[start:start + 50]
        parameters = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "key": api_key,
        }
        payload = request(f"{API_ROOT}/channels?{urlencode(parameters)}")
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            related_playlists = item.get("contentDetails", {}).get("relatedPlaylists", {})
            details[item["id"]] = {
                "title": snippet.get("title", ""),
                "custom_url": snippet.get("customUrl", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "country": snippet.get("country", ""),
                "default_language": snippet.get("defaultLanguage", ""),
                "subscribers": int(statistics.get("subscriberCount", 0)),
                "video_count": int(statistics.get("videoCount", 0)),
                "uploads_playlist": related_playlists.get("uploads", ""),
            }
    return details


def fetch_channel_upload_video_ids(
    api_key: str,
    channel_ids: list[str],
    *,
    max_results_per_channel: int = 10,
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Recupera gli upload recenti dei canali senza usare search.list."""
    request = request_json or _request_json
    details = fetch_channel_details(api_key, channel_ids, request_json=request)
    results: dict[str, list[str]] = {}
    for channel_id in channel_ids:
        playlist_id = (details.get(channel_id) or {}).get("uploads_playlist", "")
        if not playlist_id:
            results[channel_id] = []
            continue
        video_ids = []
        page_token = ""
        while len(video_ids) < max_results_per_channel:
            parameters = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": min(50, max_results_per_channel - len(video_ids)),
                "key": api_key,
            }
            if page_token:
                parameters["pageToken"] = page_token
            try:
                payload = request(f"{API_ROOT}/playlistItems?{urlencode(parameters)}")
            except YouTubeAPIError:
                # Canali eliminati o playlist upload non pubbliche non devono
                # interrompere l'arricchimento degli altri anchor.
                video_ids = []
                break
            video_ids.extend(
                item.get("contentDetails", {}).get("videoId", "")
                for item in payload.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            )
            page_token = payload.get("nextPageToken", "")
            if not page_token or not payload.get("items"):
                break
        results[channel_id] = video_ids[:max_results_per_channel]
    return results


def fetch_video_details(
    api_key: str,
    video_ids: list[str],
    *,
    niche: str = "",
    topic: str = "",
    source_query: str = "",
    acquired_at: str,
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Recupera snippet, statistiche e durata per una lista di video ID."""
    request = request_json or _request_json
    contents: list[dict[str, Any]] = []
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start:start + 50]
        details_parameters = {
            "part": "snippet,statistics,contentDetails,paidProductPlacementDetails",
            "id": ",".join(chunk),
            "key": api_key,
        }
        details_payload = request(f"{API_ROOT}/videos?{urlencode(details_parameters)}")
        contents.extend(_contents_from_video_details(
            details_payload,
            niche=niche,
            topic=topic,
            source_query=source_query,
            acquired_at=acquired_at,
        ))
    return contents


def discover_videos(
    api_key: str,
    query: str,
    niche: str,
    days: int = 30,
    max_results: int = 25,
    topic: str = "",
    request_json: Callable[[str], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    request = request_json or _request_json
    now = now or datetime.now(timezone.utc)
    acquired_at = now.isoformat()
    published_after = (now - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    search_parameters = {
        "part": "snippet",
        "q": query.strip(),
        "type": "video",
        "order": "date",
        "maxResults": min(max_results, 50),
        "publishedAfter": published_after,
        "key": api_key,
    }
    search_payload = request(f"{API_ROOT}/search?{urlencode(search_parameters)}")
    video_ids = _video_ids_from_search(search_payload)
    if not video_ids:
        return []
    return fetch_video_details(
        api_key, video_ids, niche=niche, topic=topic,
        source_query=query.strip(), acquired_at=acquired_at,
        request_json=request_json,
    )


def fetch_video_metrics(
    api_key: str,
    video_ids: list[str],
    request_json: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    request = request_json or _request_json
    metrics = []
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start:start + 50]
        parameters = {"part": "statistics", "id": ",".join(chunk), "key": api_key}
        payload = request(f"{API_ROOT}/videos?{urlencode(parameters)}")
        for item in payload.get("items", []):
            statistics = item.get("statistics", {})
            metrics.append({
                "external_id": item["id"],
                "views": int(statistics.get("viewCount", 0)),
                "likes": int(statistics.get("likeCount", 0)),
                "comments": int(statistics.get("commentCount", 0)),
            })
    return metrics
