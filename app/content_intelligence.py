from __future__ import annotations

import re
import json
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


STOPWORDS = {
    "anche", "come", "dalla", "dalle", "dello", "della", "degli", "delle", "dopo",
    "sono", "questo", "questa", "quello", "quella", "quando", "perche", "perché",
    "video", "guida", "tutto", "tutti", "fare", "cosa", "solo", "senza", "molto",
    "with", "from", "that", "this", "your", "what", "when", "have", "will", "about",
}

PURPOSE_RULES = {
    "Podcast": ("podcast", "episodio", "puntata"),
    "Intervista": ("intervista", "interview", "ospite"),
    "Tutorial / informativo": ("tutorial", "guida", "come fare", "spiegato", "consigli"),
    "Recensione / confronto": ("recensione", "review", "confronto", "versus", " test "),
    "Documentario / inchiesta": ("documentario", "inchiesta", "reportage", "la storia di"),
    "Intrattenimento": ("challenge", "reaction", "reazione", "vlog", "divertente"),
}

COMMERCIAL_RULES = {
    "hashtag pubblicitario": ("#ad", "#adv", "#sponsored"),
    "dichiarazione sponsor": ("sponsorizzato", "sponsored by", "in collaborazione con", "partnership con"),
    "codice promozionale": ("codice sconto", "codice promo", "coupon"),
    "link affiliato": ("affiliate", "affiliazione", "amzn.to/", "amazon.it/", "bit.ly/"),
}


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def extract_terms(value: str) -> set[str]:
    words = re.findall(r"[^\W\d_]{4,}", value.lower(), flags=re.UNICODE)
    return {word for word in words if word not in STOPWORDS}


def _term_counts(contents: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in contents:
        counts.update(extract_terms(f"{item.get('title', '')} {item.get('description', '')}"))
    return counts


def _tags(item: dict[str, Any]) -> list[str]:
    value = item.get("tags_json", "[]")
    if isinstance(value, list):
        return [str(tag) for tag in value]
    try:
        parsed = json.loads(value or "[]")
        return [str(tag) for tag in parsed] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def classify_content(item: dict[str, Any]) -> dict[str, Any]:
    duration = int(item.get("duration_seconds", 0))
    content_format = "Breve ≤3 min (proxy)" if duration <= 180 else "Medio 3–15 min" if duration <= 900 else "Lungo >15 min"
    text = " ".join((item.get("title", ""), item.get("description", ""), " ".join(_tags(item)))).lower()
    purposes = [
        label for label, signals in PURPOSE_RULES.items()
        if any(signal in text for signal in signals)
    ] or ["Non classificato"]
    commercial = [
        label for label, signals in COMMERCIAL_RULES.items()
        if any(signal in text for signal in signals)
    ]
    return {"format": content_format, "purposes": purposes, "commercial_signals": commercial}


def _relationship_graph(contents: list[dict[str, Any]]) -> dict[str, Any]:
    niche_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    niche_channels: Counter[tuple[str, str]] = Counter()
    channel_topics: Counter[tuple[str, str]] = Counter()
    channel_niches: dict[str, set[str]] = defaultdict(set)
    topic_niches: dict[str, set[str]] = defaultdict(set)
    for item in contents:
        niche = item.get("niche") or "Non classificata"
        channel = item.get("channel_title") or "Canale sconosciuto"
        topic = item.get("topic") or item.get("source_query") or "Altro"
        niche_counts[niche] += 1
        channel_counts[channel] += 1
        topic_counts[topic] += 1
        niche_channels[(niche, channel)] += 1
        channel_topics[(channel, topic)] += 1
        channel_niches[channel].add(niche)
        topic_niches[topic].add(niche)

    selected_niches = {name for name, _ in niche_counts.most_common(6)}
    selected_channels = {name for name, _ in channel_counts.most_common(12)}
    selected_topics = {name for name, _ in topic_counts.most_common(12)}

    def identifier(kind: str, label: str) -> str:
        digest = hashlib.sha1(f"{kind}:{label}".encode()).hexdigest()[:10]
        return f"{kind}-{digest}"

    nodes = []
    for kind, counts, selected in (
        ("niche", niche_counts, selected_niches),
        ("channel", channel_counts, selected_channels),
        ("topic", topic_counts, selected_topics),
    ):
        nodes.extend(
            {"id": identifier(kind, label), "label": label, "type": kind, "size": counts[label]}
            for label in selected
        )
    edges = [
        {"source": identifier("niche", niche), "target": identifier("channel", channel), "weight": weight}
        for (niche, channel), weight in niche_channels.items()
        if niche in selected_niches and channel in selected_channels
    ]
    edges.extend(
        {"source": identifier("channel", channel), "target": identifier("topic", topic), "weight": weight}
        for (channel, topic), weight in channel_topics.items()
        if channel in selected_channels and topic in selected_topics
    )
    bridges = [
        {"type": "channel", "name": name, "niches": sorted(niches)}
        for name, niches in channel_niches.items() if len(niches) > 1
    ]
    bridges.extend(
        {"type": "topic", "name": name, "niches": sorted(niches)}
        for name, niches in topic_niches.items() if len(niches) > 1
    )
    bridges.sort(key=lambda item: (len(item["niches"]), item["name"]), reverse=True)
    return {"nodes": nodes, "edges": edges, "bridges": bridges[:12]}


def _platform_report(contents: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in contents:
        grouped[item.get("platform") or "Non specificata"].append(item)
    items = []
    for platform, platform_contents in grouped.items():
        items.append({
            "name": platform,
            "contents": len(platform_contents),
            "views": sum(int(item.get("views", 0)) for item in platform_contents),
            "interactions": sum(int(item.get("likes", 0)) + int(item.get("comments", 0)) for item in platform_contents),
            "channels": len({item.get("channel_id") or item.get("channel_title") for item in platform_contents}),
        })
    items.sort(key=lambda item: item["contents"], reverse=True)
    comparison = None
    if len(items) >= 2:
        left, right = items[:2]
        left_terms = _term_counts(grouped[left["name"]])
        right_terms = _term_counts(grouped[right["name"]])
        left_top = {term for term, _ in left_terms.most_common(20)}
        right_top = {term for term, _ in right_terms.most_common(20)}
        comparison = {
            "left": left["name"], "right": right["name"],
            "shared_terms": sorted(left_top & right_top, key=lambda term: left_terms[term] + right_terms[term], reverse=True)[:8],
            "distinctive_left": [term for term, _ in left_terms.most_common(20) if term not in right_top][:6],
            "distinctive_right": [term for term, _ in right_terms.most_common(20) if term not in left_top][:6],
        }
    return {"items": items, "comparison": comparison}


def _comparison(
    contents: list[dict[str, Any]], names: tuple[str, str] | None
) -> dict[str, Any] | None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in contents:
        grouped[item.get("niche") or "Non classificata"].append(item)
    ordered = sorted(grouped, key=lambda name: len(grouped[name]), reverse=True)
    if len(ordered) < 2:
        return None
    left, right = ordered[:2]
    if names and names[0] in grouped and names[1] in grouped and names[0] != names[1]:
        left, right = names
    left_terms, right_terms = _term_counts(grouped[left]), _term_counts(grouped[right])
    left_top = {term for term, _ in left_terms.most_common(20)}
    right_top = {term for term, _ in right_terms.most_common(20)}
    shared = sorted(left_top & right_top, key=lambda term: left_terms[term] + right_terms[term], reverse=True)
    left_channels = {item.get("channel_id") for item in grouped[left] if item.get("channel_id")}
    right_channels = {item.get("channel_id") for item in grouped[right] if item.get("channel_id")}
    channel_union = left_channels | right_channels
    return {
        "left": left,
        "right": right,
        "shared_terms": shared[:8],
        "distinctive_left": [term for term, _ in left_terms.most_common(20) if term not in right_top][:6],
        "distinctive_right": [term for term, _ in right_terms.most_common(20) if term not in left_top][:6],
        "channel_overlap": round(len(left_channels & right_channels) / len(channel_union) * 100) if channel_union else 0,
        "sample_left": len(grouped[left]),
        "sample_right": len(grouped[right]),
    }


def build_content_report(
    raw_contents: Iterable[dict[str, Any]], now: datetime | None = None,
    days: int = 30, niche: str | None = None,
    comparison_names: tuple[str, str] | None = None,
    raw_snapshots: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    period_contents = [item for item in raw_contents if _parse_date(item["published_at"]) >= start]
    comparison = _comparison(period_contents, comparison_names)
    contents = period_contents
    if niche:
        contents = [item for item in contents if item.get("niche") == niche]
    if not contents:
        return {
            "metrics": {"contents": 0, "real_contents": 0, "demo_contents": 0, "channels": 0, "views": 0, "interactions": 0, "tracked": 0},
            "timeline": [], "top_contents": [], "channels": [], "topics": [], "terms": [],
            "durations": [], "queries": [], "niches": [], "comparison": comparison,
            "trajectories": [], "last_updated": None,
            "taxonomy": {"formats": [], "purposes": [], "tags": []},
            "commercial_signals": {"contents": 0, "items": []},
            "graph": {"nodes": [], "edges": [], "bridges": []},
            "platforms": {"items": [], "comparison": None},
        }

    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"contents": 0, "views": 0})
    by_channel: dict[str, dict[str, Any]] = {}
    topic_counts: Counter[str] = Counter()
    niche_counts: Counter[str] = Counter()
    duration_counts: Counter[str] = Counter()
    query_data: dict[str, dict[str, Any]] = {}
    format_counts: Counter[str] = Counter()
    purpose_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    commercial_items = []
    enriched = []
    for item in contents:
        day = _parse_date(item["published_at"]).date().isoformat()
        by_day[day]["contents"] += 1
        by_day[day]["views"] += int(item["views"])
        channel = item.get("channel_title") or "Canale sconosciuto"
        channel_data = by_channel.setdefault(channel, {"name": channel, "contents": 0, "views": 0, "interactions": 0})
        channel_data["contents"] += 1
        channel_data["views"] += int(item["views"])
        channel_data["interactions"] += int(item["likes"]) + int(item["comments"])
        topic_counts[item.get("topic") or item.get("source_query") or "Altro"] += 1
        niche_counts[item.get("niche") or "Non classificata"] += 1
        duration = int(item.get("duration_seconds", 0))
        duration_label = "< 1 min" if duration < 60 else "1-5 min" if duration < 300 else "5-15 min" if duration < 900 else "> 15 min"
        duration_counts[duration_label] += 1
        classification = classify_content(item)
        format_counts[classification["format"]] += 1
        purpose_counts.update(classification["purposes"])
        tag_counts.update(set(_tags(item)))
        if classification["commercial_signals"]:
            commercial_items.append({
                "external_id": item["external_id"], "title": item["title"],
                "channel_title": item.get("channel_title", ""),
                "signals": classification["commercial_signals"],
            })
        query = item.get("source_query") or "Importazione diretta"
        query_entry = query_data.setdefault(query, {"query": query, "contents": 0, "last_acquired": item.get("acquired_at", "")})
        query_entry["contents"] += 1
        query_entry["last_acquired"] = max(query_entry["last_acquired"], item.get("acquired_at", ""))
        engagement = ((int(item["likes"]) + int(item["comments"])) / int(item["views"]) * 100) if int(item["views"]) else 0
        enriched.append({**item, "engagement_rate": round(engagement, 2)})

    channels = []
    for data in by_channel.values():
        data["average_views"] = round(data["views"] / data["contents"])
        channels.append(data)
    channels.sort(key=lambda item: item["views"], reverse=True)
    enriched.sort(key=lambda item: int(item["views"]), reverse=True)
    content_by_id = {item["external_id"]: item for item in contents}
    snapshot_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in raw_snapshots:
        if snapshot["external_id"] in content_by_id and _parse_date(snapshot["captured_at"]) >= start:
            snapshot_groups[snapshot["external_id"]].append(snapshot)
    trajectories = []
    for external_id, snapshots in snapshot_groups.items():
        snapshots.sort(key=lambda item: _parse_date(item["captured_at"]))
        if len(snapshots) < 2:
            continue
        first, last = snapshots[0], snapshots[-1]
        elapsed_days = max((_parse_date(last["captured_at"]) - _parse_date(first["captured_at"])).total_seconds() / 86400, 1 / 24)
        view_change = int(last["views"]) - int(first["views"])
        trajectories.append({
            "external_id": external_id,
            "title": content_by_id[external_id]["title"],
            "channel_title": content_by_id[external_id].get("channel_title", ""),
            "first_views": int(first["views"]),
            "last_views": int(last["views"]),
            "view_change": view_change,
            "growth_percent": round(view_change / int(first["views"]) * 100, 1) if int(first["views"]) else 0,
            "views_per_day": round(view_change / elapsed_days),
            "observations": len(snapshots),
            "from_at": first["captured_at"],
            "to_at": last["captured_at"],
            "is_demo": external_id.startswith("demo-"),
        })
    trajectories.sort(key=lambda item: item["views_per_day"], reverse=True)
    all_snapshot_dates = [item["captured_at"] for items in snapshot_groups.values() for item in items]
    return {
        "metrics": {
            "contents": len(contents),
            "real_contents": sum(1 for item in contents if not item["external_id"].startswith("demo-")),
            "demo_contents": sum(1 for item in contents if item["external_id"].startswith("demo-")),
            "channels": len(by_channel),
            "views": sum(int(item["views"]) for item in contents),
            "interactions": sum(int(item["likes"]) + int(item["comments"]) for item in contents),
            "tracked": len(trajectories),
        },
        "timeline": [{"date": date, **values} for date, values in sorted(by_day.items())],
        "top_contents": enriched[:10],
        "channels": channels[:10],
        "topics": [{"name": name, "contents": count} for name, count in topic_counts.most_common(10)],
        "terms": [{"name": name, "documents": count} for name, count in _term_counts(contents).most_common(15)],
        "durations": [{"label": label, "contents": duration_counts[label]} for label in ("< 1 min", "1-5 min", "5-15 min", "> 15 min")],
        "queries": sorted(query_data.values(), key=lambda item: item["contents"], reverse=True),
        "niches": [{"name": name, "contents": count} for name, count in niche_counts.most_common()],
        "comparison": comparison,
        "trajectories": trajectories[:10],
        "last_updated": max(all_snapshot_dates) if all_snapshot_dates else None,
        "taxonomy": {
            "formats": [{"name": name, "contents": count} for name, count in format_counts.most_common()],
            "purposes": [{"name": name, "contents": count} for name, count in purpose_counts.most_common()],
            "tags": [{"name": name, "documents": count} for name, count in tag_counts.most_common(15)],
        },
        "commercial_signals": {"contents": len(commercial_items), "items": commercial_items[:10]},
        "graph": _relationship_graph(contents),
        "platforms": _platform_report(contents),
    }
