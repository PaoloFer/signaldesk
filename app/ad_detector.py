"""AD Detector Engine.

Identifica relazioni commerciali (sponsorship, affiliate, product placement)
in contenuti social attraverso un sistema a 6 livelli di evidenza:

L0: segnali piattaforma (has_paid_product_placement, etichette)
L1: disclosure testuale esplicita
L2: link, URL e codici promozionali
L3: entità brand + linguaggio commerciale
L4: pattern comportamentali e campagne
L5: cross-modal (audio/transcript/commenti)

Ogni assessment include ad_type, confidence, disclosure_quality ed evidenze.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Pattern di disclosure (L1)
# ---------------------------------------------------------------------------

DISCLOSURE_PATTERNS = {
    "sponsorship": [
        r"(?:^|\s)#ad\b",
        r"(?:^|\s)#adv\b",
        r"(?:^|\s)#sponsored\b",
        r"(?:^|\s)#sponsor\b",
        r"(?:^|\s)#partner\b",
        r"(?:^|\s)#paidpartnership\b",
        r"\bpaid\s+promotion\b",
        r"\bpaid\s+partnership\b",
        r"sponsorizzat[oa]\s+(da|da\s+parte\s+di)",
        r"in\s+collaborazione\s+con",
        r"partnership\s+con",
        r"grazie\s+a\s+(.+?)\s+(per|che)",
        r"offerto\s+(da|di)",
        r"promosso\s+(da|di)",
        r"\bcontenuto\s+sponsorizzato\b",
        r"pagato\s+(da|di)",
        r"brand\s+partner",
    ],
    "affiliate": [
        r"(?:^|\s)#affiliate\b",
        r"(?:^|\s)#affiliato\b",
        r"\baffiliat[oei]\b",
        r"link\s+affiliat[oei]",
        r"commissioni",
    ],
    "product_placement": [
        r"product\s+placement",
        r"prodotto\s+omaggiato",
        r"ricevuto\s+in\s+omaggio",
        r"in\s+omaggio\s+(da|di)",
        r"mi\s+(?:hanno|ha)\s+inviato",
        r"mi\s+(?:hanno|ha)\s+regalato",
        r"gentilmente\s+(?:offerto|inviato)",
    ],
}

# ---------------------------------------------------------------------------
# Pattern link e codici (L2)
# ---------------------------------------------------------------------------

AFFILIATE_URL_PATTERNS = [
    r"amzn\.to/\w+",
    r"amazon\.[a-z]+/.*?[?&]tag=",
    r"bit\.ly/\w+",
    r"tidd\.ly/\w+",
    r"geni\.us/\w+",
    r"kit\.co/\w+",
    r"stan\.store/\w+",
    r"ltk\.to/\w+",
    r"linktr\.ee/\w+",
    r"awin1\.com",
    r"shareasale\.com",
    r"refersion\.com",
    r"impact\.com",
    r"partnerize\.com",
    r"rakutenadvertising\.com",
    r"[?&]ref=\w+",
    r"[?&]aff=\w+",
    r"[?&]affiliate=\w+",
    r"[?&]utm_source=(?:influencer|youtube|creator)",
    r"[?&]utm_medium=(?:influencer|affiliate|creator)",
]

CODE_PATTERNS = [
    r"\bcodice\s+(?:sconto|promo)\s+([A-Z0-9]{4,})",
    r"\busa\s+(?:il\s+codice\s+)?([A-Z0-9]{4,})\b",
    r"\bpromo\s+code\s+([A-Z0-9]{4,})",
    r"\bcodice\s+([A-Z0-9]{4,})\s+per\s+(?:il|lo|la|gli|le|un|una)?\s*([A-Z][a-zA-Z0-9&\.]{2,})",
]

# ---------------------------------------------------------------------------
# Pattern commercial language (L3)
# ---------------------------------------------------------------------------

COMMERCIAL_VERBS = [
    "scarica", "registrati", "prova", "usa", "ottieni", "risparmia",
    "sconto", "codice", "gratis", "omaggio", "offerta", "promozione",
    "download", "sign up", "try", "get", "save", "discount", "free",
    "deal", "coupon",
]

PROMOTIONAL_CONTEXT = [
    "grazie a", "mi ha permesso", "ho scoperto", "vi consiglio",
    "non potrei più farne a meno", "cambierà", "cambiera",
]

NEGATIVE_SENTIMENT_WORDS = [
    "schifo", "orribile", "pessimo", "deludente", "truffa", "scam",
    "non funziona", "non comprate", "evitate", "terrible", "awful",
    "worst", "hate", "disappointing", "scam",
]

NEWS_CONTEXT_WORDS = [
    "notizia", "news", "annuncia", "licenzia", "acquisisce", "fallimento",
    "indagine", "denuncia", "report", "secondo fonti", "fonti vicine",
]

COMMON_WORDS = {
    "this", "that", "with", "from", "have", "will", "about", "their",
    "questo", "questa", "quello", "quella", "canale", "video", "canali",
    "contenuto", "episodio", "puntata", "link", "codice", "sconto",
    "promo", "coupon", "affiliate", "affiliazione", "descrizione",
}

KNOWN_BRANDS = {
    "revolut", "n26", "wise", "trade republic", "traderepublic", "paypal",
    "stripe", "binance", "coinbase", "nexi", "satispay", "hype",
    "amazon", "nike", "adidas", "apple", "samsung", "sony", "microsoft",
    "google", "meta", "spotify", "netflix", "disney", "airbnb", "uber",
    "booking", "sky", "dazn", "iliad", "vodafone", "tim", "windtre",
    "fastweb", "enel", "eni", "acea", "hellmanns", "barilla", "ferrero",
    "nutella", "lavazza", "nespresso", "mulino bianco", "findus",
    "activia", "danone", "nestlé", "ferrarelle", "san benedetto", "levissima",
}

DOMAIN_BRAND_MAP = {
    "traderepublic": "Trade Republic",
    "revolut": "Revolut",
    "n26": "N26",
    "wise": "Wise",
    "paypal": "PayPal",
    "binance": "Binance",
    "coinbase": "Coinbase",
}

# ---------------------------------------------------------------------------
# Sponsor extraction helpers
# ---------------------------------------------------------------------------

SPONSOR_PATTERNS = [
    re.compile(
        r"sponsorizzat[oa]\s+da\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|i|gli|grazie|codice|link)\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"sponsored\s+by\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:for|with|the|on|in|at|and|or|a|an|thanks|code|link)\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"in\s+collaborazione\s+con\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|grazie|codice|link)\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"partnership\s+con\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|un|una|grazie|codice|link)\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"grazie\s+a\s+([A-Z][A-Za-z0-9&\.\s]+?)(?=\s*[.,;:!?]|\s+(?:per|con|il|la|lo|gli|le|su|in|a|da|o|e|ed|grazie|codice|link)\s|$)",
        re.IGNORECASE,
    ),
]


def _normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\b(srl|s\.r\.l\.|spa|s\.p\.a\.|sas|s\.a\.s\.)$", "", name, flags=re.IGNORECASE).strip()
    return name


def _content_text(content: Mapping[str, Any]) -> str:
    """Testo combinato da titolo, descrizione e tag."""
    parts = [content.get("title", ""), content.get("description", "")]
    tags_value = content.get("tags_json", "[]")
    if isinstance(tags_value, str):
        try:
            tags = json.loads(tags_value or "[]")
            if isinstance(tags, list):
                parts.extend(str(tag) for tag in tags)
        except (TypeError, json.JSONDecodeError):
            pass
    elif isinstance(tags_value, list):
        parts.extend(str(tag) for tag in tags_value)
    return " ".join(parts)


def _transcript_text(content: Mapping[str, Any]) -> str:
    """Restituisce il transcript se disponibile (diretto o da transcripts)."""
    transcript = content.get("transcript", "")
    if transcript:
        return transcript
    analysis = content.get("transcript_analysis_json", "{}")
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis or "{}")
        except (TypeError, json.JSONDecodeError):
            analysis = {}
    return analysis.get("text", "") if isinstance(analysis, dict) else ""


def _comments_text(content: Mapping[str, Any]) -> str:
    comments = content.get("comments_sample", [])
    if isinstance(comments, str):
        try:
            comments = json.loads(comments or "[]")
        except (TypeError, json.JSONDecodeError):
            comments = []
    return " ".join(str(c) for c in comments if c)


# ---------------------------------------------------------------------------
# Estrattori di segnali
# ---------------------------------------------------------------------------

def extract_platform_signals(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    if content.get("has_paid_product_placement") in (1, "1", True, "true"):
        signals.append({
            "level": "L0_platform",
            "signal": "has_paid_product_placement",
            "value": 1,
            "weight": 0.35,
            "ad_type_hint": "sponsorship",
        })

    description = (content.get("description", "") or "").lower()
    if "includes paid promotion" in description:
        signals.append({
            "level": "L0_platform",
            "signal": "youtube_paid_promotion_label",
            "value": "includes paid promotion",
            "weight": 0.30,
            "ad_type_hint": "sponsorship",
        })

    return signals


NEGATION_WORDS = ["non", "nessun", "nessuna", "no", "senza", "not", "no one"]


def _is_negated(text: str, match_start: int, window: int = 15) -> bool:
    """Controlla se il match è preceduto da una negazione entro window caratteri."""
    prefix = text[max(0, match_start - window):match_start]
    return any(re.search(rf"\b{re.escape(word)}\b", prefix, re.IGNORECASE) for word in NEGATION_WORDS)


def extract_disclosure_signals(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    text = _content_text(content).lower()

    for ad_type, patterns in DISCLOSURE_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if _is_negated(text, match.start()):
                    continue
                signals.append({
                    "level": "L1_disclosure",
                    "signal": f"disclosure_{ad_type}",
                    "value": match.group(0),
                    "weight": 0.30 if ad_type == "sponsorship" else 0.25,
                    "ad_type_hint": ad_type,
                })

    return signals


def extract_link_and_code_signals(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    description = (content.get("description", "") or "").lower()
    title = (content.get("title", "") or "").lower()
    combined = f"{title} {description}"

    # Affiliate links
    for pattern in AFFILIATE_URL_PATTERNS:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            signals.append({
                "level": "L2_link_code",
                "signal": "affiliate_link",
                "value": match.group(0),
                "weight": 0.45,
                "ad_type_hint": "affiliate",
            })

    # Promo codes
    for pattern in CODE_PATTERNS:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            code = match.group(1)
            if code and not _is_common_word(code):
                signals.append({
                    "level": "L2_link_code",
                    "signal": "promo_code",
                    "value": code,
                    "weight": 0.16,
                    "ad_type_hint": "sponsorship",
                })

    # Dedicated brand URL patterns (e.g. revolut.com/r/mario)
    for match in re.finditer(r"([a-z0-9\-]+\.com)/[a-z0-9_/\-]*(?:r/|ref/|refer/|invite/)([a-z0-9_\-]+)", combined):
        signals.append({
            "level": "L2_link_code",
            "signal": "dedicated_referral_url",
            "value": match.group(0),
            "weight": 0.45,
            "ad_type_hint": "sponsorship",
        })

    return signals


def _is_common_word(word: str) -> bool:
    return word.lower() in COMMON_WORDS or len(word) < 3


def _score_commercial_language(text: str) -> float:
    """Restituisce un punteggio 0-1 per la presenza di linguaggio commerciale."""
    text_lower = text.lower()
    score = 0.0
    for verb in COMMERCIAL_VERBS:
        if verb in text_lower:
            score += 0.12
    for phrase in PROMOTIONAL_CONTEXT:
        if phrase in text_lower:
            score += 0.15
    return min(1.0, score)


def _is_negative_context(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in NEGATIVE_SENTIMENT_WORDS)


def _is_news_context(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in NEWS_CONTEXT_WORDS)


def extract_brand_candidates(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Estrae candidati brand da pattern di sponsor, menzioni note e hashtag."""
    text = _content_text(content)
    transcript = _transcript_text(content)
    combined = f"{text} {transcript}".strip()
    candidates = []
    seen = set()

    # Pattern espliciti di sponsor
    for pattern in SPONSOR_PATTERNS:
        for match in pattern.finditer(combined):
            name = _normalize_name(match.group(1))
            if name and name.lower() not in seen:
                seen.add(name.lower())
                candidates.append({
                    "name": name,
                    "source": "sponsor_pattern",
                    "position": match.start(),
                })

    # Hashtag brand dopo disclosure
    lower = combined.lower()
    if any(tag in lower for tag in ("#ad", "#adv", "#sponsored", "#partner")):
        for match in re.finditer(r"[@#]([A-Za-z0-9_\.]{3,})", combined):
            tag = match.group(1)
            tag_lower = tag.lower()
            if tag_lower not in {"ad", "adv", "sponsored", "partner", "affiliate"} and tag_lower not in seen:
                seen.add(tag_lower)
                candidates.append({
                    "name": _normalize_name(tag),
                    "source": "disclosure_hashtag",
                    "position": match.start(),
                })

    # Brand noti nel testo combinato
    for brand in KNOWN_BRANDS:
        for match in re.finditer(r"\b" + re.escape(brand) + r"\b", combined, re.IGNORECASE):
            key = brand.lower()
            if key not in seen:
                seen.add(key)
                candidates.append({
                    "name": brand.title(),
                    "source": "known_brand",
                    "position": match.start(),
                })

    # Amazon proxy
    if "amzn.to/" in lower or "amazon.it/" in lower or "amazon.com/" in lower:
        if "amazon" not in seen:
            seen.add("amazon")
            candidates.append({
                "name": "Amazon",
                "source": "affiliate_proxy",
                "position": 0,
            })

    return candidates


def extract_entity_signals(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    text = _content_text(content)
    transcript = _transcript_text(content)
    combined_text = f"{text} {transcript}".strip()

    # Estrazione brand noti dal testo
    candidates = extract_brand_candidates(content)

    # Se ci sono entità pre-estratte, usale
    existing_entities = content.get("entity_mentions", [])
    if existing_entities:
        for entity in existing_entities:
            name = entity.get("name", "")
            if name:
                candidates.append({
                    "name": name,
                    "source": "entity_extraction",
                    "position": combined_text.lower().find(name.lower()),
                })

    seen = set()
    for candidate in candidates:
        name = candidate["name"]
        key = name.lower()
        if key in seen or not name:
            continue
        seen.add(key)

        # Trova il contesto attorno al brand
        pos = candidate.get("position", 0)
        context = combined_text[max(0, pos - 80):min(len(combined_text), pos + len(name) + 80)]
        context_lower = context.lower()

        # Ignora se il contesto è negativo o news
        if _is_negative_context(context):
            signals.append({
                "level": "L3_entity",
                "signal": "negative_brand_mention",
                "value": name,
                "weight": -0.15,
            })
            continue

        if _is_news_context(context):
            signals.append({
                "level": "L3_entity",
                "signal": "news_context_brand",
                "value": name,
                "weight": -0.10,
            })
            continue

        # Conta dove appare il brand
        locations = 0
        if name.lower() in (content.get("title", "") or "").lower():
            locations += 1
        if name.lower() in (content.get("description", "") or "").lower():
            locations += 1
        if name.lower() in transcript.lower():
            locations += 1

        if locations >= 2:
            signals.append({
                "level": "L3_entity",
                "signal": "brand_multi_location",
                "value": name,
                "weight": 0.08,
            })

        # Linguaggio commerciale attorno al brand
        commercial_score = _score_commercial_language(context)
        if commercial_score > 0:
            signals.append({
                "level": "L3_entity",
                "signal": "commercial_language_near_brand",
                "value": name,
                "weight": 0.12 * commercial_score,
                "ad_type_hint": "sponsorship",
            })

    return signals


def detect_main_brand(content: Mapping[str, Any], signals: list[dict[str, Any]]) -> str:
    """Determina il brand principale dai segnali."""
    brand_weights: dict[str, float] = defaultdict(float)

    # Dai pattern di sponsor espliciti
    for candidate in extract_brand_candidates(content):
        brand_weights[candidate["name"]] += 0.5

    # Dai segnali L3
    for signal in signals:
        if signal.get("signal") in ("brand_multi_location", "commercial_language_near_brand"):
            brand_weights[signal["value"]] += signal.get("weight", 0)

    # Da link dedicati
    description = (content.get("description", "") or "").lower()
    for match in re.finditer(r"([a-z0-9\-]+\.com)/[a-z0-9_/\-]*(?:r/|ref/|refer/|invite/)([a-z0-9_\-]+)", description):
        domain = match.group(1).replace(".com", "")
        brand = DOMAIN_BRAND_MAP.get(domain, domain.title())
        brand_weights[brand] += 0.3

    if not brand_weights:
        return ""

    return max(brand_weights, key=brand_weights.get)


def extract_behavioral_signals(
    content: Mapping[str, Any],
    context_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Estrae segnali comportamentali richiedendo dati di contesto opzionali."""
    signals = []
    brand = detect_main_brand(content, [])
    if not brand or not context_data:
        return signals

    channel_id = content.get("channel_id", "")
    previous_mentions = context_data.get("previous_mentions", {}).get(channel_id, {}).get(brand.lower(), 0)
    if previous_mentions == 0:
        signals.append({
            "level": "L4_behavioral",
            "signal": "brand_debut",
            "value": brand,
            "weight": 0.08,
        })

    cluster_size = context_data.get("campaign_cluster", {}).get(brand.lower(), 0)
    if cluster_size >= 3:
        signals.append({
            "level": "L4_behavioral",
            "signal": "campaign_cluster",
            "value": {"brand": brand, "cluster_size": cluster_size},
            "weight": min(0.12, 0.04 * cluster_size),
        })

    return signals


def extract_cross_modal_signals(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals = []
    transcript = _transcript_text(content)

    if transcript:
        transcript_lower = transcript.lower()
        # Disclosure in audio
        for ad_type, patterns in DISCLOSURE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, transcript_lower, re.IGNORECASE):
                    signals.append({
                        "level": "L5_cross_modal",
                        "signal": "audio_disclosure",
                        "value": ad_type,
                        "weight": 0.08,
                        "ad_type_hint": ad_type,
                    })
                    break

        # Brand in audio
        main_brand = detect_main_brand(content, [])
        if main_brand and main_brand.lower() in transcript_lower:
            signals.append({
                "level": "L5_cross_modal",
                "signal": "brand_in_audio",
                "value": main_brand,
                "weight": 0.05,
            })

    # Commenti
    comments_text = _comments_text(content)
    if comments_text:
        ad_related = [c for c in content.get("comments_sample", [])
                      if any(w in str(c).lower() for w in ["pagato", "sponsor", "affiliato", "#ad", "quanto", "soldi"])]
        if len(ad_related) >= 2:
            signals.append({
                "level": "L5_cross_modal",
                "signal": "audience_ad_suspicion",
                "value": len(ad_related),
                "weight": 0.05,
            })

    return signals


# ---------------------------------------------------------------------------
# Classificazione
# ---------------------------------------------------------------------------

def _determine_ad_type(type_weights: dict[str, float], signals: list[dict[str, Any]]) -> str:
    has_platform_flag = any(s.get("signal") == "has_paid_product_placement" for s in signals)
    has_disclosure_sponsorship = any(
        s.get("signal") == "disclosure_sponsorship" for s in signals
    )
    has_disclosure_affiliate = any(
        s.get("signal") == "disclosure_affiliate" for s in signals
    )
    has_disclosure_product_placement = any(
        s.get("signal") == "disclosure_product_placement" for s in signals
    )
    has_affiliate_link = any(s.get("signal") == "affiliate_link" for s in signals)
    has_promo_code = any(s.get("signal") == "promo_code" for s in signals)
    has_dedicated_url = any(s.get("signal") == "dedicated_referral_url" for s in signals)
    has_brand_in_audio = any(s.get("signal") == "brand_in_audio" for s in signals)

    # Mixed
    if (has_disclosure_sponsorship or has_platform_flag) and has_affiliate_link:
        return "mixed"

    # Product placement: piattaforma segnala paid placement e ci sono segnali di omaggio/regalo
    if (has_platform_flag or has_disclosure_product_placement) and not has_disclosure_sponsorship and not has_affiliate_link:
        return "product_placement"

    # Sponsorship
    if has_disclosure_sponsorship or (has_promo_code and has_brand_in_audio) or (has_dedicated_url and has_brand_in_audio):
        return "sponsorship"

    # Affiliate
    if has_affiliate_link or has_disclosure_affiliate:
        return "affiliate"

    if not type_weights:
        return "none"

    return max(type_weights, key=type_weights.get)


def _assess_disclosure_quality(signals: list[dict[str, Any]], ad_type: str) -> str:
    if ad_type in ("none", "organic_uncertain"):
        return "not_applicable"

    disclosure_signals = [s for s in signals if s.get("signal", "").startswith("disclosure_")]
    has_platform_label = any(
        s.get("signal") in ("has_paid_product_placement", "youtube_paid_promotion_label")
        for s in signals
    )
    has_audio_disclosure = any(
        s.get("signal") == "audio_disclosure" for s in signals
    )

    # Disclosure solo tramite hashtag brevi (#ad, #partner, ecc.) -> ambigua
    if disclosure_signals and all(
        re.match(r"^\s*#[a-z]+", str(s.get("value", "")), re.IGNORECASE)
        for s in disclosure_signals
    ):
        return "ambiguous"

    if has_platform_label:
        return "clear"

    if disclosure_signals:
        return "clear"

    if has_audio_disclosure:
        return "clear"

    # Se ci sono segnali commerciali ma nessuna disclosure
    if any(s.get("level") in ("L2_link_code", "L3_entity") and s.get("weight", 0) > 0 for s in signals):
        return "missing"

    return "not_applicable"


def _build_affiliate_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"type": s["signal"], "value": s["value"]}
        for s in signals
        if s.get("level") == "L2_link_code" and s.get("ad_type_hint") == "affiliate"
    ]


def _build_sponsorship_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"type": s["signal"], "value": s["value"]}
        for s in signals
        if s.get("level") == "L2_link_code" and s.get("ad_type_hint") == "sponsorship"
    ]


def _build_risks(ad_type: str, disclosure_quality: str, confidence: float) -> list[dict[str, Any]]:
    risks = []
    if ad_type in ("sponsorship", "product_placement", "mixed") and disclosure_quality == "missing":
        risks.append({
            "type": "missing_disclosure",
            "description": "Relazione commerciale probabile ma disclosure assente o non chiara",
            "severity": "medium",
        })
    if confidence < 0.50 and ad_type != "none":
        risks.append({
            "type": "low_confidence",
            "description": "Classificazione incerta, richiede verifica manuale",
            "severity": "low",
        })
    return risks


def detect_ad(
    content: Mapping[str, Any],
    context_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analizza un contenuto e restituisce la valutazione AD.

    Args:
        content: dizionario con metadati del contenuto.
        context_data: dati opzionali per segnali comportamentali (previous_mentions, campaign_cluster).

    Returns:
        dict con ad_type, confidence, disclosure_quality, evidence, ecc.
    """
    signals = []
    signals.extend(extract_platform_signals(content))
    signals.extend(extract_disclosure_signals(content))
    signals.extend(extract_link_and_code_signals(content))
    signals.extend(extract_entity_signals(content))
    signals.extend(extract_behavioral_signals(content, context_data))
    signals.extend(extract_cross_modal_signals(content))

    positive_signals = [s for s in signals if s.get("weight", 0) > 0]
    negative_signals = [s for s in signals if s.get("weight", 0) < 0]

    # Pesi per tipo
    type_weights: dict[str, float] = defaultdict(float)
    for signal in positive_signals:
        hint = signal.get("ad_type_hint")
        if hint:
            type_weights[hint] += signal["weight"]

    base_score = sum(s["weight"] for s in positive_signals)
    penalty = abs(sum(s["weight"] for s in negative_signals))

    levels_present = set(s.get("level", "") for s in positive_signals)
    corroboration_bonus = 0.10 * max(0, len(levels_present) - 1)

    confidence = min(0.99, base_score + corroboration_bonus - penalty)
    confidence = max(0.0, confidence)

    ad_type = _determine_ad_type(type_weights, signals)

    # Se non ci sono segnali commerciali forti e confidence bassa, forza organic/none
    if ad_type not in ("none", "organic_uncertain") and confidence < 0.25:
        ad_type = "organic_uncertain"

    disclosure_quality = _assess_disclosure_quality(signals, ad_type)
    brand = detect_main_brand(content, signals)

    risks = _build_risks(ad_type, disclosure_quality, confidence)

    return {
        "ad_type": ad_type,
        "confidence": round(confidence, 2),
        "disclosure_quality": disclosure_quality,
        "is_commercial": ad_type in ("sponsorship", "affiliate", "product_placement", "mixed"),
        "is_disclosed": disclosure_quality in ("clear", "ambiguous"),
        "brand_name": brand,
        "evidence": signals,
        "affiliate_signals": _build_affiliate_signals(signals),
        "sponsorship_signals": _build_sponsorship_signals(signals),
        "risks": risks,
    }


def detect_ad_for_content(
    content: Mapping[str, Any],
    project_id: int,
    db_connection: Any | None = None,
) -> dict[str, Any]:
    """Versione con lookup di contesto dal database.

    Se db_connection è fornito, carica dati comportamentali per L4.
    """
    context_data: dict[str, Any] | None = None
    if db_connection is not None:
        context_data = _load_context_data(db_connection, project_id, content)
    return detect_ad(content, context_data)


def _load_context_data(
    db_connection: Any,
    project_id: int,
    content: Mapping[str, Any],
) -> dict[str, Any]:
    """Carica dati di contesto per segnali comportamentali."""
    context: dict[str, Any] = {"previous_mentions": defaultdict(lambda: defaultdict(int)), "campaign_cluster": defaultdict(int)}

    brand = detect_main_brand(content, [])
    if not brand:
        return context

    channel_id = content.get("channel_id", "")
    external_id = content.get("external_id", "")
    published_at = content.get("published_at", "")

    # Conta menzioni precedenti dello stesso brand sullo stesso canale
    try:
        rows = db_connection.execute(
            """SELECT c.external_id, c.published_at
               FROM social_contents c
               JOIN project_contents pc ON pc.content_id = c.id
               JOIN content_entity_mentions m ON m.content_id = c.id
               JOIN entities e ON e.id = m.entity_id
               WHERE pc.project_id = ? AND c.channel_id = ?
                 AND LOWER(e.name) = LOWER(?)
                 AND c.external_id != ?""",
            (project_id, channel_id, brand, external_id),
        ).fetchall()
        context["previous_mentions"][channel_id][brand.lower()] = len(rows)
    except Exception:
        pass

    # Cluster temporale: stesso brand su più canali nelle ultime 2 settimane
    try:
        if published_at:
            since = (datetime.fromisoformat(published_at.replace("Z", "+00:00")) - timedelta(days=14)).isoformat()
            rows = db_connection.execute(
                """SELECT COUNT(DISTINCT c.channel_id) as cluster_size
                   FROM social_contents c
                   JOIN project_contents pc ON pc.content_id = c.id
                   JOIN content_entity_mentions m ON m.content_id = c.id
                   JOIN entities e ON e.id = m.entity_id
                   WHERE pc.project_id = ? AND c.published_at >= ?
                     AND LOWER(e.name) = LOWER(?)
                     AND c.external_id != ?""",
                (project_id, since, brand, external_id),
            ).fetchone()
            if rows:
                context["campaign_cluster"][brand.lower()] = rows["cluster_size"]
    except Exception:
        pass

    return context
