from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.traffic_anomaly import detect_traffic_anomalies


# Trigger che indicano presenza di pubblicità diretta o indiretta.
DIRECT_AD_TRIGGERS = {
    "sponsorizzato da",
    "sponsored by",
    "in collaborazione con",
    "partnership con",
    "grazie a",
    "offerto da",
    "promosso da",
    "pubblicità di",
    "spot di",
    "brand partner",
}

INDIRECT_AD_TRIGGERS = {
    "codice sconto",
    "codice promo",
    "coupon",
    "affiliate",
    "affiliazione",
    "link in descrizione",
    "link nella descrizione",
    "amzn.to/",
    "amazon.it/",
    "bit.ly/",
    "#ad",
    "#adv",
    "#sponsored",
    "#partner",
    "#affiliate",
}

ALL_AD_TRIGGERS = DIRECT_AD_TRIGGERS | INDIRECT_AD_TRIGGERS

# Trigger deboli: linguaggio da "prodotto omaggio", indice di possibile
# sponsorizzazione non dichiarata. A differenza dei trigger diretti/indiretti
# non marcano il contenuto come adv dichiarato, ma alimentano il sospetto.
GIFT_LANGUAGE_TRIGGERS = {
    "mi hanno inviato",
    "mi ha inviato",
    "mi è stato inviato",
    "mi e stato inviato",
    "ho ricevuto in regalo",
    "ricevuto in omaggio",
    "in omaggio da",
    "gentilmente offerto",
    "mi è stato regalato",
    "mi e stato regalato",
    "mi hanno regalato",
    "prodotto inviato da",
    "prodotti inviati da",
}

# Domini di affiliazione/tracking non coperti dai trigger indiretti classici
# (bit.ly, amzn.to ecc. sono già in INDIRECT_AD_TRIGGERS).
AFFILIATE_LINK_PATTERN = re.compile(
    r"\b(?:linktr\.ee|awin1\.com|tradedoubler\.com|anrdoezrs\.net|cj\.com|impact\.com|"
    r"shareasale\.com|refersion\.com|go2cloud\.org|partnerize\.com|rakutenadvertising\.com)"
    r"(?:/|\b)",
    re.IGNORECASE,
)
UTM_TRACKING_PATTERN = re.compile(r"[?&]utm_(?:source|medium|campaign)=", re.IGNORECASE)

# Pesi dei segnali deboli nello score di sospetto (0-1).
WEAK_SIGNAL_WEIGHTS = {
    "paid_placement_flag": 1.0,
    "affiliate_link": 0.5,
    "gift_language": 0.35,
    "brand_repetition": 0.3,
    "traffic_anomaly": 0.2,
}

SPONSOR_PATTERNS = [
    re.compile(r"sponsorizzat[oa]\s+da\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|i|gli|grazie|codice|link)\s|$)", re.IGNORECASE),
    re.compile(r"sponsored\s+by\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:for|with|the|on|in|at|and|or|a|an|thanks|code|link)\s|$)", re.IGNORECASE),
    re.compile(r"in\s+collaborazione\s+con\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|grazie|codice|link)\s|$)", re.IGNORECASE),
    re.compile(r"partnership\s+con\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|grazie|codice|link)\s|$)", re.IGNORECASE),
    re.compile(r"grazie\s+a\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|grazie|codice|link)\s|$)", re.IGNORECASE),
]


_STOPWORDS = {
    "questo", "questa", "quello", "quella", "questi", "queste", "canale",
    "video", "canali", "contenuto", "episodio", "puntata", "link", "codice",
    "sconto", "promo", "coupon", "affiliate", "affiliazione", "descrizione",
    "amazon", "youtube", "instagram", "tiktok", "facebook", "twitter",
    "grazie", "running", "corsa", "fitness", "allenamento", "recensione",
}


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tags(item: dict[str, Any]) -> list[str]:
    value = item.get("tags_json", "[]")
    if isinstance(value, list):
        return [str(tag) for tag in value]
    try:
        parsed = json.loads(value or "[]")
        return [str(tag) for tag in parsed] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _content_text(item: dict[str, Any]) -> str:
    parts = [item.get("title", ""), item.get("description", "")]
    parts.extend(_tags(item))
    return " ".join(parts)


def _normalize_sponsor(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\b(srl|s\.r\.l\.|spa|s\.p\.a\.|sas|s\.a\.s\.)$", "", name, flags=re.IGNORECASE).strip()
    if len(name) < 2:
        return ""
    return name


def extract_sponsor_candidates(text: str) -> list[str]:
    """Estrae possibili nomi di sponsor/aziende da un testo.

    L'estrazione è euristica: cerca espressioni commerciali e nomi propri
    adiacenti. I risultati vanno sempre verificati dall'analista.
    """
    candidates: list[str] = []
    lower = text.lower()
    for pattern in SPONSOR_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _normalize_sponsor(match.group(1))
            if candidate and candidate.lower() not in _STOPWORDS:
                candidates.append(candidate)

    # Codice sconto come proxy indiretto: il codice stesso è un identificatore
    # dell'azienda solo se accompagnato da un nome proprio nelle vicinanze.
    for match in re.finditer(r"codice\s+(?:sconto|promo)\s+([A-Z][A-Z0-9]+)", text, re.IGNORECASE):
        code = match.group(1)
        # Cerca un nome proprio subito prima o dopo il codice sconto.
        window = 60
        before = text[max(0, match.start() - window):match.start()]
        after = text[match.end():match.end() + window]
        names_before = re.findall(r"\b([A-Z][a-zA-Z0-9&\.]{2,})\b", before)
        names_after = re.findall(r"\b([A-Z][a-zA-Z0-9&\.]{2,})\b", after)
        # Pattern esplicito "codice sconto X per Azienda" ha priorità.
        explicit = re.search(r"\bper\s+(?:l['a]\s+|l['a]|gli\s+|le\s+|la\s+|lo\s+)?([A-Z][a-zA-Z0-9&\.]{2,})\b", after)
        valid_name = None
        if explicit:
            valid_name = explicit.group(1)
        else:
            for name in reversed(names_after):
                normalized_name = name.lower()
                if normalized_name not in _STOPWORDS and normalized_name not in {"ad", "adv", "sponsored", "partner", "affiliate"}:
                    valid_name = name
                    break
            if not valid_name:
                for name in reversed(names_before):
                    normalized_name = name.lower()
                    if normalized_name not in _STOPWORDS and normalized_name not in {"ad", "adv", "sponsored", "partner", "affiliate"}:
                        valid_name = name
                        break
        if valid_name:
            candidates.append(_normalize_sponsor(valid_name))
        else:
            candidates.append(code)

    # Hashtag adv spesso accompagnati da @brand o #brand.
    if any(trigger in lower for trigger in ("#ad", "#adv", "#sponsored", "#partner")):
        for match in re.finditer(r"[@#]([A-Za-z0-9_\.]{3,})", text):
            tag = match.group(1)
            tag_lower = tag.lower()
            if tag_lower not in _STOPWORDS and tag_lower not in {"ad", "adv", "sponsored", "partner", "affiliate"}:
                candidates.append(_normalize_sponsor(tag))

    # Link affiliati noti come proxy indiretti.
    if "amzn.to/" in lower or "amazon.it/" in lower:
        candidates.append("Amazon")

    return list(dict.fromkeys(c for c in candidates if c))


GIFT_SPONSOR_PATTERNS = [
    # "inviato da Nike", "in omaggio da Nike", "regalato da Nike".
    re.compile(r"(?:inviat[oaie]?|omaggio|regalat[oaie]?|offert[oaie]?)\s+(?:da|di)\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|che|questo|questa|mi)\s|$)", re.IGNORECASE),
    # "Nike mi ha inviato le scarpe".
    re.compile(r"\b([A-Z][A-Za-z0-9&\.]{2,})\s+mi\s+(?:ha|hanno)\s+inviato\b", re.IGNORECASE),
]


def extract_gift_sponsor_candidates(text: str) -> list[str]:
    """Estrae possibili brand dal linguaggio da "prodotto omaggio".

    Complementare a :func:`extract_sponsor_candidates`: cattura sponsor non
    dichiarati con formule come "mi hanno inviato da X" o "X mi ha inviato".
    I risultati vanno sempre verificati dall'analista.
    """
    candidates: list[str] = []
    for pattern in GIFT_SPONSOR_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _normalize_sponsor(match.group(1))
            if candidate and candidate.lower() not in _STOPWORDS:
                candidates.append(candidate)
    return list(dict.fromkeys(candidates))


def detect_weak_signals(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Segnali deboli di sponsorizzazione rilevabili dai soli metadati (Tier 0).

    Ogni segnale ha un peso che contribuisce allo score di sospetto. Non
    richiedono trascrizioni né analisi visive: sono il filtro gratuito del
    funnel di indagine sponsor.
    """
    signals: list[dict[str, Any]] = []
    text = _content_text(item)
    lower = text.lower()

    if item.get("has_paid_product_placement"):
        signals.append({
            "type": "paid_placement_flag",
            "weight": WEAK_SIGNAL_WEIGHTS["paid_placement_flag"],
            "evidence": "Flag ufficiale YouTube 'contenuto promozionale'",
        })

    gift_hits = sorted({trigger for trigger in GIFT_LANGUAGE_TRIGGERS if trigger in lower})
    if gift_hits:
        signals.append({
            "type": "gift_language",
            "weight": WEAK_SIGNAL_WEIGHTS["gift_language"],
            "evidence": ", ".join(gift_hits[:3]),
        })

    affiliate_hits = sorted({
        match.group(0).rstrip("/") for match in AFFILIATE_LINK_PATTERN.finditer(text)
    })
    utm_hits = sorted({
        match.group(0).lstrip("?&").rstrip("=") for match in UTM_TRACKING_PATTERN.finditer(text)
    })
    if affiliate_hits or utm_hits:
        signals.append({
            "type": "affiliate_link",
            "weight": WEAK_SIGNAL_WEIGHTS["affiliate_link"],
            "evidence": ", ".join((affiliate_hits + utm_hits)[:3]),
        })

    return signals


def _has_ad_signal(item: dict[str, Any]) -> bool:
    text = _content_text(item).lower()
    return any(trigger in text for trigger in ALL_AD_TRIGGERS)


def _month_key(value: str) -> str:
    return _parse_date(value).strftime("%Y-%m")


def build_adv_report_from_entities(
    mentions: list[dict[str, Any]],
    raw_snapshots: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Costruisce il report Adv Intelligence usando entità persistenti.

    Ogni mention deve contenere almeno: entity_id, entity_name, entity_type,
    content_id, title, channel_title, published_at, views, likes, comments, niche.
    """
    if not mentions:
        return {
            "metrics": {"contents_with_ads": 0, "sponsors_detected": 0, "channels_with_ads": 0, "niches_with_ads": 0},
            "top_sponsors": [],
            "sponsors_by_niche": [],
            "channels_with_most_sponsors": [],
            "ad_contents": [],
            "indirect_niches": [],
            "cross_niche_bridges": [],
            "trends": [],
        }

    snapshots_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in raw_snapshots:
        snapshots_by_id[snapshot["external_id"]].append(snapshot)

    sponsor_contents: dict[int, list[dict[str, Any]]] = defaultdict(list)
    sponsor_channels: dict[int, set[str]] = defaultdict(set)
    sponsor_niches: dict[int, set[str]] = defaultdict(set)
    channel_sponsors: dict[str, set[int]] = defaultdict(set)
    niche_sponsors: dict[str, set[int]] = defaultdict(set)
    trend_counts: Counter[str] = Counter()
    sponsor_trend_counts: dict[int, Counter[str]] = defaultdict(Counter)
    ad_contents: dict[str, dict[str, Any]] = {}

    for mention in mentions:
        entity_id = mention["entity_id"]
        entity_name = mention["entity_name"]
        channel = mention["channel_title"] or "Canale sconosciuto"
        niche = mention.get("niche") or "Non classificata"
        month = _month_key(mention["published_at"])
        external_id = mention.get("external_id") or str(mention["content_id"])

        sponsor_contents[entity_id].append(mention)
        sponsor_channels[entity_id].add(channel)
        sponsor_niches[entity_id].add(niche)
        channel_sponsors[channel].add(entity_id)
        niche_sponsors[niche].add(entity_id)
        trend_counts[month] += 1
        sponsor_trend_counts[entity_id][month] += 1

        if external_id not in ad_contents:
            snaps = sorted(snapshots_by_id.get(external_id, []), key=lambda s: _parse_date(s["captured_at"]))
            view_change = None
            growth_percent = None
            if len(snaps) >= 2:
                first_views = int(snaps[0]["views"])
                last_views = int(snaps[-1]["views"])
                view_change = last_views - first_views
                growth_percent = round((last_views - first_views) / first_views * 100, 1) if first_views else 0
            ad_contents[external_id] = {
                "external_id": external_id,
                "title": mention["title"],
                "channel": channel,
                "niche": niche,
                "sponsors": [],
                "views": int(mention.get("views", 0)),
                "likes": int(mention.get("likes", 0)),
                "comments": int(mention.get("comments", 0)),
                "published_at": mention["published_at"],
                "ad_type": "diretta" if entity_name != "segnale commerciale" else "indiretta",
                "view_change": view_change,
                "growth_percent": growth_percent,
            }
        if entity_name not in ad_contents[external_id]["sponsors"]:
            ad_contents[external_id]["sponsors"].append(entity_name)

    top_sponsors = []
    for entity_id, items in sorted(sponsor_contents.items(), key=lambda x: (-len(x[1]), x[0])):
        total_views = sum(int(item.get("views", 0)) for item in items)
        top_sponsors.append({
            "name": items[0]["entity_name"],
            "contents": len(items),
            "channels": len(sponsor_channels[entity_id]),
            "niches": sorted(sponsor_niches[entity_id]),
            "total_views": total_views,
            "average_views": round(total_views / len(items)),
            "sample_titles": [item["title"] for item in items[:3]],
        })

    sponsors_by_niche = []
    for niche, entities in sorted(niche_sponsors.items(), key=lambda x: -len(x[1])):
        niche_contents = {item["content_id"] for item in mentions if (item.get("niche") or "Non classificata") == niche}
        sponsor_counts: Counter[str] = Counter()
        for item in mentions:
            if (item.get("niche") or "Non classificata") == niche:
                sponsor_counts[item["entity_name"]] += 1
        sponsors_by_niche.append({
            "niche": niche,
            "total_contents": len(niche_contents),
            "sponsors": [{"name": name, "contents": count} for name, count in sponsor_counts.most_common(8)],
        })

    channels_with_most_sponsors = []
    for channel, entities in sorted(channel_sponsors.items(), key=lambda x: (-len(x[1]), x[0]))[:15]:
        channel_items = [c for c in ad_contents.values() if c["channel"] == channel]
        channels_with_most_sponsors.append({
            "channel": channel,
            "sponsors": len(entities),
            "contents": len(channel_items),
            "niches": sorted({c["niche"] for c in channel_items}),
            "sponsor_names": sorted({mentions[0]["entity_name"] if mentions else str(e) for e in entities})[:8],
        })

    indirect_niches = []
    for entity_id, items in sponsor_contents.items():
        if len(items) < 2:
            continue
        channels = sorted({item["channel_title"] or "Canale sconosciuto" for item in items})
        niches = sorted(sponsor_niches[entity_id])
        total_views = sum(int(item.get("views", 0)) for item in items)
        related_sponsors: Counter[str] = Counter()
        for channel in channels:
            for other_id in channel_sponsors.get(channel, set()):
                if other_id != entity_id:
                    related_sponsors[sponsor_contents[other_id][0]["entity_name"] if other_id in sponsor_contents else str(other_id)] += 1
        indirect_niches.append({
            "name": f"Indiretta: {items[0]['entity_name']}",
            "seed_sponsor": items[0]["entity_name"],
            "contents": len(items),
            "channels": channels[:12],
            "channels_total": len(channels),
            "niches": niches,
            "views": total_views,
            "average_views": round(total_views / len(items)),
            "related_sponsors": [{"name": name, "shared_channels": count} for name, count in related_sponsors.most_common(6)],
        })
    indirect_niches.sort(key=lambda x: -x["contents"])

    cross_bridges = []
    for entity_id, niches in sponsor_niches.items():
        if len(niches) < 2:
            continue
        cross_bridges.append({
            "sponsor": sponsor_contents[entity_id][0]["entity_name"],
            "niches": sorted(niches),
            "channels": sorted(sponsor_channels[entity_id])[:10],
            "channels_total": len(sponsor_channels[entity_id]),
            "contents": len(sponsor_contents[entity_id]),
        })
    cross_bridges.sort(key=lambda x: -x["contents"])

    months = sorted({month for month in trend_counts} | {month for counter in sponsor_trend_counts.values() for month in counter})
    trends = []
    for month in months:
        trends.append({
            "month": month,
            "contents": trend_counts[month],
            "sponsors": sum(1 for counter in sponsor_trend_counts.values() if counter[month] > 0),
            "views": sum(int(c["views"]) for c in ad_contents.values() if _month_key(c["published_at"]) == month),
        })

    return {
        "metrics": {
            "contents_with_ads": len(ad_contents),
            "sponsors_detected": len(sponsor_contents),
            "channels_with_ads": len(channel_sponsors),
            "niches_with_ads": len(niche_sponsors),
        },
        "top_sponsors": top_sponsors[:15],
        "sponsors_by_niche": sponsors_by_niche,
        "channels_with_most_sponsors": channels_with_most_sponsors[:12],
        "ad_contents": list(ad_contents.values())[:50],
        "indirect_niches": indirect_niches[:12],
        "cross_niche_bridges": cross_bridges[:12],
        "trends": trends,
    }


def _canonical_sponsors(sponsors: list[str]) -> dict[str, str]:
    """Restituisce una mappa chiave-lowercase -> nome display più frequente."""
    forms: dict[str, Counter[str]] = defaultdict(Counter)
    for name in sponsors:
        forms[name.lower()][name] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in forms.items()}


def build_adv_report(
    raw_contents: Iterable[dict[str, Any]],
    raw_snapshots: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
    days: int = 90,
    niche: str | None = None,
) -> dict[str, Any]:
    """Costruisce il report Adv Intelligence per il progetto corrente.

    Il report analizza i segnali commerciali diretti e indiretti presenti nei
    contenuti. Permette di incrociare canali e nicchie a partire dagli sponsor
    osservati e di ricostruire nicchie "indirette" definite da pattern di
    pubblicità invece che da keyword tematiche.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    contents = [item for item in raw_contents if _parse_date(item["published_at"]) >= start]
    if niche:
        contents = [item for item in contents if item.get("niche") == niche]

    if not contents:
        return {
            "metrics": {"contents_with_ads": 0, "sponsors_detected": 0, "channels_with_ads": 0, "niches_with_ads": 0},
            "top_sponsors": [],
            "sponsors_by_niche": [],
            "channels_with_most_sponsors": [],
            "ad_contents": [],
            "indirect_niches": [],
            "cross_niche_bridges": [],
            "trends": [],
        }

    sponsor_contents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    channel_sponsors: dict[str, set[str]] = defaultdict(set)
    niche_sponsors: dict[str, set[str]] = defaultdict(set)
    sponsor_channels: dict[str, set[str]] = defaultdict(set)
    sponsor_niches: dict[str, set[str]] = defaultdict(set)
    ad_contents: list[dict[str, Any]] = []
    trend_counts: Counter[str] = Counter()
    sponsor_trend_counts: dict[str, Counter[str]] = defaultdict(Counter)
    display_names: dict[str, str] = {}

    snapshots_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in raw_snapshots:
        snapshots_by_id[snapshot["external_id"]].append(snapshot)

    for item in contents:
        text = _content_text(item)
        raw_sponsors = extract_sponsor_candidates(text)
        has_signal = _has_ad_signal(item)
        if not raw_sponsors and not has_signal:
            continue

        canonical_map = _canonical_sponsors(raw_sponsors)
        display_names.update(canonical_map)
        sponsors = list(canonical_map.keys()) or (["segnale commerciale"] if has_signal else [])

        channel = item.get("channel_title") or "Canale sconosciuto"
        item_niche = item.get("niche") or "Non classificata"
        month = _month_key(item["published_at"])
        trend_counts[month] += 1

        entry = {
            "external_id": item["external_id"],
            "title": item["title"],
            "channel": channel,
            "niche": item_niche,
            "sponsors": [display_names.get(s, s) for s in sponsors],
            "views": int(item.get("views", 0)),
            "likes": int(item.get("likes", 0)),
            "comments": int(item.get("comments", 0)),
            "published_at": item["published_at"],
            "ad_type": "diretta" if any(t in text.lower() for t in DIRECT_AD_TRIGGERS) else "indiretta",
        }

        # Andamento views se ci sono snapshot.
        snaps = sorted(snapshots_by_id.get(item["external_id"], []), key=lambda s: _parse_date(s["captured_at"]))
        if len(snaps) >= 2:
            first_views = int(snaps[0]["views"])
            last_views = int(snaps[-1]["views"])
            entry["view_change"] = last_views - first_views
            entry["growth_percent"] = round((last_views - first_views) / first_views * 100, 1) if first_views else 0
        else:
            entry["view_change"] = None
            entry["growth_percent"] = None

        ad_contents.append(entry)

        for sponsor in sponsors:
            sponsor_contents[sponsor].append(item)
            sponsor_channels[sponsor].add(channel)
            sponsor_niches[sponsor].add(item_niche)
            channel_sponsors[channel].add(sponsor)
            niche_sponsors[item_niche].add(sponsor)
            sponsor_trend_counts[sponsor][month] += 1

    top_sponsors = []
    for sponsor, items in sorted(sponsor_contents.items(), key=lambda x: (-len(x[1]), x[0])):
        total_views = sum(int(item.get("views", 0)) for item in items)
        top_sponsors.append({
            "name": display_names.get(sponsor, sponsor),
            "contents": len(items),
            "channels": len(sponsor_channels[sponsor]),
            "niches": sorted(sponsor_niches[sponsor]),
            "total_views": total_views,
            "average_views": round(total_views / len(items)),
            "sample_titles": [item["title"] for item in items[:3]],
        })

    sponsors_by_niche = []
    for item_niche, sponsors in sorted(niche_sponsors.items(), key=lambda x: -len(x[1])):
        niche_contents = [item for item in contents if (item.get("niche") or "Non classificata") == item_niche and _has_ad_signal(item)]
        sponsor_counts: Counter[str] = Counter()
        for item in niche_contents:
            item_sponsors = extract_sponsor_candidates(_content_text(item)) or (["segnale commerciale"] if _has_ad_signal(item) else [])
            for sponsor in item_sponsors:
                sponsor_counts[sponsor.lower()] += 1
                display_names[sponsor.lower()] = sponsor
        sponsors_by_niche.append({
            "niche": item_niche,
            "total_contents": len(niche_contents),
            "sponsors": [{"name": display_names.get(name, name), "contents": count} for name, count in sponsor_counts.most_common(8)],
        })

    channels_with_most_sponsors = []
    for channel, sponsors in sorted(channel_sponsors.items(), key=lambda x: (-len(x[1]), x[0]))[:15]:
        channel_items = [item for item in ad_contents if item["channel"] == channel]
        channels_with_most_sponsors.append({
            "channel": channel,
            "sponsors": len(sponsors),
            "contents": len(channel_items),
            "niches": sorted({item["niche"] for item in channel_items}),
            "sponsor_names": sorted(display_names.get(s, s) for s in sponsors)[:8],
        })

    # Nicchie indirette: raggruppate per sponsor principale.
    indirect_niches = []
    for sponsor, items in sponsor_contents.items():
        if len(items) < 2:
            continue
        channels = sorted({item.get("channel_title") or "Canale sconosciuto" for item in items})
        niches = sorted(sponsor_niches[sponsor])
        total_views = sum(int(item.get("views", 0)) for item in items)
        related_sponsors: Counter[str] = Counter()
        for channel in channels:
            for other in channel_sponsors.get(channel, set()):
                if other != sponsor:
                    related_sponsors[other] += 1
        indirect_niches.append({
            "name": f"Indiretta: {display_names.get(sponsor, sponsor)}",
            "seed_sponsor": display_names.get(sponsor, sponsor),
            "contents": len(items),
            "channels": channels[:12],
            "channels_total": len(channels),
            "niches": niches,
            "views": total_views,
            "average_views": round(total_views / len(items)),
            "related_sponsors": [{"name": display_names.get(name, name), "shared_channels": count} for name, count in related_sponsors.most_common(6)],
        })
    indirect_niches.sort(key=lambda x: -x["contents"])

    # Ponti tra nicchie tramite sponsor condivisi.
    cross_bridges = []
    for sponsor, niches in sponsor_niches.items():
        if len(niches) < 2:
            continue
        cross_bridges.append({
            "sponsor": display_names.get(sponsor, sponsor),
            "niches": sorted(niches),
            "channels": sorted(sponsor_channels[sponsor])[:10],
            "channels_total": len(sponsor_channels[sponsor]),
            "contents": len(sponsor_contents[sponsor]),
        })
    cross_bridges.sort(key=lambda x: -x["contents"])

    months = sorted({month for month in trend_counts} | {month for counter in sponsor_trend_counts.values() for month in counter})
    trends = []
    for month in months:
        trends.append({
            "month": month,
            "contents": trend_counts[month],
            "sponsors": sum(1 for counter in sponsor_trend_counts.values() if counter[month] > 0),
            "views": sum(int(item.get("views", 0)) for item in ad_contents if _month_key(item["published_at"]) == month),
        })

    return {
        "metrics": {
            "contents_with_ads": len(ad_contents),
            "sponsors_detected": len(sponsor_contents),
            "channels_with_ads": len(channel_sponsors),
            "niches_with_ads": len(niche_sponsors),
        },
        "top_sponsors": top_sponsors[:15],
        "sponsors_by_niche": sponsors_by_niche,
        "channels_with_most_sponsors": channels_with_most_sponsors[:12],
        "ad_contents": ad_contents[:50],
        "indirect_niches": indirect_niches[:12],
        "cross_niche_bridges": cross_bridges[:12],
        "trends": trends,
    }


def search_sponsor(
    raw_contents: Iterable[dict[str, Any]],
    raw_snapshots: Iterable[dict[str, Any]] = (),
    query: str = "",
) -> dict[str, Any]:
    """Cerca tutti i contenuti, canali e nicchie associati a uno sponsor/azienda.

    La ricerca è case-insensitive e cerca la query nel titolo, descrizione e tag
    oppure tra gli sponsor estratti. Restituisce metriche aggregate e andamenti.
    """
    query = query.strip()
    if not query:
        return {"query": "", "matches": [], "channels": [], "niches": [], "trends": [], "metrics": {}}

    query_lower = query.lower()
    matches: list[dict[str, Any]] = []
    channel_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    niche_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trend_counts: Counter[str] = Counter()

    snapshots_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in raw_snapshots:
        snapshots_by_id[snapshot["external_id"]].append(snapshot)

    for item in raw_contents:
        text = _content_text(item)
        sponsors = extract_sponsor_candidates(text)
        title_desc = f"{item.get('title', '')} {item.get('description', '')}".lower()
        is_match = (
            query_lower in title_desc
            or any(query_lower in sponsor.lower() for sponsor in sponsors)
            or query_lower in item.get("channel_title", "").lower()
            or query_lower in item.get("channel_id", "").lower()
        )
        if not is_match:
            continue

        channel = item.get("channel_title") or "Canale sconosciuto"
        item_niche = item.get("niche") or "Non classificata"
        month = _month_key(item["published_at"])
        trend_counts[month] += 1

        snaps = sorted(snapshots_by_id.get(item["external_id"], []), key=lambda s: _parse_date(s["captured_at"]))
        view_change = None
        growth_percent = None
        if len(snaps) >= 2:
            first_views = int(snaps[0]["views"])
            last_views = int(snaps[-1]["views"])
            view_change = last_views - first_views
            growth_percent = round((last_views - first_views) / first_views * 100, 1) if first_views else 0

        entry = {
            "external_id": item["external_id"],
            "title": item["title"],
            "channel": channel,
            "niche": item_niche,
            "sponsors": sponsors or [],
            "views": int(item.get("views", 0)),
            "likes": int(item.get("likes", 0)),
            "comments": int(item.get("comments", 0)),
            "published_at": item["published_at"],
            "view_change": view_change,
            "growth_percent": growth_percent,
        }
        matches.append(entry)
        channel_items[channel].append(entry)
        niche_items[item_niche].append(entry)

    channels = []
    for channel, items in sorted(channel_items.items(), key=lambda x: -len(x[1])):
        channels.append({
            "name": channel,
            "contents": len(items),
            "views": sum(item["views"] for item in items),
            "avg_views": round(sum(item["views"] for item in items) / len(items)),
        })

    niches = []
    for item_niche, items in sorted(niche_items.items(), key=lambda x: -len(x[1])):
        niches.append({
            "name": item_niche,
            "contents": len(items),
            "views": sum(item["views"] for item in items),
            "channels": len({item["channel"] for item in items}),
        })

    months = sorted(trend_counts.keys())
    trends = [{"month": month, "contents": trend_counts[month]} for month in months]

    total_views = sum(item["views"] for item in matches)
    return {
        "query": query,
        "matches": matches[:50],
        "channels": channels[:12],
        "niches": niches[:12],
        "trends": trends,
        "metrics": {
            "matches": len(matches),
            "channels": len(channels),
            "niches": len(niches),
            "total_views": total_views,
            "avg_views": round(total_views / len(matches)) if matches else 0,
        },
    }


def build_suspicion_report(
    raw_contents: Iterable[dict[str, Any]],
    raw_snapshots: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
    days: int = 90,
    niche: str | None = None,
    min_score: float = 0.3,
    include_declared: bool = False,
    min_channel_repetitions: int = 3,
) -> dict[str, Any]:
    """Individua contenuti con sponsorizzazione sospetta anche senza tag #adv.

    Combina i segnali deboli dei metadati (Tier 0, gratuito) con le anomalie
    di traffico calcolate dagli snapshot. È il filtro iniziale del funnel che
    seleziona i video candidati all'indagine premium (trascrizioni, frame).

    Score (0-1): flag ufficiale paid placement +1.0, link affiliato/tracciato
    +0.5, linguaggio da omaggio +0.35, brand ricorrente nel canale +0.3,
    anomalia di traffico +0.1/+0.2. Classificazione: >= 0.7 "probabile",
    >= ``min_score`` "sospetto". I contenuti già dichiarati (#adv, codici
    sconto ecc.) sono esclusi di default.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    contents = [item for item in raw_contents if _parse_date(item["published_at"]) >= start]
    if niche:
        contents = [item for item in contents if item.get("niche") == niche]

    anomalies = {
        entry["external_id"]: entry
        for entry in detect_traffic_anomalies(contents, raw_snapshots)
    }

    # Candidati brand per contenuto (trigger commerciali + linguaggio omaggio)
    # e conteggio per canale: un brand citato in >= min_channel_repetitions
    # video dello stesso canale suggerisce un contratto continuativo.
    brand_display: dict[str, list[str]] = {}
    channel_brand_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in contents:
        text = _content_text(item)
        candidates = extract_sponsor_candidates(text) + extract_gift_sponsor_candidates(text)
        # Dedup case-insensitive preservando la prima forma incontrata.
        unique = list({candidate.lower(): candidate for candidate in reversed(candidates)}.values())
        brand_display[item["external_id"]] = unique
        channel_key = item.get("channel_id") or item.get("channel_title") or ""
        for candidate in {candidate.lower() for candidate in unique}:
            channel_brand_counts[channel_key][candidate] += 1
    repeated_brands = {
        channel: {brand for brand, count in counts.items() if count >= min_channel_repetitions}
        for channel, counts in channel_brand_counts.items()
    }

    items: list[dict[str, Any]] = []
    brand_scores: dict[str, list[float]] = defaultdict(list)
    channel_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"suspects": 0, "scores": []})
    declared_excluded = 0

    for item in contents:
        declared = _has_ad_signal(item)
        if declared and not include_declared:
            declared_excluded += 1
            continue

        signals = detect_weak_signals(item)

        channel_key = item.get("channel_id") or item.get("channel_title") or ""
        item_brands = {candidate.lower() for candidate in brand_display.get(item["external_id"], [])}
        repeated = sorted(repeated_brands.get(channel_key, set()) & item_brands)
        if repeated:
            signals.append({
                "type": "brand_repetition",
                "weight": WEAK_SIGNAL_WEIGHTS["brand_repetition"],
                "evidence": f"Brand ricorrente nel canale: {', '.join(repeated[:3])}",
            })

        anomaly = anomalies.get(item["external_id"])
        if anomaly and anomaly["score"] > 0:
            weight = WEAK_SIGNAL_WEIGHTS["traffic_anomaly"] if anomaly["score"] >= 0.4 else 0.1
            evidence_parts = []
            if anomaly["views_zscore"] is not None:
                evidence_parts.append(f"z-score views {anomaly['views_zscore']}")
            if anomaly["growth_shape"] in {"lineare", "spike_tardivo"}:
                evidence_parts.append(f"crescita {anomaly['growth_shape']}")
            signals.append({
                "type": "traffic_anomaly",
                "weight": weight,
                "evidence": "; ".join(evidence_parts) or "anomalia di traffico",
            })

        score = round(min(sum(signal["weight"] for signal in signals), 1.0), 2)
        if not declared and score < min_score:
            continue
        if declared:
            # La dichiarazione è di per sé l'evidenza: incluso a prescindere
            # dallo score quando include_declared=True.
            classification = "dichiarato"
        else:
            classification = "probabile" if score >= 0.7 else "sospetto"

        suspected_brands = brand_display.get(item["external_id"], [])
        channel = item.get("channel_title") or "Canale sconosciuto"
        items.append({
            "external_id": item["external_id"],
            "title": item["title"],
            "channel": channel,
            "niche": item.get("niche") or "Non classificata",
            "published_at": item["published_at"],
            "views": int(item.get("views", 0)),
            "declared": declared,
            "score": score,
            "classification": classification,
            "signals": signals,
            "suspected_brands": suspected_brands,
        })
        for brand in suspected_brands:
            brand_scores[brand].append(score)
        channel_stats[channel]["suspects"] += 1
        channel_stats[channel]["scores"].append(score)

    items.sort(key=lambda entry: (-entry["score"], -entry["views"]))

    top_brands = [
        {"name": brand, "contents": len(scores), "avg_score": round(sum(scores) / len(scores), 2)}
        for brand, scores in sorted(brand_scores.items(), key=lambda x: (-len(x[1]), x[0]))[:15]
    ]
    channels = [
        {
            "channel": channel,
            "suspects": stats["suspects"],
            "avg_score": round(sum(stats["scores"]) / len(stats["scores"]), 2),
        }
        for channel, stats in sorted(channel_stats.items(), key=lambda x: -x[1]["suspects"])[:12]
    ]

    return {
        "metrics": {
            "analyzed": len(contents),
            "suspects": sum(1 for entry in items if not entry["declared"]),
            "probable": sum(1 for entry in items if entry["classification"] == "probabile"),
            "declared_excluded": declared_excluded,
            "declared_included": sum(1 for entry in items if entry["declared"]),
        },
        "items": items[:50],
        "top_suspected_brands": top_brands,
        "channels": channels,
    }
