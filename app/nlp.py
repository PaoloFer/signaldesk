"""Analisi NLP rule-based dei commenti.

Questa implementazione evita dipendenze pesanti (transformers/torch) e usa
lessemi e pattern per italiano e inglese. È pensata come baseline spiegabile:
i risultati vanno interpretati come indicatori, non come verdetti.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


POSITIVE_IT = {
    "bello", "belli", "bella", "belle", "bravo", "bravi", "ottimo", "ottimi",
    "ottima", "ottime", "buono", "buoni", "buona", "buone", "grande", "grandi",
    "utile", "utili", "interessante", "interessanti", "valido", "validi", "valida",
    "valide", "perfetto", "perfetti", "perfetta", "perfette", "consiglio",
    "consigliato", "consigliata", "consigliati", "consigliate", "geniale",
    "geniali", "top", "grazie", "apprezzo", "apprezzato", "apprezzata",
    "adoro", "adorare", "piace", "piaciuto", "piaciuta", "felice", "contento",
    "contenta", "entusiasta", "entusiasti", "entusiaste", "approvo", "approvato",
}

NEGATIVE_IT = {
    "brutto", "brutti", "brutta", "brutte", "schifo", "schifoso", "schifosa",
    "schifosi", "schifose", "pessimo", "pessimi", "pessima", "pessime", "cattivo",
    "cattivi", "cattiva", "cattive", "orribile", "orribili", "terribile",
    "terribili", "inutile", "inutili", "noioso", "noiosa", "noiosi", "noiose",
    "deludente", "deludenti", "deluso", "delusa", "delusi", "deluse", "odio",
    "odiato", "odiata", "bugiardo", "bugiarda", "bugiardi", "bugiarde", "falso",
    "falsi", "falsa", "false", "truffa", "truffatore", "truffatori", "peggio",
    "peggiore", "pessimo", "pessima", "non funziona", "non capisce", "non serve",
    "schifezza", "schifezze",
}

POSITIVE_EN = {
    "good", "great", "nice", "awesome", "amazing", "excellent", "perfect",
    "love", "loved", "like", "liked", "helpful", "useful", "interesting",
    "valid", "best", "fantastic", "wonderful", "brilliant", "thanks", "thank",
    "appreciate", "appreciated", "happy", "glad", "enthusiastic", "approve",
    "approved", "recommended", "recommend",
}

NEGATIVE_EN = {
    "bad", "ugly", "terrible", "horrible", "awful", "worst", "worse", "hate",
    "hated", "useless", "boring", "disappointing", "disappointed", "fake",
    "liar", "liars", "scam", "scammer", "fraud", "trash", "garbage", "doesnt",
    "doesn't", "dont", "don't", "not work", "not working", "waste",
}

TOXIC_IT = {
    "idiota", "idioti", "stupido", "stupida", "stupidi", "stupide", "cretino",
    "cretina", "cretini", "cretine", "deficiente", "deficienti", "ritardato",
    "ritardata", "ritardati", "ritardate", "scemo", "scema", "scemi", "sceme",
    "coglione", "coglioni", "stronzo", "stronza", "stronzi", "stronze",
    "bastardo", "bastarda", "bastardi", "bastarde", "merda", "merde",
    "vaffanculo", "cazzo", "cazzi", "minchia", "figlio di puttana",
    "puttana", "puttane", "troia", "trote", "zoccola", "zoccole", "mignotta",
    "mignotte", "succhiami", "rompiballe", "rompipalle", "testa di cazzo",
    "pezzo di merda", "schifoso", "schifosa", "schifosi", "schifose",
}

TOXIC_EN = {
    "idiot", "idiots", "stupid", "stupidest", "moron", "morons", "retard",
    "retarded", "dumb", "asshole", "assholes", "bastard", "bastards",
    "bitch", "bitches", "whore", "whores", "slut", "sluts", "fuck", "fucking",
    "fucker", "fuckers", "shit", "shitty", "crap", "damn", "damned", "hell",
    "suck", "sucks", "sucker", "suckers", "loser", "losers", "kill yourself",
    "kys", "stfu", "gtfo",
}

INTENT_PATTERNS = [
    ("question", [r"\?", r"^(come|dove|quando|quanto|quale|quali|perché|perche|chi|cosa|che)"]),
    ("complaint", [r"non (funziona|va|serve|capisco|piace)", r"problema", r"bug"]),
    ("appreciation", [r"grazie", r"bravo", r"ottimo", r"top", r"bel lavoro", r"thank", r"thanks", r"great job"]),
    ("criticism", [r"non (mi|ti) piace", r"pessimo", r"orribile", r"terribile", r"brutto"]),
]


def _normalize(text: str) -> set[str]:
    lowered = text.lower()
    lowered = re.sub(r"['’]", " ", lowered)
    return set(re.findall(r"[a-zà-ú0-9]+", lowered))


def _detect_language(text: str) -> str:
    words = _normalize(text)
    it_score = len(words & (POSITIVE_IT | NEGATIVE_IT | TOXIC_IT))
    en_score = len(words & (POSITIVE_EN | NEGATIVE_EN | TOXIC_EN))
    if it_score > en_score:
        return "it"
    if en_score > it_score:
        return "en"
    return "unknown"


def _sentiment(text: str) -> tuple[str, float]:
    words = _normalize(text)
    pos = len(words & POSITIVE_IT) + len(words & POSITIVE_EN)
    neg = len(words & NEGATIVE_IT) + len(words & NEGATIVE_EN)
    # Pesi per espressioni forti
    neg += len([w for w in words if w in TOXIC_IT or w in TOXIC_EN]) * 2
    if pos > neg:
        return "positive", min((pos - neg) * 0.25, 1.0)
    if neg > pos:
        return "negative", max(min((neg - pos) * -0.25, -0.1), -1.0)
    return "neutral", 0.0


def _intent(text: str) -> str:
    lowered = text.lower()
    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return intent
    return "other"


def _toxicity(text: str) -> tuple[float, list[str]]:
    lowered = text.lower()
    flags: list[str] = []
    score = 0.0
    for word in TOXIC_IT | TOXIC_EN:
        if word in lowered:
            flags.append(word)
            score += 0.35
    if re.search(r"\b(morte|morto|ammazz|uccid|suicid|kill|die)\b", lowered):
        flags.append("violence")
        score += 0.4
    return min(score, 1.0), flags


def analyze_text(text: str) -> dict[str, Any]:
    language = _detect_language(text)
    sentiment, sentiment_score = _sentiment(text)
    intent = _intent(text)
    toxicity_score, flags = _toxicity(text)
    return {
        "language": language,
        "sentiment": sentiment,
        "sentiment_score": round(sentiment_score, 3),
        "intent": intent,
        "toxicity_score": round(toxicity_score, 3),
        "flags": flags,
    }


def analyze_comment(comment_id: int, text: str) -> dict[str, Any]:
    result = analyze_text(text)
    result["comment_id"] = comment_id
    result["processed_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return result
