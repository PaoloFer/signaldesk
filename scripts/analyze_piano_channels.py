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

from app.ad_detector import detect_ad
from app.connectors import YouTubeConnector
from app.niche_discovery import aggregate_channel_pool
from app.semantic_engine import TfidfEngine


ITALIAN_QUERIES = (
    "pianoforte lezioni",
    "pianoforte tutorial",
    "pianoforte cover",
    "pianista emergente",
)
GLOBAL_QUERIES = (
    "piano lessons",
    "piano tutorial",
    "piano cover",
    "new piano channel",
)
ITALIAN_MARKERS = {
    "pianoforte", "pianista", "lezione", "lezioni", "imparare", "suonare",
    "spartito", "spartiti", "accordi", "esercizi", "italiano", "italiana",
    "tastiera", "brano", "brani", "canzone", "canzoni", "musica",
}


def _matches_italian_market(channel: dict[str, Any]) -> bool:
    country = str(channel.get("country", "")).upper()
    language = str(channel.get("language", "")).lower()
    if country == "IT" or language.startswith("it"):
        return True
    text = " ".join((
        str(channel.get("channel_title", "")),
        str(channel.get("description", "")),
        *(str(video.get("title", "")) + " " + str(video.get("description", ""))
          for video in channel.get("videos", [])),
    )).lower()
    tokens = set(re.findall(r"[a-zà-ú]+", text))
    marker_count = len(tokens & ITALIAN_MARKERS)
    return marker_count >= (4 if country and country != "IT" else 2)


def _collect_market(
    connector: YouTubeConnector,
    *,
    name: str,
    queries: tuple[str, ...],
    days: int,
    max_results: int,
    region_code: str | None,
    language: str | None,
) -> dict[str, Any]:
    video_queries: dict[str, set[str]] = {}
    errors = []
    for query in queries:
        try:
            video_ids = connector.search(
                query=query,
                days=days,
                max_results=max_results,
                region_code=region_code,
                relevance_language=language,
            )
        except Exception as exc:
            errors.append({"query": query, "error": str(exc)})
            continue
        for video_id in video_ids:
            video_queries.setdefault(video_id, set()).add(query)

    acquired_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    contents = connector.fetch_details(
        list(video_queries),
        niche=f"Pianoforte - {name}",
        topic="Pianoforte",
        source_query="",
        acquired_at=acquired_at,
    )
    for content in contents:
        queries_for_video = sorted(video_queries.get(content["external_id"], []))
        content["source_query"] = " | ".join(queries_for_video)
        content["market"] = name

    channel_ids = sorted({content["channel_id"] for content in contents if content.get("channel_id")})
    channel_meta = connector.fetch_channels(channel_ids)
    channels = aggregate_channel_pool(contents, channel_meta)
    if name == "Italia / italiano":
        channels = [channel for channel in channels if _matches_italian_market(channel)]
        accepted_ids = {channel["channel_id"] for channel in channels}
        contents = [content for content in contents if content.get("channel_id") in accepted_ids]

    profiles, _, _ = TfidfEngine().profiles(channels, depth="P2") if channels else ([], {}, 0)
    profiles_by_id = {profile["channel_id"]: profile for profile in profiles}
    content_by_channel: dict[str, list[dict[str, Any]]] = {}
    for content in contents:
        content_by_channel.setdefault(content.get("channel_id", ""), []).append(content)

    for channel in channels:
        profile = profiles_by_id.get(channel["channel_id"], {})
        channel["themes"] = [theme["term"] for theme in profile.get("themes", [])[:6]]
        channel_contents = content_by_channel.get(channel["channel_id"], [])
        assessments = [detect_ad(content) for content in channel_contents]
        channel["commercial_contents"] = sum(assessment["is_commercial"] for assessment in assessments)
        channel["queries"] = sorted({
            query
            for content in channel_contents
            for query in content.get("source_query", "").split(" | ")
            if query
        })

    channels.sort(key=lambda item: item.get("channel_published_at") or "0000", reverse=True)
    return {
        "name": name,
        "queries": list(queries),
        "errors": errors,
        "videos_found": len(contents),
        "channels_found": len(channels),
        "channels": channels,
        "contents": contents,
    }


def _date(value: str) -> str:
    return value[:10] if value else "n.d."


def _top_themes(channels: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return Counter(theme for channel in channels for theme in channel.get("themes", [])).most_common(12)


def _channel_table(channels: list[dict[str, Any]], limit: int = 20) -> list[str]:
    lines = [
        "| # | Canale | Creato | Iscritti | Video osservati | Views medie | Engagement | Temi | ADV |",
        "|---:|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for index, channel in enumerate(channels[:limit], 1):
        title = str(channel.get("channel_title") or channel.get("channel_id", "")).replace("|", "/")
        themes = ", ".join(channel.get("themes", [])[:4]).replace("|", "/") or "n.d."
        lines.append(
            f"| {index} | {title} | {_date(channel.get('channel_published_at', ''))} "
            f"| {channel.get('subscribers', 0):,} | {channel.get('video_count', 0)} "
            f"| {channel.get('avg_views', 0):,} | {channel.get('engagement_rate', 0) * 100:.2f}% "
            f"| {themes} | {channel.get('commercial_contents', 0)} |"
        )
    return lines


def _market_summary(market: dict[str, Any]) -> dict[str, Any]:
    channels = market["channels"]
    recent = [channel for channel in channels if (channel.get("channel_published_at") or "") >= "2022-01-01"]
    return {
        "market": market["name"],
        "videos": market["videos_found"],
        "channels": market["channels_found"],
        "channels_since_2022": len(recent),
        "median_subscribers": _median([channel.get("subscribers", 0) for channel in channels]),
        "median_avg_views": _median([channel.get("avg_views", 0) for channel in channels]),
        "themes": _top_themes(channels),
    }


def _creation_cohorts(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = (
        ("2025-2026", "2025-01-01", "9999"),
        ("2022-2024", "2022-01-01", "2025-01-01"),
        ("2018-2021", "2018-01-01", "2022-01-01"),
        ("Prima del 2018", "0000", "2018-01-01"),
    )
    cohorts = []
    for label, start, end in definitions:
        items = [channel for channel in channels if start <= (channel.get("channel_published_at") or "0000") < end]
        cohorts.append({
            "label": label,
            "channels": len(items),
            "median_subscribers": _median([item.get("subscribers", 0) for item in items]),
            "median_avg_views": _median([item.get("avg_views", 0) for item in items]),
        })
    return cohorts


def _format_mix(contents: list[dict[str, Any]]) -> list[tuple[str, int]]:
    formats = Counter()
    for content in contents:
        duration = int(content.get("duration_seconds", 0) or 0)
        if duration <= 180:
            formats["Breve ≤3 min"] += 1
        elif duration <= 900:
            formats["Medio 3-15 min"] += 1
        else:
            formats["Lungo >15 min"] += 1
    return formats.most_common()


def _candidate_table(channels: list[dict[str, Any]], limit: int = 10) -> list[str]:
    recent = [channel for channel in channels if (channel.get("channel_published_at") or "") >= "2022-01-01"]
    recent.sort(
        key=lambda channel: (
            channel.get("video_count", 0) >= 2,
            channel.get("avg_views", 0),
            channel.get("engagement_rate", 0),
        ),
        reverse=True,
    )
    lines = [
        "| Canale | Creato | Evidenza | Views medie | Iscritti | Engagement | Lettura |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for channel in recent[:limit]:
        observed = int(channel.get("video_count", 0))
        reading = "Più solido nel campione" if observed >= 2 else "Esplorativo: un solo video"
        title = str(channel.get("channel_title") or channel.get("channel_id", "")).replace("|", "/")
        lines.append(
            f"| {title} | {_date(channel.get('channel_published_at', ''))} | {observed} video "
            f"| {channel.get('avg_views', 0):,} | {channel.get('subscribers', 0):,} "
            f"| {channel.get('engagement_rate', 0) * 100:.2f}% | {reading} |"
        )
    if len(lines) == 2:
        lines.append("| Nessun canale recente nel campione | - | - | - | - | - | - |")
    return lines


def _median(values: list[int]) -> int:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def _markdown_report(payload: dict[str, Any]) -> str:
    generated = payload["generated_at"]
    summaries = [_market_summary(market) for market in payload["markets"]]
    lines = [
        "# Nuovi canali YouTube nella nicchia pianoforte",
        "",
        f"Analisi generata da SignalDesk il {generated}.",
        "",
        "## Metodo",
        "",
        "- Due corpus separati: Italia/italiano e globale/inglese.",
        "- Il corpus italiano filtra per paese/lingua dichiarati oppure per segnali lessicali italiani; regione e lingua YouTube da sole non sono filtri rigidi.",
        "- I canali sono ordinati dalla data ufficiale di creazione YouTube più recente alla meno recente.",
        "- La discovery parte da video recenti trovati per query: non è un censimento completo di YouTube.",
        "- Views ed engagement sono calcolati solo sui video osservati nel campione.",
        "- I temi sono profili TF-IDF spiegabili su titoli, tag e descrizioni dei video osservati.",
        "- I segnali ADV sono screening euristici e richiedono verifica manuale.",
        "",
        "## Sintesi comparativa",
        "",
        "| Mercato | Video | Canali | Creati dal 2022 | Iscritti mediani | Views medie mediane | Temi ricorrenti |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for summary in summaries:
        themes = ", ".join(theme for theme, _ in summary["themes"][:6]) or "n.d."
        lines.append(
            f"| {summary['market']} | {summary['videos']} | {summary['channels']} | "
            f"{summary['channels_since_2022']} | {summary['median_subscribers']:,} | "
            f"{summary['median_avg_views']:,} | {themes} |"
        )

    for market in payload["markets"]:
        lines.extend((
            "",
            f"## {market['name']}: canali dal più recente",
            "",
            *_channel_table(market["channels"]),
            "",
            "### Temi più ricorrenti",
            "",
            ", ".join(f"{theme} ({count})" for theme, count in _top_themes(market["channels"])) or "Dati insufficienti.",
            "",
            "### Canali recenti da approfondire",
            "",
            "La shortlist privilegia prima i canali con almeno due video osservati, poi views medie ed engagement. Non è un punteggio assoluto di qualità.",
            "",
            *_candidate_table(market["channels"]),
            "",
            "### Età del canale e metriche del campione",
            "",
            "| Coorte | Canali | Iscritti mediani | Views medie mediane |",
            "|---|---:|---:|---:|",
            *(f"| {cohort['label']} | {cohort['channels']} | {cohort['median_subscribers']:,} | {cohort['median_avg_views']:,} |"
              for cohort in _creation_cohorts(market["channels"])),
            "",
            "### Mix dei formati osservati",
            "",
            ", ".join(f"{label}: {count}" for label, count in _format_mix(market["contents"])) or "Dati insufficienti.",
        ))
        if market["errors"]:
            lines.extend(("", f"Query non completate: {len(market['errors'])}. Vedi il file JSON per i dettagli."))

    lines.extend((
        "",
        "## Come leggere il risultato",
        "",
        "I canali in alto sono i più recenti per data di apertura, non necessariamente quelli con la crescita più rapida. "
        "Per valutare opportunità reali vanno incrociati anno di creazione, views medie del campione, engagement, "
        "coerenza tematica e continuità di pubblicazione. Un solo video virale può alzare fortemente la media.",
        "",
    ))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analizza i nuovi canali YouTube nella nicchia pianoforte")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "piano-channels")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if not os.getenv("YOUTUBE_API_KEY"):
        raise SystemExit("YOUTUBE_API_KEY non configurata")

    connector = YouTubeConnector()
    markets = [
        _collect_market(
            connector,
            name="Italia / italiano",
            queries=ITALIAN_QUERIES,
            days=args.days,
            max_results=args.max_results,
            region_code="IT",
            language="it",
        ),
        _collect_market(
            connector,
            name="Globale / inglese",
            queries=GLOBAL_QUERIES,
            days=args.days,
            max_results=args.max_results,
            region_code=None,
            language="en",
        ),
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "parameters": {"days": args.days, "max_results_per_query": args.max_results},
        "markets": markets,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output.with_suffix(".json")
    markdown_path = args.output.with_suffix(".md")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown_report(payload), encoding="utf-8")
    print(f"Report Markdown: {markdown_path}")
    print(f"Dati JSON: {json_path}")


if __name__ == "__main__":
    main()
