from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.connectors import YouTubeConnector
from app.channel_profiling import emerging_circles, pool_themes, score_channels
from app.niche_discovery import aggregate_channel_pool, expand_niche_channels
from app.semantic_engine import TfidfEngine


DEFAULT_QUERIES = (
    "vlog italiano",
    "gaming italiano",
    "beauty creator italiana",
    "tecnologia italiano creator",
    "food creator italiano",
    "fitness creator italiano",
    "divulgazione italiana",
)

DEFAULT_ANCHOR_CHANNELS = (
    ("UCS5PaGnSnFUnrjSc80XRnqw", "Marcello Ascani"),
    ("UCN7x37T8InfV3DINfYKvOQQ", "Michele Molteni"),
    ("UCz-KJn98sMCPW5kjG0ZnE-Q", "Jakidale"),
)
DEFAULT_REGISTRY = ROOT / "data" / "italian_creator_seeds.json"

ITALIAN_MARKERS = {
    "anche", "come", "con", "cosa", "della", "delle", "degli", "dopo",
    "fare", "gli", "italia", "italiano", "italiana", "italiani", "italiane",
    "miei", "molto", "nel", "nella", "nelle", "nostro", "oggi", "per",
    "perché", "prima", "questo", "questa", "sono", "tutto", "una", "video",
    "vita", "voi",
}

PUBLISHER_STRONG_MARKERS = (
    "testata giornalistica", "quotidiano nazionale", "agenzia di stampa",
    "redazione giornalistica", "emittente televisiva", "network televisivo",
    "canale ufficiale di", "official channel of", "breaking news",
)
PUBLISHER_TITLE_MARKERS = {
    "news", "media", "quotidiano", "giornale", "radio", "sport", "clips",
    "corriere", "messaggero", "mattino", "tele", "sky", "mtv",
}
INDIVIDUAL_MARKERS = (
    "il mio canale", "nel mio canale", "mi chiamo", "sono un creator",
    "sono una creator", "sono uno youtuber", "seguimi", "i miei video",
    "la mia vita", "vlog", "content creator", "makeup artist", "gamer",
)

SUBSCRIBER_BANDS = (
    ("10K-50K", 10_000, 50_000),
    ("50K-100K", 50_000, 100_000),
    ("100K-500K", 100_000, 500_000),
    ("500K-1M", 500_000, 1_000_000),
    ("1M+", 1_000_000, None),
)


def italian_evidence(channel: dict[str, Any]) -> dict[str, Any]:
    country = str(channel.get("country", "")).strip().upper()
    language = str(channel.get("language", "")).strip().lower().split("-")[0]
    reasons = []
    conflicts = []
    if channel.get("matched_seed") == "channel" and channel.get("anchor_name"):
        reasons.append("anchor presente nel registry curato")
    if country == "IT":
        reasons.append("paese dichiarato IT")
    elif country:
        conflicts.append(f"paese dichiarato {country}")
    if language == "it":
        reasons.append("lingua dichiarata it")
    elif language:
        conflicts.append(f"lingua dichiarata {language}")

    text = " ".join((
        str(channel.get("channel_title", "")),
        str(channel.get("description", "")),
        *(f"{video.get('title', '')} {video.get('description', '')}"
          for video in channel.get("videos", [])),
    )).lower()
    tokens = re.findall(r"[a-zà-ú]+", text)
    marker_counts = Counter(token for token in tokens if token in ITALIAN_MARKERS)
    marker_total = sum(marker_counts.values())
    marker_types = len(marker_counts)

    if reasons:
        status = "confirmed"
    elif conflicts:
        status = "excluded"
    elif marker_types >= 5 and marker_total >= 8:
        status = "probable"
        reasons.append(f"testo prevalentemente italiano ({marker_total} segnali, {marker_types} distinti)")
    else:
        status = "insufficient"
        reasons.append(f"italianità non verificabile ({marker_total} segnali, {marker_types} distinti)")
    return {
        "status": status,
        "reasons": reasons,
        "conflicts": conflicts,
        "marker_total": marker_total,
        "marker_types": marker_types,
    }


def creator_evidence(channel: dict[str, Any]) -> dict[str, Any]:
    title = str(channel.get("channel_title", "")).lower()
    description = str(channel.get("description", "")).lower()
    text = f"{title} {description}"
    strong = [marker for marker in PUBLISHER_STRONG_MARKERS if marker in text]
    title_tokens = set(re.findall(r"[a-zà-ú]+", title))
    title_markers = sorted(title_tokens & PUBLISHER_TITLE_MARKERS)
    individual = [marker for marker in INDIVIDUAL_MARKERS if marker in text]
    if strong:
        status = "publisher"
        reasons = strong
    elif title_markers and not individual:
        status = "publisher"
        reasons = [f"indicatore editoriale nel nome: {marker}" for marker in title_markers]
    elif individual:
        status = "individual"
        reasons = individual
    else:
        status = "uncertain"
        reasons = ["profilo individuale non verificabile dai metadata pubblici"]
    return {"status": status, "reasons": reasons}


def build_niche(
    queries: list[str],
    *,
    anchor_channels: list[tuple[str, str]] | None = None,
    days: int,
    max_results: int,
    min_subscribers: int,
    include_popular: bool,
) -> dict[str, Any]:
    return {
        "name": "Content creator italiani 10K+",
        "description": (
            "Content creator italiani attivi su YouTube nei settori intrattenimento, "
            "lifestyle, cultura, tecnologia, gaming, food, beauty, sport e divulgazione"
        ),
        "seed_channels": [
            {"channel_id": channel_id, "channel_title": title}
            for channel_id, title in (anchor_channels or [])
        ],
        "seed_videos": [],
        "include_keywords": queries,
        "exclude_keywords": [
            "compilation", "reupload", "fanpage", "canale automatico", "notizie estere",
        ],
        "filters": {
            "date_window_days": days,
            "max_results": max_results,
            "region_code": "IT",
            "relevance_language": "it",
            "channel_country": "IT",
            "channel_language": "it",
            # Il paese YouTube può riflettere mercato/monetizzazione e non
            # nazionalità: Marcello Ascani, ad esempio, dichiara US ma lingua it.
            # La verifica combinata viene applicata dopo la raccolta.
            "strict_geo": False,
            "min_subscribers": min_subscribers,
            "harvest_popular": include_popular,
            "include_top_channels": True,
            "evidence_depth": "P2",
            "second_wave_top_k": 0,
            "cross_theme_ranking": True,
            "w_theme": 1.0,
            "w_geo": 1.0,
            "w_size": 0.5,
            "w_popularity": 0.4,
            "w_engagement": 0.6,
            "w_velocity": 0.0,
            "circles_top_n": 10,
        },
    }


def load_anchor_registry(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return [
            {"channel_id": channel_id, "name": name, "category": "anchor"}
            for channel_id, name in DEFAULT_ANCHOR_CHANNELS
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    anchors = []
    seen = set()
    for item in payload:
        channel_id = str(item.get("channel_id", "")).strip()
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        anchors.append({
            "channel_id": channel_id,
            "name": str(item.get("name", channel_id)).strip() or channel_id,
            "category": str(item.get("category", "anchor")).strip() or "anchor",
        })
    return anchors


def _channel_from_meta(channel_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": "YouTube",
        "channel_id": channel_id,
        "channel_title": meta.get("title", channel_id),
        "custom_url": meta.get("custom_url", ""),
        "description": meta.get("description", ""),
        "channel_published_at": meta.get("published_at", ""),
        "country": meta.get("country", ""),
        "language": meta.get("default_language", ""),
        "subscribers": int(meta.get("subscribers", 0) or 0),
        "declared_video_count": int(meta.get("video_count", 0) or 0),
        "videos": [],
        "matched_seed": "channel",
        "matched_value": channel_id,
        "relevance_score": 1.0,
    }


def _recalculate_channel(channel: dict[str, Any]) -> None:
    unique_videos = {}
    for video in channel.get("videos", []):
        external_id = video.get("external_id", "")
        if external_id:
            unique_videos[external_id] = video
    videos = list(unique_videos.values())
    views = [int(video.get("views", 0) or 0) for video in videos]
    total_views = sum(views)
    likes = sum(int(video.get("likes", 0) or 0) for video in videos)
    comments = sum(int(video.get("comments", 0) or 0) for video in videos)
    channel["videos"] = videos
    channel["video_count"] = len(videos)
    channel["total_views"] = total_views
    channel["avg_views"] = round(total_views / len(videos)) if videos else 0
    channel["max_views"] = max(views, default=0)
    channel["engagement_rate"] = round((likes + comments) / total_views, 5) if total_views else 0.0
    channel["last_published_at"] = max(
        (video.get("published_at", "") for video in videos if video.get("published_at")),
        default="",
    )
    channel["videos"].sort(key=lambda video: int(video.get("views", 0) or 0), reverse=True)


def _merge_channels(
    discovered: list[dict[str, Any]], anchors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (*discovered, *anchors):
        channel_id = source.get("channel_id", "")
        if not channel_id:
            continue
        if channel_id not in merged:
            merged[channel_id] = {**source, "videos": list(source.get("videos", []))}
            continue
        target = merged[channel_id]
        target["videos"].extend(source.get("videos", []))
        if source.get("matched_seed") == "channel":
            target["matched_seed"] = "channel"
            target["matched_value"] = source.get("matched_value", channel_id)
        for field in (
            "channel_title", "custom_url", "description", "channel_published_at",
            "country", "language", "subscribers", "declared_video_count",
            "anchor_name", "anchor_category",
        ):
            if source.get(field) not in (None, "", 0):
                target[field] = source[field]
    channels = list(merged.values())
    for channel in channels:
        _recalculate_channel(channel)
    return channels


def collect_anchor_channels(
    connector: YouTubeConnector,
    anchors: list[dict[str, str]],
    *,
    days: int,
    videos_per_anchor: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    channel_ids = [anchor["channel_id"] for anchor in anchors]
    meta = connector.fetch_channels(channel_ids)
    upload_ids = connector.fetch_channel_uploads(
        channel_ids, max_results_per_channel=videos_per_anchor,
    )
    all_video_ids = list(dict.fromkeys(
        video_id for channel_id in channel_ids for video_id in upload_ids.get(channel_id, [])
    ))
    acquired_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    contents = connector.fetch_details(
        all_video_ids,
        niche="Content creator italiani 10K+",
        topic="Creator italiani",
        source_query="anchor_registry",
        acquired_at=acquired_at,
    ) if all_video_ids else []
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    contents = [
        content for content in contents
        if not content.get("published_at")
        or datetime.fromisoformat(content["published_at"].replace("Z", "+00:00")).timestamp() >= since
    ]
    content_by_channel: dict[str, list[dict[str, Any]]] = {}
    for content in contents:
        content_by_channel.setdefault(content.get("channel_id", ""), []).append(content)
    channels = []
    for anchor in anchors:
        channel_id = anchor["channel_id"]
        channel = _channel_from_meta(channel_id, meta.get(channel_id, {}))
        channel["anchor_name"] = anchor["name"]
        channel["anchor_category"] = anchor["category"]
        channel["videos"] = content_by_channel.get(channel_id, [])
        _recalculate_channel(channel)
        channels.append(channel)
    diagnostics = {
        "requested": len(anchors),
        "resolved": sum(channel_id in meta for channel_id in channel_ids),
        "with_recent_videos": sum(bool(channel["videos"]) for channel in channels),
        "videos_collected": len(contents),
    }
    return channels, diagnostics


def _median(values: list[int | float]) -> float:
    ordered = sorted(float(value or 0) for value in values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _subscriber_distribution(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    distribution = []
    for label, minimum, maximum in SUBSCRIBER_BANDS:
        count = sum(
            1 for channel in channels
            if int(channel.get("subscribers", 0)) >= minimum
            and (maximum is None or int(channel.get("subscribers", 0)) < maximum)
        )
        distribution.append({"label": label, "channels": count})
    return distribution


def _clean_channel(channel: dict[str, Any]) -> dict[str, Any]:
    evidence = italian_evidence(channel)
    creator = creator_evidence(channel)
    return {
        "channel_id": channel.get("channel_id", ""),
        "title": channel.get("channel_title", ""),
        "custom_url": channel.get("custom_url", ""),
        "created_at": channel.get("channel_published_at", ""),
        "country": channel.get("country", ""),
        "language": channel.get("language", ""),
        "italian_evidence": evidence,
        "creator_evidence": creator,
        "subscribers": int(channel.get("subscribers", 0) or 0),
        "declared_video_count": int(channel.get("declared_video_count", 0) or 0),
        "observed_videos": int(channel.get("video_count", 0) or 0),
        "total_views": int(channel.get("total_views", 0) or 0),
        "average_views": int(channel.get("avg_views", 0) or 0),
        "engagement_rate": round(float(channel.get("engagement_rate", 0)) * 100, 2),
        "last_published_at": channel.get("last_published_at", ""),
        "matched_seed": channel.get("matched_seed", ""),
        "matched_value": channel.get("matched_value", ""),
        "score": float(channel.get("score", 0) or 0),
        "score_breakdown": channel.get("score_breakdown", {}),
        "themes": channel.get("themes", [])[:8],
        "circles": channel.get("circles", []),
        "shared_terms": channel.get("shared_terms", [])[:10],
        "evidence_videos": [
            {
                "external_id": video.get("external_id", ""),
                "title": video.get("title", ""),
                "published_at": video.get("published_at", ""),
                "views": int(video.get("views", 0) or 0),
                "likes": int(video.get("likes", 0) or 0),
                "comments": int(video.get("comments", 0) or 0),
                "duration_seconds": int(video.get("duration_seconds", 0) or 0),
            }
            for video in channel.get("videos", [])[:5]
        ],
    }


def analyze(
    connector: YouTubeConnector,
    *,
    queries: list[str],
    anchor_channels: list[dict[str, str]] | None,
    days: int,
    max_results: int,
    max_channels: int,
    min_subscribers: int,
    videos_per_anchor: int = 10,
    include_popular: bool = False,
) -> dict[str, Any]:
    anchors = anchor_channels or []
    niche = build_niche(
        queries,
        anchor_channels=[(item["channel_id"], item["name"]) for item in anchors],
        days=days,
        max_results=max_results,
        min_subscribers=min_subscribers,
        include_popular=include_popular,
    )
    stats: dict[str, Any] = {}
    discovery_niche = {**niche, "seed_channels": []}
    discovered = expand_niche_channels(discovery_niche, connector=connector, stats=stats)
    anchor_pool, anchor_stats = collect_anchor_channels(
        connector, anchors, days=days, videos_per_anchor=videos_per_anchor,
    )
    merged = _merge_channels(discovered, anchor_pool)
    preliminary = [
        channel for channel in merged
        if int(channel.get("subscribers", 0) or 0) >= min_subscribers
        and italian_evidence(channel)["status"] in {"confirmed", "probable"}
        and creator_evidence(channel)["status"] != "publisher"
    ]

    engine = TfidfEngine()
    profiles, idf, n_docs = engine.profiles(preliminary, depth="P2") if preliminary else ([], {}, 0)
    profiles_by_id = {profile["channel_id"]: profile for profile in profiles}
    for channel in preliminary:
        profile = profiles_by_id.get(channel["channel_id"], {})
        channel["themes"] = profile.get("themes", [])
        channel["vector"] = profile.get("vector", {})
    theme_matches = engine.theme_matches(
        niche["description"], preliminary, depth="P2", idf=idf, n_docs=n_docs,
    ) if preliminary else {}
    weights = {
        key: float(niche["filters"].get(key, 0.0) or 0.0)
        for key in ("w_theme", "w_geo", "w_size", "w_popularity", "w_engagement", "w_velocity")
    }
    geo_components = {
        channel["channel_id"]: (
            1.0 if italian_evidence(channel)["status"] == "confirmed" else 0.6
        )
        for channel in preliminary
    }
    theme_groups = [
        (channel.get("themes") or [{"term": "altro"}])[0]["term"]
        for channel in preliminary
    ]
    scored = score_channels(
        preliminary,
        query_text=niche["description"],
        idf=idf,
        n_docs=n_docs,
        weights=weights,
        geo_components=geo_components,
        theme_groups=theme_groups,
        cross_theme=True,
        theme_matches=theme_matches,
    )
    classified = [_clean_channel(channel) for channel in scored]
    accepted = list(classified)
    accepted.sort(key=lambda item: (-item["score"], -item["observed_videos"], -item["total_views"], item["title"]))
    accepted = accepted[:max_channels]
    accepted_ids = {item["channel_id"] for item in accepted}
    accepted_raw = [channel for channel in scored if channel.get("channel_id") in accepted_ids]
    profiles, _, _ = TfidfEngine().profiles(accepted_raw, depth="P2") if accepted_raw else ([], {}, 0)
    profiles_by_id = {profile["channel_id"]: profile for profile in profiles}
    for channel in accepted:
        channel["themes"] = profiles_by_id.get(channel["channel_id"], {}).get("themes", [])[:8]
    vectors = [profile.get("vector") or {} for profile in profiles]
    filtered_themes = pool_themes(vectors, min_channels=2, top_n=20)
    filtered_circles = emerging_circles(profiles, top_n=10)
    confirmed = sum(item["italian_evidence"]["status"] == "confirmed" for item in accepted)
    probable = sum(item["italian_evidence"]["status"] == "probable" for item in accepted)
    individual = sum(item["creator_evidence"]["status"] == "individual" for item in accepted)
    uncertain = sum(item["creator_evidence"]["status"] == "uncertain" for item in accepted)
    all_classified = [_clean_channel(channel) for channel in merged]
    publisher_excluded = sum(item["creator_evidence"]["status"] == "publisher" for item in all_classified)
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "definition": niche,
        "method": {
            "platform": "YouTube",
            "semantic_engine": "TF-IDF P2",
            "ranking": "cross-theme composite score",
            "italianity": "declared country/language or textual evidence",
            "minimum_subscribers": min_subscribers,
            "notice": "Campione osservato, non censimento completo dei creator italiani.",
        },
        "coverage": {
            "anchors_requested": len(anchors),
            "anchors_in_report": sum(
                item["channel_id"] in accepted_ids for item in anchors
            ),
            "anchor_diagnostics": anchor_stats,
            "candidate_videos": stats.get("candidates", 0) + anchor_stats["videos_collected"],
            "kept_videos": stats.get("kept", 0) + anchor_stats["videos_collected"],
            "channels_checked": len(merged),
            "channels_before_italian_verification": len(merged),
            "channels_in_report": len(accepted),
            "confirmed_italian": confirmed,
            "probable_italian": probable,
            "individual_creator": individual,
            "creator_type_uncertain": uncertain,
            "publisher_candidates_excluded": publisher_excluded,
            "excluded_geo": stats.get("excluded_geo", 0),
            "unresolved_channels": stats.get("unresolved_channels", []),
            "sources": stats.get("sources", []),
            "sources_skipped": stats.get("sources_skipped", []),
        },
        "summary": {
            "median_subscribers": round(_median([item["subscribers"] for item in accepted])),
            "median_average_views": round(_median([item["average_views"] for item in accepted])),
            "median_engagement_rate": round(_median([item["engagement_rate"] for item in accepted]), 2),
            "observed_videos": sum(item["observed_videos"] for item in accepted),
            "observed_views": sum(item["total_views"] for item in accepted),
        },
        "subscriber_distribution": _subscriber_distribution(accepted),
        "pool_themes": filtered_themes,
        "circles": filtered_circles,
        "channels": accepted,
        "excluded_or_uncertain": [
            channel for channel in all_classified
            if channel["italian_evidence"]["status"] not in {"confirmed", "probable"}
            or channel["subscribers"] < min_subscribers
            or channel["creator_evidence"]["status"] == "publisher"
        ],
    }


def _fmt(value: int | float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _date(value: str) -> str:
    return value[:10] if value else "n.d."


def markdown_report(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    summary = payload["summary"]
    lines = [
        "# Content creator italiani con almeno 10.000 iscritti",
        "",
        f"Analisi generata da SignalDesk il {payload['generated_at']}.",
        "",
        "> Campione osservato da query YouTube, non censimento completo dei creator italiani.",
        "",
        "## Perimetro e metodo",
        "",
        f"- Query: {', '.join(payload['definition']['include_keywords'])}.",
        f"- Anchor creator: {', '.join(item['channel_title'] for item in payload['definition']['seed_channels']) or 'nessuno'}.",
        f"- Periodo: ultimi {payload['definition']['filters']['date_window_days']} giorni.",
        f"- Soglia: almeno {_fmt(payload['method']['minimum_subscribers'])} iscritti.",
        "- Regione IT e lingua italiana orientano la ricerca; l'italianità viene verificata dopo la raccolta perché il paese dichiarato può riflettere il mercato del canale.",
        "- Italianità confermata da paese/lingua dichiarati; in alternativa classificata probabile da evidenza linguistica.",
        "- Temi e affinità: TF-IDF su titoli, tag, descrizioni video e descrizione canale.",
        "- Score: composito cross-theme, utile per ordinare il campione e non assimilabile a qualità assoluta.",
        "",
        "## Copertura",
        "",
        f"- {coverage['candidate_videos']} video candidati e {coverage['kept_videos']} mantenuti.",
        f"- {coverage['channels_checked']} canali controllati.",
        f"- {coverage['channels_in_report']} canali nel report: {coverage['confirmed_italian']} confermati e {coverage['probable_italian']} probabili.",
        f"- {coverage['anchors_in_report']} anchor presenti su {coverage['anchors_requested']} richiesti.",
        f"- Tipologia canale: {coverage['individual_creator']} creator individuali riconoscibili e {coverage['creator_type_uncertain']} casi da verificare.",
        f"- {coverage['publisher_candidates_excluded']} publisher, testate o aggregatori candidati esclusi.",
        f"- {coverage['excluded_geo']} contenuti esclusi per segnali geo-linguistici o soglia iscritti.",
        "",
        "## Sintesi",
        "",
        "| Canali | Video osservati | Views osservate | Iscritti mediani | Views medie mediane | Engagement mediano |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {coverage['channels_in_report']} | {summary['observed_videos']} | {_fmt(summary['observed_views'])} | {_fmt(summary['median_subscribers'])} | {_fmt(summary['median_average_views'])} | {summary['median_engagement_rate']:.2f}% |",
        "",
        "## Distribuzione per dimensione",
        "",
        "| Fascia iscritti | Canali |",
        "|---|---:|",
        *(f"| {item['label']} | {item['channels']} |" for item in payload["subscriber_distribution"]),
        "",
        "## Canali ordinati per score del campione",
        "",
        "| # | Canale | Origine | Italianità | Tipo | Iscritti | Video osservati | Views medie | Engagement | Score | Temi |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for index, channel in enumerate(payload["channels"], 1):
        status = "Confermata" if channel["italian_evidence"]["status"] == "confirmed" else "Probabile"
        creator_type = "Individuale" if channel["creator_evidence"]["status"] == "individual" else "Da verificare"
        origin = "Anchor" if channel["matched_seed"] == "channel" else "Discovery"
        themes = ", ".join(theme.get("term", "") for theme in channel["themes"][:4]) or "n.d."
        lines.append(
            f"| {index} | {channel['title'].replace('|', '/')} | {origin} | {status} | {creator_type} "
            f"| {_fmt(channel['subscribers'])} | {channel['observed_videos']} "
            f"| {_fmt(channel['average_views'])} | {channel['engagement_rate']:.2f}% "
            f"| {channel['score']:.3f} | {themes.replace('|', '/')} |"
        )
    lines.extend((
        "",
        "## Cerchi emergenti nel campione",
        "",
    ))
    if payload["circles"]:
        for circle in payload["circles"]:
            lines.append(
                f"- **{circle.get('label', 'Senza etichetta')}**: "
                f"{len(circle.get('channels', []))} canali; termini: "
                f"{', '.join(circle.get('label_terms', [])[:6]) or 'n.d.'}."
            )
    else:
        lines.append("Dati insufficienti per costruire cerchi emergenti.")
    lines.extend((
        "",
        "## Come leggere il risultato",
        "",
        "Il report ordina i canali rispetto al pool raccolto. Views, engagement e temi sono calcolati solo sui video osservati. "
        "Canali con un solo video hanno evidenza più fragile; paese e lingua possono non essere dichiarati dal creator. "
        "Prima di usare il report per selezione commerciale è necessaria una verifica manuale dei contenuti di evidenza.",
        "",
    ))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analizza content creator italiani con almeno 10.000 iscritti"
    )
    parser.add_argument("--days", type=int, choices=(30, 90, 365), default=365)
    parser.add_argument("--max-results", type=int, default=300)
    parser.add_argument("--max-channels", type=int, default=100)
    parser.add_argument("--min-subscribers", type=int, default=10_000)
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument(
        "--seed-channel", action="append", dest="seed_channels",
        help="ID UC..., @handle o URL da aggiungere al registry; ripetibile",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--no-default-anchors", action="store_true")
    parser.add_argument("--anchor-videos", type=int, default=10)
    parser.add_argument("--include-popular", action="store_true")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "reports" / "italian-creators-10k",
    )
    args = parser.parse_args()
    queries = args.queries or list(DEFAULT_QUERIES)
    if len(queries) > 10:
        raise SystemExit("Sono consentite al massimo 10 query di discovery")
    if args.min_subscribers < 10_000:
        raise SystemExit("La soglia minima per questo report è 10.000 iscritti")

    load_dotenv(ROOT / ".env")
    if not os.getenv("YOUTUBE_API_KEY"):
        raise SystemExit("YOUTUBE_API_KEY non configurata")
    connector = YouTubeConnector()
    anchors = [] if args.no_default_anchors else load_anchor_registry(args.registry)
    seen_anchors = {item["channel_id"] for item in anchors}
    for reference in args.seed_channels or []:
        channel_id = connector.resolve_channel(reference)
        if not channel_id:
            raise SystemExit(f"Canale anchor non risolvibile: {reference}")
        if channel_id not in seen_anchors:
            anchors.append({"channel_id": channel_id, "name": reference, "category": "custom"})
            seen_anchors.add(channel_id)

    payload = analyze(
        connector,
        queries=queries,
        anchor_channels=anchors,
        days=args.days,
        max_results=max(50, min(args.max_results, 500)),
        max_channels=max(1, min(args.max_channels, 100)),
        min_subscribers=args.min_subscribers,
        videos_per_anchor=max(1, min(args.anchor_videos, 50)),
        include_popular=args.include_popular,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output.with_suffix(".json")
    markdown_path = args.output.with_suffix(".md")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    print(f"Report Markdown: {markdown_path}")
    print(f"Dati JSON: {json_path}")
    print(
        f"Canali inclusi: {payload['coverage']['channels_in_report']} "
        f"({payload['coverage']['confirmed_italian']} confermati, "
        f"{payload['coverage']['probable_italian']} probabili)"
    )


if __name__ == "__main__":
    main()
