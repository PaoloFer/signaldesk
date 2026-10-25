from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_text(value: str) -> str:
    value = re.sub(r"https?://\S+", " url ", value.lower())
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _hour_bucket(value: str) -> datetime:
    return _parse_date(value).replace(minute=0, second=0, microsecond=0)


def _clusters(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        normalized = normalize_text(comment["text"])
        if normalized:
            groups[normalized].append(comment)

    result = []
    for normalized, items in groups.items():
        if len(items) < 3:
            continue
        result.append({
            "text": items[0]["text"],
            "normalized": normalized,
            "comments": len(items),
            "authors": len({item["author_hash"] for item in items}),
            "contents": len({item["content_id"] for item in items}),
        })
    return sorted(result, key=lambda item: item["comments"], reverse=True)


def _author_signals(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    authors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        authors[comment["author_hash"]].append(comment)

    results = []
    for author, items in authors.items():
        if len(items) < 3:
            continue
        reasons = []
        score = 0
        normalized = [normalize_text(item["text"]) for item in items]
        repeated = len(normalized) - len(set(normalized))
        contents = len({item["content_id"] for item in items})
        dates = sorted(_parse_date(item["published_at"]) for item in items)
        span_minutes = (dates[-1] - dates[0]).total_seconds() / 60
        if len(items) >= 5:
            score += 25
            reasons.append(f"{len(items)} commenti nel periodo")
        if repeated >= 2:
            score += 30
            reasons.append(f"{repeated + 1} testi ripetuti")
        if contents >= 2:
            score += 20
            reasons.append(f"attività su {contents} contenuti")
        if len(items) >= 4 and span_minutes <= 15:
            score += 25
            reasons.append(f"attività concentrata in {round(span_minutes)} minuti")
        if score >= 40:
            results.append({"author": author, "score": score, "reasons": reasons})
    return sorted(results, key=lambda item: item["score"], reverse=True)


def _niche_report(
    comments: list[dict[str, Any]], comparison_names: tuple[str, str] | None = None
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        grouped[comment.get("niche") or "Non classificata"].append(comment)

    niches = []
    for name, items in grouped.items():
        topic_counts = Counter(item.get("topic") or "Altro" for item in items)
        niches.append({
            "name": name,
            "comments": len(items),
            "authors": len({item["author_hash"] for item in items}),
            "topics": [{"name": topic, "count": count} for topic, count in topic_counts.most_common(5)],
        })
    niches.sort(key=lambda item: item["comments"], reverse=True)

    comparison = None
    if len(niches) >= 2:
        selected = niches[:2]
        if comparison_names:
            by_name = {item["name"]: item for item in niches}
            if all(name in by_name for name in comparison_names):
                selected = [by_name[comparison_names[0]], by_name[comparison_names[1]]]
        left, right = selected
        left_items, right_items = grouped[left["name"]], grouped[right["name"]]
        left_authors = {item["author_hash"] for item in left_items}
        right_authors = {item["author_hash"] for item in right_items}
        left_topics = {item.get("topic") or "Altro" for item in left_items}
        right_topics = {item.get("topic") or "Altro" for item in right_items}
        author_union = left_authors | right_authors
        comparison = {
            "left": left["name"],
            "right": right["name"],
            "audience_overlap": round(len(left_authors & right_authors) / len(author_union) * 100) if author_union else 0,
            "shared_topics": sorted(left_topics & right_topics),
        }
    return {"items": niches, "comparison": comparison}


def build_intelligence_report(
    raw_comments: Iterable[dict[str, Any]], now: datetime | None = None,
    days: int = 14, niche: str | None = None,
    comparison_names: tuple[str, str] | None = None,
) -> dict[str, Any]:
    comments = list(raw_comments)
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    recent = [item for item in comments if _parse_date(item["published_at"]) >= start]
    if niche:
        recent = [item for item in recent if item.get("niche") == niche]
    if not recent:
        return {
            "metrics": {"comments": 0, "authors": 0, "anomalies": 0, "coordinated_share": 0},
            "activity": {"hours": [0] * 24, "days": [0] * 7, "peak_hour": None},
            "events": [], "clusters": [], "authors": [],
            "niches": {"items": [], "comparison": None},
        }

    hours = Counter(_parse_date(item["published_at"]).hour for item in recent)
    days = Counter(_parse_date(item["published_at"]).weekday() for item in recent)
    bucketed: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for item in recent:
        bucketed[_hour_bucket(item["published_at"])].append(item)
    non_empty_counts = [len(items) for items in bucketed.values()]
    expected = max(float(median(non_empty_counts)), 1.0)
    threshold = max(8, expected * 3)
    events = []
    for bucket, items in bucketed.items():
        if len(items) < threshold:
            continue
        event_clusters = _clusters(items)
        duplicate_comments = sum(cluster["comments"] for cluster in event_clusters)
        ratio = duplicate_comments / len(items) if items else 0
        multiplier = round(len(items) / expected, 1)
        confidence = min(95, round(35 + ratio * 45 + min(multiplier, 8) * 2))
        events.append({
            "started_at": bucket.isoformat(),
            "content_id": Counter(item["content_id"] for item in items).most_common(1)[0][0],
            "content_title": Counter(item["content_title"] for item in items).most_common(1)[0][0],
            "comments": len(items),
            "expected": round(expected, 1),
            "multiplier": multiplier,
            "confidence": confidence,
            "observed": f"{len(items)} commenti concentrati in un'ora",
            "calculated": f"Volume {multiplier}x rispetto alle ore attive tipiche",
            "estimated": "Segnali di coordinamento elevati" if confidence >= 70 else "Evento da verificare",
        })
    events.sort(key=lambda item: item["comments"], reverse=True)

    clusters = _clusters(recent)
    suspicious_ids = {cluster["normalized"] for cluster in clusters}
    coordinated_count = sum(1 for item in recent if normalize_text(item["text"]) in suspicious_ids)
    peak_hour = hours.most_common(1)[0][0] if hours else None
    return {
        "generated_at": now.isoformat(),
        "metrics": {
            "comments": len(recent),
            "authors": len({item["author_hash"] for item in recent}),
            "anomalies": len(events),
            "coordinated_share": round(coordinated_count / len(recent) * 100),
        },
        "activity": {
            "hours": [hours[index] for index in range(24)],
            "days": [days[index] for index in range(7)],
            "peak_hour": peak_hour,
        },
        "events": events[:8],
        "clusters": clusters[:8],
        "authors": _author_signals(recent)[:8],
        "niches": _niche_report(recent, comparison_names),
    }
