"""Analisi della rete di canali e sovrapposizione del pubblico osservato."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_channel_overlap(comments: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcola la sovrapposizione di commentatori (Jaccard) tra coppie di canali.

    Restituisce una matrice e le coppie con sovrapposizione maggiore di zero.
    """
    by_channel: dict[str, set[str]] = defaultdict(set)
    for comment in comments:
        channel = comment.get("channel_title", "").strip()
        author = comment.get("author_hash", "").strip()
        if channel and author:
            by_channel[channel].add(author)

    channels = sorted(by_channel.keys())
    matrix: list[dict[str, Any]] = []
    top_pairs: list[dict[str, Any]] = []

    for index_i, channel_i in enumerate(channels):
        row: list[float] = []
        for index_j, channel_j in enumerate(channels):
            if index_i == index_j:
                row.append(1.0)
                continue
            authors_i = by_channel[channel_i]
            authors_j = by_channel[channel_j]
            intersection = len(authors_i & authors_j)
            union = len(authors_i | authors_j)
            jaccard = round(intersection / union, 3) if union else 0.0
            row.append(jaccard)
            if index_i < index_j and jaccard > 0:
                top_pairs.append({
                    "left": channel_i,
                    "right": channel_j,
                    "overlap": jaccard,
                    "shared_authors": intersection,
                })
        matrix.append({"channel": channel_i, "values": row})

    top_pairs.sort(key=lambda item: item["overlap"], reverse=True)
    return {
        "channels": channels,
        "matrix": matrix,
        "top_pairs": top_pairs[:10],
    }
