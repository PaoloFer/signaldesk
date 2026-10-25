"""Pipeline panorama: dal pool canali ai temi, agli score e ai cerchi.

Orchestra le milestone del motore semantico delle nicchie:

- **N1**: :func:`app.niche_discovery.expand_niche_channels` raccoglie il
  pool di canali candidati con i video come evidenza;
- **N2**: :func:`app.channel_profiling.compute_channel_profiles` estrae i
  temi di ogni canale (TF-IDF dinamico sul pool, spiegabile);
- **N3**: score composito configurabile (theme/geo/size/popularity/
  engagement/velocity) con breakdown e termini condivisi, più la
  modalità di ranking cross-tema;
- **N4**: i top temi del pool diventano "cerchi" ad appartenenza
  multipla con label leggibili e intersezioni esplicite.

Il risultato è un dizionario pronto per l'API: canali ordinati per
score, cerchi emergenti e temi del pool.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.channel_profiling import (
    DEFAULT_SCORE_WEIGHTS,
    emerging_circles,
    pool_themes,
    score_channels,
)
from app.connectors import SocialConnector
from app.niche_discovery import _geo_signals, expand_niche_channels
from app.semantic_engine import (
    OpenAICompatibleCircleLabeler,
    SemanticEngine,
    TfidfEngine,
    make_semantic_engine,
)
from app.settings import settings


def _geo_components(
    channels: list[dict[str, Any]],
    filters: dict[str, Any],
) -> dict[str, float]:
    """Segnali geo esistenti come componente ``w_geo`` (0–1), non boost.

    Riusa :func:`app.niche_discovery._geo_signals`: il boost massimo
    possibile è 0.6 (iscritti in fascia + paese + lingua), quindi la
    componente è ``min(boost / 0.6, 1)``. I canali senza dichiarazioni
    restano a 0 senza essere esclusi (la modalità restrittiva ha già
    agito a livello video in fase di raccolta).
    """
    channel_country = (filters.get("channel_country") or "").strip()
    channel_language = (filters.get("channel_language") or "").strip()
    min_subscribers = int(filters.get("min_subscribers", 0) or 0)
    max_subscribers = int(filters.get("max_subscribers", 0) or 0)
    components: dict[str, float] = {}
    for channel in channels:
        meta = {
            "country": channel.get("country", ""),
            "default_language": channel.get("language", ""),
            "subscribers": channel.get("subscribers", 0),
        }
        boost, _ = _geo_signals(
            meta,
            channel_country=channel_country,
            channel_language=channel_language,
            min_subscribers=min_subscribers,
            max_subscribers=max_subscribers,
            strict_geo=False,
        )
        components[channel["channel_id"]] = min(boost / 0.6, 1.0)
    return components


def _dominant_groups(channels: list[dict[str, Any]]) -> list[str]:
    """Il macro tema dominante di ogni canale (per il ranking cross-tema)."""
    groups: list[str] = []
    for channel in channels:
        themes = channel.get("themes") or []
        groups.append(themes[0]["term"] if themes else "altro")
    return groups


def build_panorama(
    niche: dict[str, Any],
    connector: SocialConnector,
    now: datetime | None = None,
    stats: dict[str, Any] | None = None,
    *,
    semantic_engine: SemanticEngine | None = None,
    circle_labeler: OpenAICompatibleCircleLabeler | None = None,
) -> dict[str, Any]:
    """Costruisce il panorama della nicchia: canali, temi, score, cerchi.

    La descrizione libera della nicchia (``description``, con ``name``
    come riserva) diventa la query semantica della componente ``theme``.
    I filtri riconosciuti sono quelli di :func:`expand_niche_channels`
    più:

    - ``evidence_depth`` (``P1`` | ``P2`` | ``P3``, default ``P2``):
      profondità massima delle evidenze testuali per i temi;
    - ``w_theme``, ``w_geo``, ``w_size``, ``w_popularity``,
      ``w_engagement``, ``w_velocity``: pesi dello score composito;
    - ``cross_theme_ranking`` (bool, default ``False``): normalizza le
      componenti di volume dentro il proprio macro tema prima del
      confronto globale;
    - ``circles_top_n`` (int, default 8): numero massimo di cerchi.
    """
    filters = niche.get("filters", {})
    channels = expand_niche_channels(niche, connector, now=now, stats=stats)
    if not channels:
        return {"channels": [], "circles": [], "pool_themes": []}

    depth = (filters.get("evidence_depth") or "P2").strip().upper()
    engine = semantic_engine or make_semantic_engine(
        settings.semantic_engine, settings.semantic_embedding_model
    )
    try:
        profiles, idf, n_docs = engine.profiles(channels, depth=depth)
    except Exception:
        engine = TfidfEngine()
        profiles, idf, n_docs = engine.profiles(channels, depth=depth)
    by_id = {profile["channel_id"]: profile for profile in profiles}
    for channel in channels:
        profile = by_id.get(channel["channel_id"], {})
        channel["themes"] = profile.get("themes", [])
        channel["vector"] = profile.get("vector", {})
        channel["anomalous_videos"] = profile.get("anomalous_videos", 0)

    query_text = (niche.get("description") or "").strip() or (niche.get("name") or "")
    try:
        theme_matches = engine.theme_matches(
            query_text, channels, depth=depth, idf=idf, n_docs=n_docs
        )
    except Exception:
        theme_matches = TfidfEngine().theme_matches(
            query_text, channels, depth=depth, idf=idf, n_docs=n_docs
        )
    weights = {
        key: float(filters.get(key, default) or 0.0)
        for key, default in DEFAULT_SCORE_WEIGHTS.items()
    }
    cross_theme = bool(filters.get("cross_theme_ranking", False))
    scored = score_channels(
        channels,
        query_text=query_text,
        idf=idf,
        n_docs=n_docs,
        weights=weights,
        geo_components=_geo_components(channels, filters),
        theme_groups=_dominant_groups(channels),
        cross_theme=cross_theme,
        theme_matches=theme_matches,
    )

    vectors = [profile.get("vector") or {} for profile in profiles]
    themes = pool_themes(vectors, min_channels=2, top_n=30)
    circles = emerging_circles(
        profiles, top_n=int(filters.get("circles_top_n", 8) or 8),
    )
    labeler = circle_labeler
    if labeler is None and settings.semantic_label_llm_url:
        labeler = OpenAICompatibleCircleLabeler(
            settings.semantic_label_llm_url,
            settings.semantic_label_llm_api_key,
            settings.semantic_label_llm_model,
            timeout=settings.semantic_label_llm_timeout,
        )
    if labeler is not None:
        try:
            labeler.apply(circles)
        except Exception:
            pass

    # Allega a ogni canale i cerchi di appartenenza (multi-etichetta).
    memberships: dict[str, list[str]] = {}
    for circle in circles:
        for channel_id in circle["channels"]:
            memberships.setdefault(channel_id, []).append(circle["label"])
    for channel in scored:
        channel["circles"] = memberships.get(channel["channel_id"], [])
        channel.pop("vector", None)  # il vettore non esce dall'API

    return {"channels": scored, "circles": circles, "pool_themes": themes}
