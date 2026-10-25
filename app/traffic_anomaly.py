"""Rilevamento anomalie di traffico sui contenuti.

Le anomalie di crescita/engagement sono un segnale indiretto di promozione
paid (boost del video o campagna coordinata) anche in assenza di tag #adv.
Il modulo lavora solo su dati già raccolti (contenuti + snapshot metrici),
quindi non ha costi aggiuntivi: è il primo filtro del funnel di indagine
sponsor e seleziona i candidati per le analisi premium (trascrizioni, frame).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable


MIN_BASELINE_VIDEOS = 3
DEFAULT_Z_THRESHOLD = 2.5

GROWTH_ORGANIC = "organico"
GROWTH_LINEAR = "lineare"
GROWTH_LATE_SPIKE = "spike_tardivo"
GROWTH_FLAT = "piatto"
GROWTH_INSUFFICIENT_DATA = "dati_insufficienti"


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mad(values: list[float], center: float) -> float:
    """Median Absolute Deviation: misura di dispersione robusta agli outlier."""
    if not values:
        return 0.0
    return float(median([abs(value - center) for value in values]))


def _robust_zscore(value: float, center: float, mad: float) -> float | None:
    """Z-score robusto basato su mediana e MAD (0.6745 = costante di consistenza)."""
    if mad <= 0:
        return None
    return round(0.6745 * (value - center) / mad, 2)


def _engagement_per_1k(views: int, likes: int, comments: int) -> float | None:
    if views <= 0:
        return None
    return (likes + comments) / views * 1000


def _baseline_stats(videos: list[dict[str, Any]]) -> dict[str, Any] | None:
    views_values = [float(int(v.get("views", 0))) for v in videos if int(v.get("views", 0)) > 0]
    if len(views_values) < MIN_BASELINE_VIDEOS:
        return None
    engagement_values = [
        engagement
        for engagement in (
            _engagement_per_1k(
                int(v.get("views", 0)), int(v.get("likes", 0)), int(v.get("comments", 0))
            )
            for v in videos
        )
        if engagement is not None
    ]
    views_center = float(median(views_values))
    engagement_center = float(median(engagement_values)) if engagement_values else None
    return {
        "videos": len(views_values),
        "views_median": views_center,
        "views_mad": _mad(views_values, views_center),
        "engagement_median": engagement_center,
        "engagement_mad": (
            _mad(engagement_values, engagement_center) if engagement_center is not None else 0.0
        ),
    }


def compute_channel_baselines(contents: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Mediana e MAD di views/engagement per canale, più baseline globale.

    I canali con meno di MIN_BASELINE_VIDEOS video ricadono sulla baseline
    globale del dataset. L'engagement è misurato come (likes + comments)
    ogni 1000 views.
    """
    items = list(contents)
    channels: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = item.get("channel_id") or item.get("channel_title") or "?"
        channels[key].append(item)
    channel_stats = {}
    for key, videos in channels.items():
        stats = _baseline_stats(videos)
        if stats:
            channel_stats[key] = stats
    return {"channels": channel_stats, "global": _baseline_stats(items)}


def classify_growth_shape(snapshots: Iterable[dict[str, Any]]) -> str:
    """Classifica la forma della curva delle views dagli snapshot temporali.

    - ``organico``: la maggior parte della crescita è nel primo intervallo
      osservato (pattern tipico della distribuzione naturale);
    - ``lineare``: crescita distribuita uniformemente (tipico di boost paid
      prolungato);
    - ``spike_tardivo``: salto anomalo in un intervallo successivo al primo
      (tipico di boost paid attivato dopo la pubblicazione);
    - ``piatto``: nessuna crescita osservabile;
    - ``dati_insufficienti``: meno di 3 snapshot disponibili.
    """
    ordered = sorted(snapshots, key=lambda s: _parse_date(s["captured_at"]))
    if len(ordered) < 3:
        return GROWTH_INSUFFICIENT_DATA
    views = [int(s["views"]) for s in ordered]
    deltas = [max(views[index] - views[index - 1], 0) for index in range(1, len(views))]
    total = sum(deltas)
    if total <= 0:
        return GROWTH_FLAT
    if deltas[0] >= total * 0.6:
        return GROWTH_ORGANIC
    later = deltas[1:]
    average = total / len(deltas)
    if later and max(later) >= average * 2:
        return GROWTH_LATE_SPIKE
    return GROWTH_LINEAR


def detect_traffic_anomalies(
    contents: Iterable[dict[str, Any]],
    snapshots: Iterable[dict[str, Any]] = (),
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> list[dict[str, Any]]:
    """Calcola per ogni contenuto z-score, forma di crescita e anomalie.

    Lo score (0-1) pesa: views fuori scala rispetto al canale (+0.4),
    spike tardivo (+0.35), crescita lineare (+0.2), engagement basso con
    views sopra la mediana (+0.2). I risultati sono ordinati per score.
    """
    items = list(contents)
    baselines = compute_channel_baselines(items)
    snapshots_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        snapshots_by_id[snapshot["external_id"]].append(snapshot)

    results: list[dict[str, Any]] = []
    for item in items:
        views = int(item.get("views", 0))
        if views <= 0:
            continue
        channel_key = item.get("channel_id") or item.get("channel_title") or "?"
        baseline = baselines["channels"].get(channel_key)
        baseline_source = "channel"
        if baseline is None:
            baseline = baselines["global"]
            baseline_source = "global"
        if baseline is None:
            continue

        views_z = _robust_zscore(float(views), baseline["views_median"], baseline["views_mad"])
        if views_z is None and baseline["views_median"] > 0:
            # MAD nullo (canale molto uniforme): fallback sul rapporto con la mediana.
            views_z = round((views / baseline["views_median"] - 1) * 2, 2)

        engagement = _engagement_per_1k(views, int(item.get("likes", 0)), int(item.get("comments", 0)))
        engagement_z = None
        if engagement is not None and baseline.get("engagement_median") is not None:
            engagement_z = _robust_zscore(
                engagement, baseline["engagement_median"], baseline["engagement_mad"]
            )

        shape = classify_growth_shape(snapshots_by_id.get(item["external_id"], []))

        anomalies: list[str] = []
        score = 0.0
        if views_z is not None and views_z >= z_threshold:
            anomalies.append("views_fuori_scala")
            score += 0.4
        if shape == GROWTH_LATE_SPIKE:
            anomalies.append("spike_tardivo")
            score += 0.35
        elif shape == GROWTH_LINEAR:
            anomalies.append("crescita_lineare")
            score += 0.2
        if (
            engagement_z is not None
            and engagement_z <= -z_threshold
            and views_z is not None
            and views_z > 0
        ):
            anomalies.append("engagement_basso")
            score += 0.2

        results.append({
            "external_id": item["external_id"],
            "channel": item.get("channel_title") or "Canale sconosciuto",
            "views": views,
            "views_zscore": views_z,
            "channel_median_views": baseline["views_median"],
            "engagement_per_1k": round(engagement, 2) if engagement is not None else None,
            "engagement_zscore": engagement_z,
            "growth_shape": shape,
            "baseline_source": baseline_source,
            "anomalies": anomalies,
            "score": round(min(score, 1.0), 2),
        })
    results.sort(key=lambda entry: (-entry["score"], entry["external_id"]))
    return results
