"""Profilo semantico dei canali: temi estratti, similarità e cerchi (N2–N4).

Il motore predefinito è TF-IDF calcolato **sul pool osservato**: nessuna
dipendenza esterna, nessuna scatola nera. Gli stessi termini pesano in
modo diverso a seconda della composizione del calderone (IDF dinamico).

Principi del modulo:
- ogni punteggio è spiegabile: i temi sono termini/bigrammi pesati e la
  similarità mostra i termini condivisi con il loro peso;
- il canale è l'unità di analisi, il video è evidenza: un video fuori
  tema rispetto al canale è marcato ``theme_anomaly`` e pesa meno nel
  documento del canale, senza spostarne i temi dominanti;
- le evidenze sono distinte per profondità: P1 titoli+tag (costo zero),
  P2 descrizioni, P3 commenti (se acquisiti).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


# ---------------------------------------------------------------------------
# Tokenizzazione
# ---------------------------------------------------------------------------

STOPWORDS_IT = {
    "il", "lo", "la", "le", "gli", "un", "uno", "una", "dei", "delle", "degli",
    "del", "della", "dello", "dell", "di", "da", "in", "con", "su", "per",
    "tra", "fra", "nel", "nella", "nello", "nei", "nelle", "sul", "sulla",
    "sulle", "al", "alla", "alle", "ai", "dal", "dalla", "dalle", "dai",
    "e", "ed", "o", "ma", "anche", "come", "più", "piu", "molto", "tutto",
    "tutti", "tutta", "tutte", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "che", "chi", "cui", "non",
    "si", "no", "sì", "io", "tu", "lui", "lei", "noi", "voi", "loro",
    "mio", "mia", "miei", "mie", "tuo", "tua", "tuoi", "tue", "suo", "sua",
    "suoi", "sue", "nostro", "nostra", "vostro", "vostra", "loro", "essere",
    "sono", "sei", "siamo", "siete", "era", "erano", "stato", "stata",
    "stati", "state", "avere", "ho", "hai", "ha", "abbiamo", "avete", "hanno",
    "fare", "fa", "fai", "fanno", "fatto", "dire", "dice", "detto", "andare",
    "va", "vado", "vanno", "video", "canale", "iscriviti", "iscrivetevi",
    "oggi", "ieri", "domani", "qui", "qua", "lì", "li", "cosa", "cose",
    "cosi", "così", "dove", "quando", "perché", "perche", "quale", "quali",
    "quanto", "quanta", "quanti", "quante", "dopo", "prima", "ancora",
    "sempre", "mai", "già", "gia", "solo", "proprio", "propria", "grazie",
    "nuovo", "nuova", "nuovi", "nuove", "episodio", "puntata", "vs",
}

STOPWORDS_EN = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "at",
    "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "once",
    "here", "there", "when", "where", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will",
    "just", "should", "now", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "having", "do", "does", "did", "doing",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "this", "that",
    "these", "those", "what", "which", "who", "whom", "as", "am", "get",
    "got", "new", "video", "channel", "subscribe", "episode", "watch",
}

STOPWORDS = STOPWORDS_IT | STOPWORDS_EN

# Rumore tecnico dei metadati: schemi URL, domini e TLD compaiono in quasi
# ogni descrizione canale ("https://www.instagram.com/...") e dominerebbero
# i temi del pool senza portare significato.
STOPWORDS_JUNK = {
    "http", "https", "www", "com", "net", "org", "gg", "link", "bio",
}
STOPWORDS = STOPWORDS | STOPWORDS_JUNK

TOKEN_PATTERN = re.compile(r"[a-zà-ú0-9]+")
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
DOMAIN_PATTERN = re.compile(
    r"\b[a-z0-9-]{2,}\.(?:com|it|net|org|io|me|tv|gg|ly|shop|info|eu)\b",
    re.IGNORECASE,
)

MIN_TOKEN_LENGTH = 3

# Profondità delle evidenze riconosciute (strato L2).
DEPTHS = ("P1", "P2", "P3")

# Peso ridotto dei video anomali nel documento del canale (strato L1).
ANOMALY_WEIGHT = 0.25
# Similarità video↔canale sotto la quale il video è anomalia puntuale.
ANOMALY_THRESHOLD = 0.05

# Troncatura delle descrizioni video nel documento del canale.
DESCRIPTION_CHARS = 500

# Pesi di default dello score composito (strati L1–L3).
DEFAULT_SCORE_WEIGHTS = {
    "w_theme": 1.0,
    "w_geo": 0.5,
    "w_size": 0.3,
    "w_popularity": 0.3,
    "w_engagement": 0.5,
    "w_velocity": 0.4,
}


def tokenize(text: str) -> list[str]:
    """Tokenizza in unigrammi + bigrammi, senza stopwords IT/EN.

    I bigrammi catturano formati e temi composti ("fai da te", "deep
    dive") che gli unigrammi da soli non distinguono. URL e domini nudi
    vengono rimossi prima della tokenizzazione: sono rumore tecnico,
    non temi.
    """
    cleaned = DOMAIN_PATTERN.sub(" ", URL_PATTERN.sub(" ", text or ""))
    words = [
        word
        for word in TOKEN_PATTERN.findall(cleaned.lower())
        if len(word) >= MIN_TOKEN_LENGTH and word not in STOPWORDS and not word.isdigit()
    ]
    bigrams = [f"{first} {second}" for first, second in zip(words, words[1:])]
    return words + bigrams


def channel_depth_documents(channel: dict[str, Any]) -> dict[str, list[str]]:
    """Token del canale distinti per profondità di evidenza.

    - **P1** (titoli + tag, già raccolti a costo zero): include anche la
      descrizione del canale, dichiarata dal creator senza quota extra;
    - **P2** (descrizioni dei video, già raccolte);
    - **P3** (commenti, solo se acquisiti come ``comments_text``).
    """
    p1 = tokenize(channel.get("description", "") or "")
    p2: list[str] = []
    p3: list[str] = []
    for video in channel.get("videos", []):
        p1.extend(tokenize(video.get("title", "") or ""))
        for tag in video.get("tags", []) or []:
            p1.extend(tokenize(str(tag)))
        p2.extend(tokenize((video.get("description", "") or "")[:DESCRIPTION_CHARS]))
        p3.extend(tokenize(video.get("comments_text", "") or ""))
    return {"P1": p1, "P2": p2, "P3": p3}


def _document_at_depth(depth_docs: dict[str, list[str]], depth: str) -> list[str]:
    """Documento cumulativo fino alla profondità richiesta."""
    document: list[str] = []
    for level in DEPTHS:
        if level in depth_docs:
            document.extend(depth_docs[level])
        if level == depth:
            break
    return document


# ---------------------------------------------------------------------------
# TF-IDF sul pool osservato
# ---------------------------------------------------------------------------

def compute_idf(documents: list[list[str]]) -> dict[str, float]:
    """IDF con smoothing, calcolato sul pool osservato.

    La formula ``log((1 + N) / (1 + df)) + 1`` evita pesi nulli per i
    termini ubiqui e divisioni per zero, mantenendo la dinamicità: lo
    stesso termine pesa diversamente al cambiare del calderone.
    """
    n_docs = len(documents)
    doc_freq: Counter[str] = Counter()
    for document in documents:
        for term in set(document):
            doc_freq[term] += 1
    return {
        term: math.log((1 + n_docs) / (1 + freq)) + 1.0
        for term, freq in doc_freq.items()
    }


def _tfidf_vector(
    counts: Counter[str] | dict[str, float],
    idf: dict[str, float],
    max_idf: float,
) -> dict[str, float]:
    return {
        term: (1.0 + math.log(count)) * idf.get(term, max_idf)
        for term, count in counts.items()
        if count > 0
    }


def cosine(first: dict[str, float], second: dict[str, float]) -> float:
    """Coseno di similarità tra due vettori sparsi."""
    if not first or not second:
        return 0.0
    if len(first) > len(second):
        first, second = second, first
    dot = sum(weight * second.get(term, 0.0) for term, weight in first.items())
    if not dot:
        return 0.0
    norm_first = math.sqrt(sum(weight * weight for weight in first.values()))
    norm_second = math.sqrt(sum(weight * weight for weight in second.values()))
    if not norm_first or not norm_second:
        return 0.0
    return dot / (norm_first * norm_second)


def extract_themes(vector: dict[str, float], k: int = 12) -> list[dict[str, Any]]:
    """I temi di un vettore: i top-K termini/bigrammi ordinati per peso."""
    ranked = sorted(vector.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"term": term, "weight": round(weight, 4)}
        for term, weight in ranked[:k]
    ]


def _term_depth(term: str, depth_sets: dict[str, set[str]]) -> str:
    """La profondità minima a cui un termine compare come evidenza."""
    for level in DEPTHS:
        if term in depth_sets.get(level, set()):
            return level
    return "P1"


def compute_channel_profiles(
    channels: list[dict[str, Any]],
    *,
    depth: str = "P2",
    k: int = 12,
    anomaly_threshold: float = ANOMALY_THRESHOLD,
) -> tuple[list[dict[str, Any]], dict[str, float], int]:
    """Calcola i profili semantici dei canali del pool (N2).

    Per ogni canale: vettore TF-IDF, temi estratti con profondità di
    evidenza, e video marcati ``theme_anomaly`` quando divergono dai temi
    dominanti (peso ridotto nel documento del canale).

    Restituisce ``(profili, idf, n_docs)``: l'IDF serve a proiettare le
    query successive (descrizione della nicchia) nello stesso spazio.

    Il filtro anti-rumore scarta i termini con una sola occorrenza in un
    solo canale del pool.
    """
    depth = depth if depth in DEPTHS else "P2"
    n_docs = len(channels)
    if not n_docs:
        return [], {}, 0

    per_channel = []
    for channel in channels:
        depth_docs = channel_depth_documents(channel)
        per_channel.append({
            "channel": channel,
            "depth_docs": depth_docs,
            "document": _document_at_depth(depth_docs, depth),
        })

    # IDF dinamico sul pool + filtro anti-rumore.
    documents = [item["document"] for item in per_channel]
    idf = compute_idf(documents)
    max_idf = math.log(1 + n_docs) + 1.0
    doc_freq: Counter[str] = Counter()
    total_freq: Counter[str] = Counter()
    for document in documents:
        counts = Counter(document)
        for term, count in counts.items():
            doc_freq[term] += 1
            total_freq[term] += count
    vocabulary = {
        term for term in doc_freq
        if not (doc_freq[term] == 1 and total_freq[term] == 1)
    }

    # Primo vettore completo: serve a individuare i video anomali.
    for item in per_channel:
        counts = Counter(t for t in item["document"] if t in vocabulary)
        item["vector"] = _tfidf_vector(counts, idf, max_idf)

    # Anomalia puntuale: il video fuori tema pesa meno nel documento del
    # canale ma resta evidenza a livello video (nicchie topic). Il video
    # è confrontato con il profilo degli **altri** video del canale
    # (leave-one-out): includerlo gonfierebbe la similarità.
    for item in per_channel:
        channel = item["channel"]
        video_tokens: list[tuple[dict[str, Any], list[str]]] = []
        for video in channel.get("videos", []):
            tokens = tokenize(video.get("title", "") or "")
            for tag in video.get("tags", []) or []:
                tokens.extend(tokenize(str(tag)))
            if depth in ("P2", "P3"):
                tokens.extend(tokenize(
                    (video.get("description", "") or "")[:DESCRIPTION_CHARS]
                ))
            if depth == "P3":
                tokens.extend(tokenize(video.get("comments_text", "") or ""))
            video_tokens.append((video, tokens))
        base_counts: Counter[str] = Counter(
            t for t in tokenize(channel.get("description", "") or "") if t in vocabulary
        )
        per_video_counts = [
            Counter(t for t in tokens if t in vocabulary)
            for _, tokens in video_tokens
        ]
        total_counts = base_counts.copy()
        for counts in per_video_counts:
            total_counts.update(counts)
        anomalies = 0
        if len(video_tokens) > 1:
            for (video, tokens), counts in zip(video_tokens, per_video_counts):
                rest = total_counts.copy()
                for term, count in counts.items():
                    rest[term] -= count
                    if rest[term] <= 0:
                        del rest[term]
                similarity = cosine(
                    _tfidf_vector(counts, idf, max_idf),
                    _tfidf_vector(rest, idf, max_idf),
                )
                video["theme_anomaly"] = bool(
                    tokens and similarity < anomaly_threshold
                )
                anomalies += int(video["theme_anomaly"])
        else:
            for video, _ in video_tokens:
                video["theme_anomaly"] = False
        if anomalies:
            # Ricostruisce il documento con i video anomali depotenziati.
            weighted: Counter[str] = Counter()
            weighted.update(t for t in tokenize(channel.get("description", "") or "") if t in vocabulary)
            for video, tokens in video_tokens:
                factor = ANOMALY_WEIGHT if video["theme_anomaly"] else 1.0
                for token in tokens:
                    if token in vocabulary:
                        weighted[token] += factor
            item["vector"] = _tfidf_vector(weighted, idf, max_idf)

    # Temi con profondità di evidenza.
    profiles: list[dict[str, Any]] = []
    for item in per_channel:
        channel = item["channel"]
        depth_sets = {
            level: set(tokens) for level, tokens in item["depth_docs"].items()
        }
        themes = [
            {**theme, "depth": _term_depth(theme["term"], depth_sets)}
            for theme in extract_themes(item["vector"], k=k)
        ]
        profiles.append({
            "channel_id": channel.get("channel_id", ""),
            "channel_title": channel.get("channel_title", ""),
            "themes": themes,
            "vector": item["vector"],
            "anomalous_videos": sum(
                1 for video in channel.get("videos", []) if video.get("theme_anomaly")
            ),
        })
    return profiles, idf, n_docs


def pool_themes(
    vectors: list[dict[str, float]],
    *,
    min_channels: int = 2,
    top_n: int = 30,
) -> list[dict[str, Any]]:
    """Temi del pool: termini con maggior copertura e peso cumulato (N2).

    Sono i candidati per le label dei "cerchi" di N4: un tema conta solo
    se compare in almeno ``min_channels`` canali.
    """
    coverage: Counter[str] = Counter()
    cumulative: Counter[str] = Counter()
    for vector in vectors:
        for term, weight in vector.items():
            coverage[term] += 1
            cumulative[term] += weight
    ranked = sorted(
        (
            {"term": term, "channels": coverage[term],
             "weight": round(cumulative[term], 4)}
            for term in coverage
            if coverage[term] >= min_channels
        ),
        key=lambda item: (-item["channels"], -item["weight"], item["term"]),
    )
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# N3 — Similarità semantica e score composito
# ---------------------------------------------------------------------------

def text_vector(
    text: str,
    idf: dict[str, float],
    n_docs: int,
) -> dict[str, float]:
    """Proietta un testo libero nello spazio TF-IDF del pool.

    I termini assenti dal pool ricevono l'IDF massimo (sono "rari" nel
    calderone), così la descrizione della nicchia non viene svuotata.
    """
    max_idf = math.log(1 + max(n_docs, 1)) + 1.0
    counts = Counter(tokenize(text))
    return _tfidf_vector(counts, idf, max_idf)


def similarity_report(
    niche_text: str,
    channel_vector: dict[str, float],
    idf: dict[str, float],
    n_docs: int,
) -> dict[str, Any]:
    """Similarità nicchia↔canale con i termini condivisi (spiegabilità)."""
    query_vector = text_vector(niche_text, idf, n_docs)
    score = cosine(query_vector, channel_vector)
    shared = [
        {
            "term": term,
            "weight": round(channel_vector[term], 4),
            "query_weight": round(query_vector[term], 4),
        }
        for term in query_vector
        if term in channel_vector
    ]
    shared.sort(key=lambda item: -(item["weight"] * item["query_weight"]))
    return {"score": round(score, 4), "shared_terms": shared[:15]}


def percentile_ranks(values: list[float]) -> list[float]:
    """Posizioni relative 0–1 nel pool (mai valori assoluti).

    I pari merito ricevono il rango medio; se tutti i valori sono zero
    (segnale non disponibile, es. nessuno snapshot) il rango è zero per
    tutti, così il breakdown non mostra differenze fittizie.
    """
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [1.0]
    if all(value == 0 for value in values):
        return [0.0] * count
    order = sorted(range(count), key=lambda index: (values[index], index))
    ranks = [0.0] * count
    start = 0
    while start < count:
        end = start
        while end + 1 < count and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + end) / 2 / (count - 1)
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def _component_percentiles(
    channels: list[dict[str, Any]],
    key: str,
    groups: list[str] | None = None,
) -> list[float]:
    """Percentili di una metrica, globali oppure dentro il proprio gruppo.

    La normalizzazione per gruppo (macro tema) è il cuore del ranking
    cross-tema: un tema con views medie strutturalmente più alte non
    parte avvantaggiato.
    """
    values = [float(channel.get(key, 0.0) or 0.0) for channel in channels]
    if groups is None:
        return percentile_ranks(values)
    if all(value == 0 for value in values):
        return [0.0] * len(channels)
    ranks = [0.0] * len(channels)
    for group in set(groups):
        indices = [i for i, g in enumerate(groups) if g == group]
        if len(indices) == 1:
            # Tema con un solo canale: nessuna competizione interna, il
            # canale prende una posizione neutra invece di un falso primo
            # posto (altrimenti ogni tema solitario varrebbe 1.0 ovunque).
            ranks[indices[0]] = 0.5
            continue
        group_ranks = percentile_ranks([values[i] for i in indices])
        for index, value in zip(indices, group_ranks):
            ranks[index] = value
    return ranks


def score_channels(
    channels: list[dict[str, Any]],
    *,
    query_text: str = "",
    idf: dict[str, float] | None = None,
    n_docs: int | None = None,
    weights: dict[str, float] | None = None,
    geo_components: dict[str, float] | None = None,
    theme_groups: list[str] | None = None,
    cross_theme: bool = False,
    theme_matches: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Score composito per ogni canale, con breakdown spiegabile (N3).

    Componenti (tutte 0–1, normalizzate nel pool):
    - ``theme``: similarità coseno con la descrizione della nicchia;
    - ``geo``: segnali geo-linguistici dichiarati dal canale;
    - ``size``: percentile degli iscritti nel pool;
    - ``popularity``: percentile delle views medie osservate nel pool;
    - ``engagement``: percentile dell'engagement rate nel pool;
    - ``velocity``: percentile della velocità di pickup (0 senza snapshot).

    Con ``cross_theme=True`` le componenti di volume (size, popularity,
    engagement, velocity) sono normalizzate **dentro** il proprio macro
    tema: il confronto globale non premia i temi strutturalmente più
    grandi. Il peso di ogni componente è configurabile (``w_*``).
    """
    if not channels:
        return []
    weights = {**DEFAULT_SCORE_WEIGHTS, **(weights or {})}
    n = n_docs if n_docs is not None else len(channels)
    idf = idf or {}
    geo_components = geo_components or {}

    groups = theme_groups if (cross_theme and theme_groups) else None
    popularity = _component_percentiles(channels, "avg_views", groups)
    size = _component_percentiles(channels, "subscribers", groups)
    engagement = _component_percentiles(channels, "engagement_rate", groups)
    velocity = _component_percentiles(channels, "velocity", groups)

    query_vector = text_vector(query_text, idf, n) if query_text.strip() else {}
    scored: list[dict[str, Any]] = []
    for index, channel in enumerate(channels):
        vector = channel.get("vector") or {}
        channel_match = (theme_matches or {}).get(channel.get("channel_id", ""))
        theme_score = (
            float(channel_match.get("score", 0.0))
            if channel_match is not None
            else cosine(query_vector, vector) if query_vector else 0.0
        )
        components = {
            "theme": round(theme_score, 4),
            "geo": round(float(geo_components.get(channel.get("channel_id", ""), 0.0)), 4),
            "size": round(size[index], 4),
            "popularity": round(popularity[index], 4),
            "engagement": round(engagement[index], 4),
            "velocity": round(velocity[index], 4),
        }
        total_weight = sum(weights.values()) or 1.0
        score = sum(
            weights[f"w_{name}"] * value for name, value in components.items()
        ) / total_weight
        shared_terms: list[dict[str, Any]] = list(
            channel_match.get("shared_terms", []) if channel_match else []
        )
        if channel_match is None and query_vector and vector:
            shared_terms = [
                {"term": term, "weight": round(vector[term], 4),
                 "query_weight": round(query_vector[term], 4)}
                for term in query_vector
                if term in vector
            ]
            shared_terms.sort(key=lambda item: -(item["weight"] * item["query_weight"]))
        scored.append({
            **channel,
            "score": round(score, 4),
            "score_breakdown": components,
            "score_weights": weights,
            "shared_terms": shared_terms[:15],
            "cross_theme": bool(groups),
        })
    scored.sort(key=lambda item: (-item["score"], item.get("channel_title", "")))
    return scored


# ---------------------------------------------------------------------------
# N4 — Cerchi emergenti multi-etichetta
# ---------------------------------------------------------------------------

def emerging_circles(
    profiles: list[dict[str, Any]],
    *,
    top_n: int = 8,
    min_channels: int = 1,
    threshold_ratio: float = 0.3,
) -> list[dict[str, Any]]:
    """Costruisce i "cerchi" emergenti dai top temi del pool (N4).

    Ogni top tema del pool diventa un cerchio; un canale appartiene al
    cerchio se il peso del tema nel suo profilo supera la soglia
    (``threshold_ratio`` del massimo osservato nel pool). L'appartenenza
    è naturalmente multipla: un canale sta in tutti i cerchi per cui
    supera la soglia.
    """
    vectors = [profile.get("vector") or {} for profile in profiles]
    themes = pool_themes(vectors, min_channels=max(min_channels, 1), top_n=top_n)
    circles: list[dict[str, Any]] = []
    for index, theme in enumerate(themes):
        term = theme["term"]
        weights = [
            (profile, (profile.get("vector") or {}).get(term, 0.0))
            for profile in profiles
        ]
        max_weight = max((weight for _, weight in weights), default=0.0)
        if max_weight <= 0:
            continue
        threshold = max_weight * threshold_ratio
        members = [
            profile for profile, weight in weights if weight >= threshold
        ]
        if not members:
            continue
        # Label leggibile: i 2–3 termini principali del cerchio (somma dei
        # vettori dei membri) + conteggio canali.
        centroid: Counter[str] = Counter()
        for member in members:
            for member_term, weight in (member.get("vector") or {}).items():
                centroid[member_term] += weight
        label_terms = [t for t, _ in sorted(
            centroid.items(), key=lambda item: (-item[1], item[0])
        )[:3]]
        circles.append({
            "id": f"circle-{index}",
            "term": term,
            "label": "",
            "label_terms": label_terms,
            "threshold": round(threshold, 4),
            "channels": sorted(member.get("channel_id", "") for member in members),
            "channel_count": len(members),
        })
    for circle in circles:
        terms_label = " · ".join(circle["label_terms"])
        circle["label"] = f"{terms_label} ({circle['channel_count']} canali)"
    return circles


def circle_intersection(
    circles: list[dict[str, Any]],
    first_id: str,
    second_id: str,
) -> dict[str, Any]:
    """I canali nell'intersezione di due cerchi selezionati."""
    by_id = {circle["id"]: circle for circle in circles}
    first = by_id.get(first_id)
    second = by_id.get(second_id)
    if first is None or second is None:
        return {"channels": [], "count": 0}
    common = sorted(set(first["channels"]) & set(second["channels"]))
    return {
        "first": first["label"],
        "second": second["label"],
        "channels": common,
        "count": len(common),
    }
