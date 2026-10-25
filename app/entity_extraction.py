from __future__ import annotations

from typing import Any

from app.adv_intelligence import ALL_AD_TRIGGERS, DIRECT_AD_TRIGGERS, extract_sponsor_candidates


ENTITY_TYPES = {
    "brand": "brand/azienda",
    "product": "prodotto/servizio",
    "person": "persona/creator",
    "organization": "organizzazione",
    "platform": "piattaforma",
}


def _content_text(item: dict[str, Any]) -> str:
    parts = [item.get("title", ""), item.get("description", "")]
    tags_value = item.get("tags_json", "[]")
    if isinstance(tags_value, list):
        parts.extend(str(tag) for tag in tags_value)
    else:
        try:
            import json
            parsed = json.loads(tags_value or "[]")
            if isinstance(parsed, list):
                parts.extend(str(tag) for tag in parsed)
        except (TypeError, json.JSONDecodeError):
            pass
    return " ".join(parts)


def _confidence_for_sponsor(text: str, sponsor: str) -> float:
    """Assegna un punteggio di confidenza in base alla qualità del segnale."""
    lower = text.lower()
    if any(trigger in lower for trigger in DIRECT_AD_TRIGGERS):
        return 0.9
    if any(trigger in lower for trigger in ALL_AD_TRIGGERS):
        return 0.7
    return 0.5


def _context_window(text: str, start: int, end: int, window: int = 80) -> str:
    return text[max(0, start - window):min(len(text), end + window)].strip()


def extract_entity_mentions(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Estrae menzioni di entità da un singolo contenuto.

    Al momento si basa sulle regole commerciali già presenti in
    app.adv_intelligence. In futuro questo è il punto dove inserire NER/LLM.
    """
    text = _content_text(item)
    lower = text.lower()
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for sponsor in extract_sponsor_candidates(text):
        key = sponsor.lower()
        if key in seen:
            continue
        seen.add(key)
        # Trova la posizione della menzione nel testo per estrarre il contesto.
        pos = lower.find(key)
        context = _context_window(text, pos, pos + len(key)) if pos >= 0 else ""
        mentions.append({
            "name": sponsor,
            "type": "brand",
            "mention_text": sponsor,
            "context": context,
            "confidence": _confidence_for_sponsor(text, sponsor),
            "source": "rule",
        })

    return mentions


def extract_entities_from_contents(
    contents: list[dict[str, Any]],
    project_id: int,
) -> list[dict[str, Any]]:
    """Estrae tutte le menzioni da una lista di contenuti, pronte per essere salvate."""
    mentions: list[dict[str, Any]] = []
    for item in contents:
        for mention in extract_entity_mentions(item):
            mentions.append({
                "project_id": project_id,
                "content_id": item["id"],
                **mention,
            })
    return mentions
