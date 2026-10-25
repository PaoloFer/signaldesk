"""Indagine premium basata sulle trascrizioni dei video (Tier 2).

Questo modulo implementa l'indagine "extra" a pagamento del funnel sponsor:

1. estrae i sottotitoli pubblici del video (traccia manuale o automatica,
   senza consumare quota API YouTube);
2. rileva i segmenti "ad-read" (lo spot letto dal creator) anche in assenza
   di qualsiasi tag #adv nei metadati;
3. raggruppa ad-read quasi identici su canali diversi: gli script forniti
   dalle agenzie rivelano campagne coordinate.

L'estrazione è on-demand e consuma crediti progetto: il costo per video è la
ragione per cui l'indagine è un servizio premium.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from app.adv_intelligence import extract_gift_sponsor_candidates, extract_sponsor_candidates


WATCH_URL = "https://www.youtube.com/watch"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class TranscriptionError(RuntimeError):
    pass


# Frasi tipiche degli ad-read italiani: segnalano un segmento promozionale
# letto dal creator anche quando il video non dichiara nulla nei metadati.
AD_READ_PHRASES = {
    "questo video è sponsorizzato",
    "questo video è reso possibile",
    "sponsor di questo video",
    "sponsor di oggi",
    "nostro sponsor",
    "prima di iniziare voglio ringraziare",
    "voglio ringraziare lo sponsor",
    "partner di questo video",
    "in collaborazione con",
    "vi lascio il link in descrizione",
    "link in descrizione",
    "trovate il link in descrizione",
    "link qui sotto",
    "usate il codice",
    "usa il codice",
    "con il codice",
    "codice sconto",
    "approfittate dell'offerta",
    "approfittate dello sconto",
    "andate sul sito",
    "visitate il sito",
    "iscrivetevi con il mio link",
    "sostiene questo video",
    "supporta il canale",
}

# Call-to-action in seconda persona: tipiche del registro pubblicitario.
CTA_PATTERN = re.compile(
    r"\b(cliccate|clicca|visitat\w*|scaricat\w*|registrat\w*|provat\w*|"
    r"approfittat\w*|iscrivet\w*|acquistat\w*|ordinat\w*)\b",
    re.IGNORECASE,
)


def _default_fetcher(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "it,en;q=0.8"})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - host YouTube fisso
        return response.read().decode("utf-8", errors="replace")


def _extract_json_array(page: str, marker: str) -> list[dict[str, Any]] | None:
    """Estrae un array JSON annidato nella pagina watch dopo ``marker``.

    Sopporta stringhe con parentesi quadre grazie al tracciamento dello stato
    stringa/escape.
    """
    index = page.find(marker)
    if index == -1:
        return None
    start = page.find("[", index + len(marker))
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(page)):
        char = page[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(page[start:position + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, list) else None
    return None


def _select_track(
    tracks: list[dict[str, Any]], languages: tuple[str, ...]
) -> dict[str, Any]:
    """Sceglie la traccia migliore: lingua preferita, manuale prima di ASR."""

    def score(track: dict[str, Any]) -> tuple[int, int]:
        language = track.get("languageCode", "")
        asr_penalty = 1 if track.get("kind") == "asr" else 0
        for rank, preferred in enumerate(languages):
            if language.startswith(preferred):
                return (rank, asr_penalty)
        return (len(languages), asr_penalty)

    return min(tracks, key=score)


def _parse_timedtext(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    segments = []
    for element in root.iter("text"):
        content = html.unescape(element.text or "").strip()
        content = re.sub(r"\s+", " ", content)
        if not content:
            continue
        segments.append({
            "start": float(element.get("start", 0) or 0),
            "duration": float(element.get("dur", 0) or 0),
            "text": content,
        })
    return segments


def fetch_transcript(
    video_id: str,
    languages: tuple[str, ...] = ("it", "en"),
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Scarica i sottotitoli pubblici di un video YouTube.

    Usa la pagina watch + timedtext, senza consumare quota API. Solleva
    :class:`TranscriptionError` se non ci sono tracce o non sono leggibili.
    """
    fetch = fetcher or _default_fetcher
    try:
        page = fetch(f"{WATCH_URL}?v={video_id}")
    except Exception as exc:
        raise TranscriptionError(f"Pagina watch non raggiungibile: {exc}") from exc
    tracks = _extract_json_array(page, '"captionTracks"')
    if not tracks:
        raise TranscriptionError("Nessuna traccia sottotitoli disponibile")
    track = _select_track(tracks, languages)
    base_url = track.get("baseUrl")
    if not base_url:
        raise TranscriptionError("Traccia sottotitoli senza URL")
    try:
        xml_text = fetch(base_url)
    except Exception as exc:
        raise TranscriptionError(f"Sottotitoli non scaricabili: {exc}") from exc
    try:
        segments = _parse_timedtext(xml_text)
    except ET.ParseError as exc:
        raise TranscriptionError(f"Sottotitoli non leggibili: {exc}") from exc
    if not segments:
        raise TranscriptionError("Traccia sottotitoli vuota")
    return {
        "language": track.get("languageCode", ""),
        "kind": "asr" if track.get("kind") == "asr" else "manual",
        "segments": segments,
        "text": " ".join(segment["text"] for segment in segments),
    }


def _chunk_segments(
    segments: list[dict[str, Any]], chunk_seconds: int
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_start = 0.0
    current_texts: list[str] = []
    for segment in segments:
        if current_texts and segment["start"] >= current_start + chunk_seconds:
            chunks.append({
                "start": current_start,
                "end": segment["start"],
                "text": " ".join(current_texts),
            })
            current_start = segment["start"]
            current_texts = []
        current_texts.append(segment["text"])
    if current_texts:
        last = segments[-1]
        chunks.append({
            "start": current_start,
            "end": last["start"] + last.get("duration", 0),
            "text": " ".join(current_texts),
        })
    return chunks


def analyze_transcript(
    segments: list[dict[str, Any]],
    known_brands: Iterable[str] = (),
    chunk_seconds: int = 45,
    ad_slot_seconds: int = 90,
) -> dict[str, Any]:
    """Punteggia i chunk della trascrizione per probabilità di ad-read.

    Pesi per chunk: frasi da ad-read +0.4, call-to-action +0.2, menzione
    brand +0.3, posizione entro ``ad_slot_seconds`` +0.1 (pre-roll tipico).
    Un chunk è sospetto da 0.4; il video è ``ad_read_detected`` da 0.5.
    """
    if not segments:
        return {
            "sponsor_score": 0.0,
            "ad_read_detected": False,
            "suspicious_segments": [],
            "brands": [],
            "chunks_analyzed": 0,
        }

    brand_patterns = [
        (brand, re.compile(rf"\b{re.escape(brand)}\b", re.IGNORECASE))
        for brand in known_brands
        if brand.strip()
    ]

    suspicious: list[dict[str, Any]] = []
    all_brands: list[str] = []
    best_score = 0.0
    chunks = _chunk_segments(segments, chunk_seconds)

    for chunk in chunks:
        text = chunk["text"]
        lower = text.lower()
        triggers = sorted({phrase for phrase in AD_READ_PHRASES if phrase in lower})
        cta_hits = len(CTA_PATTERN.findall(text))
        brands = [brand for brand, pattern in brand_patterns if pattern.search(text)]
        discovered = extract_sponsor_candidates(text) + extract_gift_sponsor_candidates(text)
        brands = list(dict.fromkeys(brands + discovered))

        score = 0.0
        if triggers:
            score += 0.4
        if cta_hits:
            score += 0.2
        if brands:
            score += 0.3
        if chunk["start"] <= ad_slot_seconds:
            score += 0.1
        score = round(min(score, 1.0), 2)
        best_score = max(best_score, score)
        all_brands.extend(brands)

        if score >= 0.4:
            suspicious.append({
                "start": chunk["start"],
                "end": chunk["end"],
                "score": score,
                "text_preview": text[:160],
                "triggers": triggers[:5],
                "brands": brands,
            })

    return {
        "sponsor_score": best_score,
        "ad_read_detected": best_score >= 0.5,
        "suspicious_segments": suspicious,
        "brands": sorted(set(all_brands)),
        "chunks_analyzed": len(chunks),
    }


def _shingles(text: str, n: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9àèéìòù]+", text.lower())
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[index:index + n]) for index in range(len(words) - n + 1)}


def find_campaign_clusters(
    entries: Iterable[dict[str, Any]],
    min_similarity: float = 0.45,
) -> list[dict[str, Any]]:
    """Raggruppa ad-read quasi identici su video diversi (stesso script).

    Ogni entry deve avere ``external_id``, ``channel`` e ``text`` (il testo
    dei segmenti sospetti). Due ad-read con similarità Jaccard degli shingle
    >= ``min_similarity`` finiscono nello stesso cluster: cluster con più
    canali indicano una campagna coordinata.
    """
    prepared = [
        (entry, _shingles(entry.get("text", "")))
        for entry in entries
        if entry.get("text")
    ]
    parent = list(range(len(prepared)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    pair_similarities: list[tuple[int, int, float]] = []
    for left in range(len(prepared)):
        for right in range(left + 1, len(prepared)):
            shingles_left, shingles_right = prepared[left][1], prepared[right][1]
            if not shingles_left or not shingles_right:
                continue
            intersection = len(shingles_left & shingles_right)
            if not intersection:
                continue
            similarity = intersection / len(shingles_left | shingles_right)
            if similarity >= min_similarity:
                pair_similarities.append((left, right, similarity))
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left

    groups: dict[int, list[int]] = {}
    for index in range(len(prepared)):
        groups.setdefault(find(index), []).append(index)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        member_set = set(members)
        scores = [
            similarity
            for left, right, similarity in pair_similarities
            if left in member_set and right in member_set
        ]
        videos = [prepared[index][0] for index in members]
        clusters.append({
            "videos": sorted(video["external_id"] for video in videos),
            "channels": sorted({video.get("channel") or "?" for video in videos}),
            "size": len(members),
            "avg_similarity": round(sum(scores) / len(scores), 2) if scores else None,
        })
    clusters.sort(key=lambda cluster: (-cluster["size"], cluster["videos"]))
    return clusters
