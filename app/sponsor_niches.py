"""Nicchie definite dagli sponsor e profili dei rispettivi bacini (N7)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.channel_profiling import compute_channel_profiles, pool_themes
from app.content_intelligence import classify_content
from app.database import (
    get_entity,
    list_channel_profiles,
    sponsor_basin_contents,
    sponsored_channels_by_entity,
)
from app.niche_discovery import aggregate_channel_pool


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(
        microsecond=0
    ).isoformat()


def _subscriber_band(value: int) -> str:
    if value < 10_000:
        return "<10k"
    if value < 100_000:
        return "10k–100k"
    if value < 1_000_000:
        return "100k–1M"
    return ">1M"


def build_sponsor_basin_profile(
    project_id: int,
    entity_id: int,
    *,
    days: int = 365,
    niche: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Profilo locale dei creator scelti da un brand, senza consumo quota."""
    entity = get_entity(entity_id)
    if not entity or entity["project_id"] != project_id:
        raise ValueError("Entità non trovata nel progetto")
    if entity["type"] not in {"brand", "organization"}:
        raise ValueError("Il bacino sponsor richiede un brand o un'organizzazione")
    since = _since(days)
    sponsorships = sponsored_channels_by_entity(
        project_id, entity_id, since=since, niche=niche, platform=platform,
    )
    contents = sponsor_basin_contents(
        project_id, entity_id, since=since, platform=platform,
    )
    known_profiles = {
        (item["platform"], item["channel_id"]): item
        for item in list_channel_profiles(project_id, platform=platform)
    }
    channel_meta = {
        channel_id: {
            "title": profile["channel_title"],
            "custom_url": profile["custom_url"],
            "description": profile["description"],
            "country": profile["country"],
            "default_language": profile["language"],
            "subscribers": profile["subscribers"],
            "video_count": profile["declared_video_count"],
        }
        for (_, channel_id), profile in known_profiles.items()
    }
    channels = aggregate_channel_pool(contents, channel_meta)
    sponsorship_by_key = {
        (row["platform"], row["channel_id"]): row for row in sponsorships
    }
    max_sponsored = max(
        (int(row["sponsored_contents"]) for row in sponsorships), default=1
    )
    profiles, _, _ = compute_channel_profiles(channels)
    profile_by_id = {profile["channel_id"]: profile for profile in profiles}
    for channel in channels:
        sponsor = sponsorship_by_key.get(
            (channel.get("platform", "YouTube"), channel["channel_id"]), {}
        )
        semantic = profile_by_id.get(channel["channel_id"], {})
        channel["themes"] = semantic.get("themes", [])
        channel["anomalous_videos"] = semantic.get("anomalous_videos", 0)
        channel["sponsored_contents"] = int(sponsor.get("sponsored_contents", 0))
        channel["sponsored_views"] = int(sponsor.get("sponsored_views", 0) or 0)
        channel["average_confidence"] = round(
            float(sponsor.get("average_confidence", 0) or 0), 3
        )
        channel["has_declared_placement"] = bool(
            sponsor.get("has_declared_placement", 0)
        )
        channel["score"] = round(channel["sponsored_contents"] / max_sponsored, 4)

    subscriber_bands = Counter(
        _subscriber_band(int(channel.get("subscribers", 0) or 0)) for channel in channels
    )
    countries = Counter(channel.get("country") or "unknown" for channel in channels)
    languages = Counter(channel.get("language") or "unknown" for channel in channels)
    platforms = Counter(channel.get("platform") or "unknown" for channel in channels)
    formats: Counter[str] = Counter()
    purposes: Counter[str] = Counter()
    for content in contents:
        classification = classify_content(content)
        formats[classification["format"]] += 1
        purposes.update(classification["purposes"])
    weighted_views = sum(int(content.get("views", 0) or 0) for content in contents)
    interactions = sum(
        int(content.get("likes", 0) or 0) + int(content.get("comments", 0) or 0)
        for content in contents
    )
    return {
        "entity": entity,
        "metrics": {
            "channels": len(channels),
            "sponsored_contents": sum(c["sponsored_contents"] for c in channels),
            "observed_contents": len(contents),
            "total_views": weighted_views,
            "weighted_engagement_rate": round(
                interactions / weighted_views, 5
            ) if weighted_views else 0.0,
        },
        "subscriber_bands": [
            {"name": name, "channels": count} for name, count in subscriber_bands.items()
        ],
        "countries": [{"name": name, "channels": count} for name, count in countries.most_common()],
        "languages": [{"name": name, "channels": count} for name, count in languages.most_common()],
        "platforms": [{"name": name, "channels": count} for name, count in platforms.most_common()],
        "formats": [{"name": name, "contents": count} for name, count in formats.most_common()],
        "purposes": [{"name": name, "contents": count} for name, count in purposes.most_common()],
        "dominant_themes": pool_themes(
            [profile.get("vector") or {} for profile in profiles], min_channels=1,
        ),
        "channels": sorted(
            channels, key=lambda item: (-item["sponsored_contents"], -item["sponsored_views"])
        ),
        "contents": contents,
    }


def compare_sponsor_basins(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def keys(profile: dict[str, Any]) -> set[str]:
        return {
            f"{channel.get('platform', 'YouTube')}:{channel['channel_id']}"
            for channel in profile["channels"]
        }

    left_keys = keys(left)
    right_keys = keys(right)
    common = left_keys & right_keys
    union = left_keys | right_keys
    return {
        "left": {"entity": left["entity"], "metrics": left["metrics"],
                 "dominant_themes": left["dominant_themes"][:12]},
        "right": {"entity": right["entity"], "metrics": right["metrics"],
                  "dominant_themes": right["dominant_themes"][:12]},
        "overlap": {
            "channels": len(common),
            "jaccard": round(len(common) / len(union), 4) if union else 0.0,
            "common": sorted(common),
            "left_only": sorted(left_keys - right_keys),
            "right_only": sorted(right_keys - left_keys),
        },
    }
