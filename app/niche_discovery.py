"""Espansione di un bacino a partire dai seed di una nicchia.

La logica è deliberatamente conservativa rispetto alla quota API YouTube:
per ogni sorgente (canale, video, keyword) si effettua al massimo una
chiamata a ``search.list`` e una chiamata aggregata a ``videos.list``.

Oltre ai seed testuali, la nicchia può definire un perimetro
geo-linguistico (filtri ``region_code``, ``relevance_language``,
``channel_country``, ``channel_language``, ``min/max_subscribers``,
``harvest_popular``, ``strict_geo``). I segnali geografici provengono
dalle dichiarazioni del creator su YouTube: quando non sono dichiarati
il contenuto non viene penalizzato, a meno che ``strict_geo`` non
richieda esplicitamente la corrispondenza.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from app.connectors import SocialConnector


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_URL_PATTERN = re.compile(r"(?:v=|/)([A-Za-z0-9_-]{11})")


def _extract_video_id(value: str) -> str | None:
    value = value.strip()
    if VIDEO_ID_PATTERN.fullmatch(value):
        return value
    match = YOUTUBE_URL_PATTERN.search(value)
    return match.group(1) if match else None


def _normalize(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[a-zA-Zà-úÀ-Ú0-9]+", text)}


def _score_content(
    content: dict[str, Any],
    channel_seeds: set[str],
    video_seeds: set[str],
    include_keywords: set[str],
    exclude_keywords: set[str],
) -> tuple[float, str, str] | None:
    title = content.get("title", "")
    description = content.get("description", "")
    tags = [tag.lower() for tag in content.get("tags", [])]
    text = f"{title} {description} {' '.join(tags)}"
    text_terms = _normalize(text) | set(tags)

    for excluded in exclude_keywords:
        if excluded in text_terms or excluded in title.lower():
            return None

    score = 0.0
    matched_seed = "keyword"
    matched_value = ""

    raw_channel_id = content.get("channel_id", "").strip()
    channel_id = raw_channel_id.lower()
    channel_title = content.get("channel_title", "").strip().lower()
    if channel_id in channel_seeds or channel_title in channel_seeds:
        score += 1.0
        matched_seed = "channel"
        matched_value = raw_channel_id or channel_title

    external_id = content.get("external_id", "").strip()
    if external_id in video_seeds:
        score += 0.8
        matched_seed = "video"
        matched_value = external_id

    keyword_hits = [kw for kw in include_keywords if kw in text_terms]
    if keyword_hits:
        score += min(0.5 * len(keyword_hits), 1.0)
        if matched_seed == "keyword":
            matched_value = keyword_hits[0]

    return max(score, 0.05), matched_seed, matched_value


def _normalize_language(value: str) -> str:
    """Normalizza una lingua (``it-IT`` e ``it`` sono equivalenti)."""
    return value.strip().lower().split("-")[0]


def _run_parallel(tasks: list[Callable[[], Any]]) -> list[Any]:
    """Esegue chiamate API indipendenti in parallelo preservando l'ordine.

    Le ricerche di espansione sono tra loro indipendenti: eseguirle in
    sequenza renderebbe la preview lenta in proporzione al numero di seed.
    Il numero di chiamate (e quindi la quota consumata) non cambia.
    """
    if len(tasks) <= 1:
        return [task() for task in tasks]
    with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
        return list(pool.map(lambda task: task(), tasks))


def _geo_signals(
    channel_meta: dict[str, Any] | None,
    *,
    channel_country: str,
    channel_language: str,
    min_subscribers: int,
    max_subscribers: int,
    strict_geo: bool,
) -> tuple[float, str | None]:
    """Valuta i segnali geo-linguistici dichiarati dal canale.

    Restituisce un boost di rilevanza e, se il canale va escluso, il motivo.
    Un dato non dichiarato dal creator non esclude mai il contenuto, nemmeno
    in modalità restrittiva: moltissimi creator non dichiarano paese o
    lingua ed escluderli svuoterebbe il panorama. La modalità restrittiva
    esclude solo le discrepanze esplicite.
    """
    if channel_meta is None:
        if min_subscribers or max_subscribers:
            return 0.0, "iscritti del canale non noti"
        return 0.0, None

    boost = 0.0

    subscribers = int(channel_meta.get("subscribers", 0))
    if min_subscribers and subscribers < min_subscribers:
        return 0.0, f"iscritti sotto il minimo ({subscribers} < {min_subscribers})"
    if max_subscribers and subscribers > max_subscribers:
        return 0.0, f"iscritti sopra il massimo ({subscribers} > {max_subscribers})"
    if min_subscribers or max_subscribers:
        boost += 0.1

    declared_country = (channel_meta.get("country") or "").strip().upper()
    if channel_country:
        if declared_country == channel_country.strip().upper():
            boost += 0.25
        elif declared_country and strict_geo:
            return 0.0, f"paese dichiarato diverso ({declared_country})"

    declared_language = _normalize_language(channel_meta.get("default_language") or "")
    if channel_language:
        if declared_language and declared_language == _normalize_language(channel_language):
            boost += 0.25
        elif declared_language and strict_geo:
            return 0.0, f"lingua del canale diversa ({declared_language})"

    return boost, None


def expand_niche(
    niche: dict[str, Any],
    connector: SocialConnector,
    now: datetime | None = None,
    stats: dict[str, Any] | None = None,
    collect_channel_meta: bool = False,
) -> list[dict[str, Any]]:
    """Espande il bacino di una nicchia a partire dai seed.

    Restituisce una lista di contenuti arricchiti con:
    - ``relevance_score``: punteggio di rilevanza per la nicchia;
    - ``matched_seed``: tipo di seed che ha generato il match;
    - ``matched_value``: valore del seed che ha generato il match.

    Se viene passato il dizionario ``stats``, viene riempito con la
    diagnostica della raccolta: risultati per fonte, fonti saltate per
    il budget di ricerca, canali verificati ed esclusioni geo-linguistiche.
    Utile per rendere visibile perché una ricerca non ha prodotto risultati.

    Con ``collect_channel_meta=True`` i metadati dei canali vengono
    recuperati anche senza filtri geo attivi e pubblicati in
    ``stats["channel_meta"]`` (serve al pool canali del panorama).
    """
    now = now or datetime.now(timezone.utc)
    acquired_at = now.isoformat()
    filters = niche.get("filters", {})
    days = int(filters.get("date_window_days", 90))
    max_results = int(filters.get("max_results", 50))
    max_per_source = max(10, min(max_results // 3, 50))

    # Perimetro geo-linguistico: orienta le ricerche e delimita i canali.
    region_code = (filters.get("region_code") or "").strip() or None
    relevance_language = (filters.get("relevance_language") or "").strip() or None
    channel_country = (filters.get("channel_country") or "").strip()
    channel_language = (filters.get("channel_language") or "").strip()
    min_subscribers = int(filters.get("min_subscribers", 0) or 0)
    max_subscribers = int(filters.get("max_subscribers", 0) or 0)
    strict_geo = bool(filters.get("strict_geo", False))
    geo_active = any([
        region_code, relevance_language, channel_country, channel_language,
        min_subscribers, max_subscribers,
    ])

    # Risolvi i riferimenti ai canali seed (ID UC..., @handle o URL) prima
    # di costruire le ricerche: un handle usato come channelId produrrebbe
    # un errore 400 e zero risultati, bruciando quota di ricerca.
    raw_channel_refs = [
        channel.get("channel_id", "").strip()
        for channel in niche.get("seed_channels", [])
        if channel.get("channel_id", "").strip()
    ]
    resolved_ids = _run_parallel([
        (lambda ref=ref: connector.resolve_channel(ref)) for ref in raw_channel_refs
    ])
    channel_ref_map = dict(zip(raw_channel_refs, resolved_ids))
    unresolved_channels = sorted(ref for ref in raw_channel_refs if not channel_ref_map[ref])

    channel_seeds = {
        resolved.lower()
        for resolved in resolved_ids
        if resolved
    } | {
        c.get("channel_title", "").strip().lower()
        for c in niche.get("seed_channels", [])
        if c.get("channel_title")
    }

    video_seeds = set()
    invalid_video_seeds: list[str] = []
    for video in niche.get("seed_videos", []):
        raw_video_ref = video.get("video_id", "").strip()
        video_id = _extract_video_id(raw_video_ref)
        if video_id:
            video_seeds.add(video_id)
        elif raw_video_ref:
            invalid_video_seeds.append(raw_video_ref)

    include_keywords = {
        kw.strip().lower()
        for kw in niche.get("include_keywords", [])
        if kw.strip()
    }
    exclude_keywords = {
        kw.strip().lower()
        for kw in niche.get("exclude_keywords", [])
        if kw.strip()
    }

    # Fonti di raccolta: panorama popolare + fino a 10 ricerche fra canali
    # seed e keyword (budget conservativo sulla quota, invariato). Le
    # chiamate vengono eseguite in parallelo perché sono indipendenti.
    sources: list[dict[str, Any]] = []
    if filters.get("harvest_popular") and region_code:
        sources.append({
            "type": "popular", "value": region_code,
            "run": lambda: connector.fetch_popular(
                region_code=region_code, max_results=min(max_results, 50),
            ),
        })
    pending: list[dict[str, Any]] = []
    for channel in niche.get("seed_channels", []):
        raw_ref = channel.get("channel_id", "").strip()
        channel_id = channel_ref_map.get(raw_ref)
        if channel_id:
            pending.append({
                "type": "channel", "value": channel_id,
                "run": lambda cid=channel_id: connector.search(
                    channel_id=cid, days=days, max_results=max_per_source, now=now,
                    region_code=region_code, relevance_language=relevance_language,
                ),
            })
    for keyword in niche.get("include_keywords", []):
        keyword = keyword.strip()
        if keyword:
            pending.append({
                "type": "keyword", "value": keyword,
                "run": lambda kw=keyword: connector.search(
                    query=kw, days=days, max_results=max_per_source, now=now,
                    region_code=region_code, relevance_language=relevance_language,
                ),
            })
    sources.extend(pending[:10])
    skipped_sources = pending[10:]

    collected_ids: list[str] = []
    popular_ids: set[str] = set()
    source_stats: list[dict[str, Any]] = []
    for source, ids in zip(sources, _run_parallel([source["run"] for source in sources])):
        if source["type"] == "popular":
            popular_ids = set(ids)
        collected_ids.extend(ids)
        source_stats.append({
            "type": source["type"], "value": source["value"], "found": len(ids),
        })

    # Video seed (sempre inclusi, se validi)
    collected_ids.extend(sorted(video_seeds))

    if not collected_ids:
        if stats is not None:
            stats["sources"] = source_stats
            stats["sources_skipped"] = skipped_sources
            stats["unresolved_channels"] = unresolved_channels
            stats["invalid_video_seeds"] = invalid_video_seeds
            stats["candidates"] = 0
            stats["channels_checked"] = 0
            stats["excluded_geo"] = 0
            stats["kept"] = 0
        return []

    # Deduplica preservando l'ordine di scoperta
    seen: set[str] = set()
    unique_ids = [vid for vid in collected_ids if not (vid in seen or seen.add(vid))][:max_results]

    detail_chunks = [unique_ids[i:i + 50] for i in range(0, len(unique_ids), 50)]
    contents = [
        content
        for chunk_contents in _run_parallel([
            (lambda chunk=chunk: connector.fetch_details(
                chunk,
                niche=niche.get("name", ""),
                topic=niche.get("description", ""),
                source_query="niche_discovery",
                acquired_at=acquired_at,
            ))
            for chunk in detail_chunks
        ])
        for content in chunk_contents
    ]

    # Metadati dei canali osservati, per i segnali geo-linguistici e per
    # il pool canali del panorama (collect_channel_meta).
    channel_meta: dict[str, dict[str, Any]] = {}
    if geo_active or collect_channel_meta:
        channel_ids = sorted({
            content.get("channel_id", "").strip()
            for content in contents
            if content.get("channel_id", "").strip()
        })
        channel_chunks = [channel_ids[i:i + 50] for i in range(0, len(channel_ids), 50)]
        for meta_chunk in _run_parallel([
            (lambda chunk=chunk: connector.fetch_channels(chunk))
            for chunk in channel_chunks
        ]):
            channel_meta.update(meta_chunk)

    enriched: list[dict[str, Any]] = []
    excluded_geo = 0
    for content in contents:
        scoring = _score_content(
            content, channel_seeds, video_seeds, include_keywords, exclude_keywords,
        )
        if scoring is None:
            continue
        score, matched_seed, matched_value = scoring
        if geo_active:
            boost, exclusion = _geo_signals(
                channel_meta.get(content.get("channel_id", "").strip()),
                channel_country=channel_country,
                channel_language=channel_language,
                min_subscribers=min_subscribers,
                max_subscribers=max_subscribers,
                strict_geo=strict_geo,
            )
            if exclusion is not None:
                excluded_geo += 1
                continue
            if boost:
                score += boost
                if matched_seed == "keyword" and not matched_value:
                    matched_value = "geo"
            if (
                content.get("external_id", "") in popular_ids
                and matched_seed == "keyword" and not matched_value
            ):
                matched_seed = "popular"
                matched_value = region_code or ""
            meta = channel_meta.get(content.get("channel_id", "").strip()) or {}
            content["channel_country"] = meta.get("country", "")
            content["channel_language"] = meta.get("default_language", "")
            content["channel_subscribers"] = meta.get("subscribers", 0)
        min_views = int(filters.get("min_views", 0))
        if content.get("views", 0) < min_views:
            continue
        content["relevance_score"] = round(score, 3)
        content["matched_seed"] = matched_seed
        content["matched_value"] = matched_value
        enriched.append(content)

    enriched.sort(key=lambda item: item.get("relevance_score", 0), reverse=True)
    if stats is not None:
        stats["sources"] = source_stats
        stats["sources_skipped"] = skipped_sources
        stats["unresolved_channels"] = unresolved_channels
        stats["invalid_video_seeds"] = invalid_video_seeds
        stats["candidates"] = len(contents)
        stats["channels_checked"] = len(channel_meta)
        stats["excluded_geo"] = excluded_geo
        stats["kept"] = len(enriched[:max_results])
        if collect_channel_meta:
            stats["channel_meta"] = channel_meta
    return enriched[:max_results]


def aggregate_channel_pool(
    contents: list[dict[str, Any]],
    channel_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggrega i contenuti raccolti per canale (N1: il canale è l'unità).

    Ogni canale del pool porta con sé i video osservati come evidenza
    (titolo, views, data) e le metriche aggregate calcolate su di essi.
    I metadati dichiarati dal creator (paese, lingua, iscritti,
    descrizione) vengono allegati quando disponibili.
    """
    channel_meta = channel_meta or {}
    pool: dict[tuple[str, str], dict[str, Any]] = {}
    for content in contents:
        channel_id = content.get("channel_id", "").strip()
        if not channel_id:
            continue
        platform = content.get("platform", "YouTube") or "YouTube"
        key = (platform, channel_id)
        entry = pool.get(key)
        if entry is None:
            meta = channel_meta.get(channel_id) or {}
            entry = {
                "platform": platform,
                "channel_id": channel_id,
                "channel_title": content.get("channel_title", "") or meta.get("title", ""),
                "custom_url": meta.get("custom_url", ""),
                "description": meta.get("description", ""),
                "channel_published_at": meta.get("published_at", ""),
                "country": meta.get("country", ""),
                "language": meta.get("default_language", ""),
                "subscribers": int(meta.get("subscribers", 0) or 0),
                "declared_video_count": int(meta.get("video_count", 0) or 0),
                "videos": [],
                "matched_seed": "",
                "matched_value": "",
                "relevance_score": 0.0,
            }
            pool[key] = entry
        entry["videos"].append({
            "external_id": content.get("external_id", ""),
            "platform": platform,
            "title": content.get("title", ""),
            "description": content.get("description", ""),
            "tags": list(content.get("tags", []) or []),
            "published_at": content.get("published_at", ""),
            "views": int(content.get("views", 0)),
            "likes": int(content.get("likes", 0)),
            "comments": int(content.get("comments", 0)),
            "duration_seconds": int(content.get("duration_seconds", 0) or 0),
            "has_paid_product_placement": bool(
                content.get("has_paid_product_placement", False)
            ),
            "niche": content.get("niche", ""),
            "topic": content.get("topic", ""),
            "source_query": content.get("source_query", ""),
            "acquired_at": content.get("acquired_at", ""),
            "relevance_score": content.get("relevance_score", 0.0),
            "matched_seed": content.get("matched_seed", ""),
            "matched_value": content.get("matched_value", ""),
        })
        if content.get("relevance_score", 0.0) > entry["relevance_score"]:
            entry["relevance_score"] = content["relevance_score"]
            entry["matched_seed"] = content.get("matched_seed", "")
            entry["matched_value"] = content.get("matched_value", "")

    channels = list(pool.values())
    for entry in channels:
        views = [video["views"] for video in entry["videos"]]
        likes = sum(video["likes"] for video in entry["videos"])
        comments = sum(video["comments"] for video in entry["videos"])
        total_views = sum(views)
        entry["video_count"] = len(entry["videos"])
        entry["total_views"] = total_views
        entry["avg_views"] = round(total_views / len(views)) if views else 0
        entry["max_views"] = max(views) if views else 0
        entry["engagement_rate"] = (
            round((likes + comments) / total_views, 5) if total_views else 0.0
        )
        entry["last_published_at"] = max(
            (video["published_at"] for video in entry["videos"] if video["published_at"]),
            default="",
        )
        entry["videos"].sort(key=lambda video: video["views"], reverse=True)
    channels.sort(key=lambda entry: entry["total_views"], reverse=True)
    return channels


def _promote_top_channels(channels: list[dict[str, Any]], include_top: Any) -> int:
    """Promuove i canali con più views osservate a candidati di primo livello.

    Fonte di raccolta ``include_top_channels`` (N1): non consuma nuova
    quota, riusa i video già raccolti. Accetta ``True`` (top 10) o un
    intero esplicito. Restituisce il numero di canali promossi.
    """
    if not include_top:
        return 0
    # Attenzione: bool è sottotipo di int, va gestito prima.
    if isinstance(include_top, bool):
        limit = 10
    elif isinstance(include_top, int) and include_top > 0:
        limit = include_top
    else:
        return 0
    promoted = 0
    for entry in channels[: min(limit, len(channels))]:
        if entry.get("candidate_level") != "matched":
            entry["candidate_level"] = "top_channels"
            entry["promoted"] = True
            promoted += 1
    return promoted


def _second_wave(
    channels: list[dict[str, Any]],
    top_k: int,
    niche: dict[str, Any],
    connector: SocialConnector,
    now: datetime,
    acquired_at: str,
) -> int:
    """Seconda ondata opt-in: video recenti dei top-K canali emersi.

    Ogni canale costa una ``search.list`` (~100 unità di quota): per
    questo la funzione è disattivata per default e il numero di canali è
    dichiarato esplicitamente nei filtri (``second_wave_top_k``).
    Restituisce il numero di video aggiunti come evidenza.
    """
    if top_k <= 0:
        return 0
    targets = channels[: min(top_k, len(channels))]
    filters = niche.get("filters", {})
    days = int(filters.get("date_window_days", 90))
    per_channel = max(10, min(int(filters.get("max_results", 50)), 50))
    new_ids = _run_parallel([
        (lambda channel=channel: connector.search(
            channel_id=channel["channel_id"], days=days, max_results=per_channel, now=now,
            region_code=(filters.get("region_code") or "").strip() or None,
            relevance_language=(filters.get("relevance_language") or "").strip() or None,
        ))
        for channel in targets
    ])
    known_ids = {
        video["external_id"]
        for channel in channels
        for video in channel["videos"]
    }
    to_fetch: list[str] = []
    for ids in new_ids:
        to_fetch.extend(video_id for video_id in ids if video_id not in known_ids)
        known_ids.update(ids)
    if not to_fetch:
        return 0
    chunks = [to_fetch[i:i + 50] for i in range(0, len(to_fetch), 50)]
    contents = [
        content
        for chunk_contents in _run_parallel([
            (lambda chunk=chunk: connector.fetch_details(
                chunk,
                niche=niche.get("name", ""),
                topic=niche.get("description", ""),
                source_query="niche_second_wave",
                acquired_at=acquired_at,
            ))
            for chunk in chunks
        ])
        for content in chunk_contents
    ]
    by_channel = {channel["channel_id"]: channel for channel in channels}
    added = 0
    for content in contents:
        channel = by_channel.get(content.get("channel_id", "").strip())
        if channel is None:
            continue
        channel["videos"].append({
            "external_id": content.get("external_id", ""),
            "title": content.get("title", ""),
            "description": content.get("description", ""),
            "tags": list(content.get("tags", []) or []),
            "published_at": content.get("published_at", ""),
            "views": int(content.get("views", 0)),
            "likes": int(content.get("likes", 0)),
            "comments": int(content.get("comments", 0)),
            "relevance_score": 0.0,
            "matched_seed": "second_wave",
            "matched_value": channel["channel_id"],
        })
        added += 1
    return added


def expand_niche_channels(
    niche: dict[str, Any],
    connector: SocialConnector,
    now: datetime | None = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Espande la nicchia in un pool di **canali candidati** (milestone N1).

    Riusa la raccolta video di :func:`expand_niche` (stessa quota e stessi
    tempi) e aggrega i contenuti per canale: ogni canale porta con sé i
    video osservati come evidenza e le metriche aggregate.

    Filtri aggiuntivi riconosciuti:
    - ``include_top_channels`` (bool | int): promuove i canali con più
      views osservate a candidati di primo livello, senza nuove ricerche;
    - ``second_wave_top_k`` (int, default 0): seconda ondata opt-in che
      raccoglie i video recenti dei top-K canali (~100 unità di quota
      ciascuno). Il budget stimato è riportato in ``stats["second_wave"]``.
    """
    now = now or datetime.now(timezone.utc)
    filters = niche.get("filters", {})
    inner_stats: dict[str, Any] = {}
    contents = expand_niche(
        niche, connector, now=now, stats=inner_stats, collect_channel_meta=True,
    )
    channel_meta = inner_stats.pop("channel_meta", {})
    channels = aggregate_channel_pool(contents, channel_meta)

    for entry in channels:
        entry["candidate_level"] = (
            "matched" if entry["relevance_score"] >= 0.5 else "observed"
        )
    promoted = _promote_top_channels(channels, filters.get("include_top_channels"))

    second_wave_top_k = int(filters.get("second_wave_top_k", 0) or 0)
    second_wave = {"channels": 0, "estimated_units": 0, "videos_added": 0}
    if second_wave_top_k > 0 and channels:
        second_wave["channels"] = min(second_wave_top_k, len(channels))
        second_wave["estimated_units"] = second_wave["channels"] * 100
        second_wave["videos_added"] = _second_wave(
            channels, second_wave_top_k, niche, connector, now, now.isoformat(),
        )
        # Ricalcola le metriche aggregate dopo l'arricchimento.
        channels = aggregate_channel_pool(
            [
                {**video, "channel_id": entry["channel_id"],
                 "channel_title": entry["channel_title"],
                 "platform": entry.get("platform", "YouTube")}
                for entry in channels
                for video in entry["videos"]
            ],
            channel_meta,
        )
        for entry in channels:
            entry["candidate_level"] = (
                "matched" if entry["relevance_score"] >= 0.5 else "observed"
            )
        _promote_top_channels(channels, filters.get("include_top_channels"))

    if stats is not None:
        stats.update(inner_stats)
        stats["channels"] = len(channels)
        stats["channels_promoted"] = promoted
        stats["second_wave"] = second_wave
    return channels
