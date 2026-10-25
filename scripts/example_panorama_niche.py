"""Esempio d'uso del motore semantico delle nicchie (milestone N1–N4).

Mostra come rispondere alla domanda "quali sono gli influencer italiani?"
(o "chi parla di cucina?", "chi fa gaming in italiano?") con la pipeline
panorama: pool di canali candidati (N1), temi estratti TF-IDF (N2),
score composito spiegabile (N3) e cerchi emergenti multi-etichetta (N4).

È lo stesso motore che l'API espone con::

    POST /api/niches/{id}/preview  {"mode": "channels", "filters": {...}}

Lo script è in sola lettura: non scrive sul database e non richiede il
server. Usa la YouTube Data API reale con la chiave in ``.env``.

Costo di quota stimato (esempio "influencer", senza seed):
~1 unità per i popolari regionali + 1 per pagina di ``videos.list``
+ 1 ogni 50 canali arricchiti. La seconda ondata (``--second-wave K``)
costa ~100 unità per canale ed è sempre dichiarata a video.

Uso:
    python scripts/example_panorama_niche.py influencer
    python scripts/example_panorama_niche.py cucina --json
    python scripts/example_panorama_niche.py gaming --max-results 40
    python scripts/example_panorama_niche.py influencer --second-wave 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Permette l'esecuzione sia dalla radice del progetto sia da scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# La console Windows usa cp1252: simboli come ∩ e caratteri accentati
# devono comunque essere stampabili.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

from app import settings  # noqa: F401  (carica le variabili da .env)
from app.channel_profiling import circle_intersection
from app.connectors import YouTubeConnector
from app.panorama import build_panorama


# Definizioni di nicchia pronte all'uso. Ognuna mostra uno strato diverso
# del modello: perimetro geo (L1), keyword/tema (L1–L2), rilevanza
# cross-tema (L3) e descrizione semantica libera.
EXAMPLES: dict[str, dict] = {
    # Il caso guida del piano: "influencer italiani" è trasversale, le
    # keyword non lo delimitano. Si parte dai popolari regionali (quota
    # minima), si filtra per paese/lingua dichiarati e si lascia che temi
    # e cerchi emergano dal pool. Il ranking cross-tema evita che i temi
    # con views strutturalmente più alte (es. gaming) schiaccino gli altri.
    "influencer": {
        "name": "Influencer italiani",
        "description": "creator italiani di intrattenimento generalista",
        "seed_channels": [],
        "seed_videos": [],
        "include_keywords": [],
        "exclude_keywords": [],
        "filters": {
            "date_window_days": 90,
            "max_results": 50,
            "region_code": "IT",
            "relevance_language": "it",
            "channel_country": "IT",
            "channel_language": "it",
            "harvest_popular": True,
            "include_top_channels": True,
            "cross_theme_ranking": True,
        },
    },
    # Nicchia tematica classica: keyword seed + descrizione semantica.
    # La componente "theme" dello score usa la descrizione libera.
    "cucina": {
        "name": "Cucina italiana",
        "description": "ricette di cucina italiana e tradizione gastronomica",
        "seed_channels": [],
        "seed_videos": [],
        "include_keywords": ["ricetta", "cucina italiana"],
        "exclude_keywords": [],
        "filters": {
            "date_window_days": 90,
            "max_results": 40,
            "region_code": "IT",
            "relevance_language": "it",
            "channel_country": "IT",
            "channel_language": "it",
        },
    },
    # Nicchia con pesi personalizzati: qui conta soprattutto l'engagement
    # (community attiva) più che le views assolute.
    "gaming": {
        "name": "Gaming italiano",
        "description": "gameplay e intrattenimento videoludico in italiano",
        "seed_channels": [],
        "seed_videos": [],
        "include_keywords": ["gameplay italiano", "gaming ita"],
        "exclude_keywords": [],
        "filters": {
            "date_window_days": 60,
            "max_results": 40,
            "region_code": "IT",
            "relevance_language": "it",
            "channel_language": "it",
            "w_theme": 1.0,
            "w_engagement": 0.8,
            "w_popularity": 0.2,
        },
    },
}


def _fmt_terms(themes: list[dict], limit: int = 5) -> str:
    return ", ".join(
        f"{t['term']} ({t['weight']:.2f}{t['depth']})" for t in themes[:limit]
    )


def print_report(panorama: dict, stats: dict, elapsed: float, niche: dict) -> None:
    print("=" * 82)
    print(f"PANORAMA NICCHIA: {niche['name']}")
    print("=" * 82)
    print(f"Descrizione semantica : {niche.get('description', '')}")
    print(f"Filtri attivi         : {json.dumps(niche['filters'], ensure_ascii=False)}")
    print(f"Tempo di esecuzione   : {elapsed:.2f}s")

    print("-" * 82)
    print("DIAGNOSTICA DI RACCOLTA E QUOTA")
    print("-" * 82)
    for source in stats.get("sources", []):
        print(f"  fonte {source['type']:<8} {source['value']:<30} -> {source['found']} video")
    print(f"  video candidati: {stats.get('candidates', 0)} | "
          f"canali nel pool: {stats.get('channels', 0)} | "
          f"promossi top: {stats.get('channels_promoted', 0)} | "
          f"esclusi geo: {stats.get('excluded_geo', 0)}")
    second_wave = stats.get("second_wave", {})
    if second_wave.get("channels"):
        print(f"  seconda ondata: {second_wave['channels']} canali, "
              f"~{second_wave['estimated_units']} unità di quota, "
              f"{second_wave['videos_added']} video aggiunti")

    circles = panorama["circles"]
    print("-" * 82)
    print(f"CERCHI EMERGENTI (N4, appartenenza multipla): {len(circles)}")
    print("-" * 82)
    for circle in circles:
        print(f"  {circle['label']}")
    if len(circles) >= 2:
        pair = circle_intersection(circles, circles[0]["id"], circles[1]["id"])
        print(f"  intersezione {circles[0]['term']} ∩ {circles[1]['term']}: "
              f"{pair['count']} canali {pair['channels'][:5]}")

    pool_themes = panorama["pool_themes"]
    print("-" * 82)
    print(f"TEMI DEL POOL (N2, copertura tra canali): {len(pool_themes)}")
    print("-" * 82)
    print("  " + ", ".join(
        f"{t['term']} ({t['channels']}ch)" for t in pool_themes[:12]
    ))

    print("-" * 82)
    print(f"CANALI CLASSIFICATI (N1+N3): {len(panorama['channels'])}")
    print("-" * 82)
    for index, channel in enumerate(panorama["channels"], start=1):
        breakdown = channel["score_breakdown"]
        geo = f"{channel.get('country') or '??'}/{channel.get('language') or '??'}"
        print(f"{index:>2}. [{channel['score']:.3f}] {channel['channel_title']}  "
              f"({geo}, {channel.get('subscribers', 0):,} iscritti, "
              f"{channel['video_count']} video osservati)")
        print(f"     breakdown: theme={breakdown['theme']:.2f} geo={breakdown['geo']:.2f} "
              f"size={breakdown['size']:.2f} pop={breakdown['popularity']:.2f} "
              f"eng={breakdown['engagement']:.2f} vel={breakdown['velocity']:.2f}")
        if channel["shared_terms"]:
            shared = ", ".join(t["term"] for t in channel["shared_terms"][:5])
            print(f"     termini condivisi con la descrizione: {shared}")
        print(f"     temi estratti: {_fmt_terms(channel['themes'])}")
        if channel.get("circles"):
            print(f"     cerchi: {' | '.join(channel['circles'][:3])}")
        anomalies = channel.get("anomalous_videos", 0)
        if anomalies:
            print(f"     video fuori tema (theme_anomaly): {anomalies}")
        top_video = channel["videos"][0] if channel["videos"] else None
        if top_video:
            print(f"     evidenza top: \"{top_video['title'][:65]}\" "
                  f"({top_video['views']:,} views)")
    print("=" * 82)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", choices=sorted(EXAMPLES),
                        help="Esempio di nicchia da esplorare")
    parser.add_argument("--max-results", type=int, default=None,
                        help="Sovrascrive max_results del filtro")
    parser.add_argument("--second-wave", type=int, default=0, metavar="K",
                        help="Seconda ondata su K canali (~100 unità di quota ciascuno)")
    parser.add_argument("--json", action="store_true",
                        help="Stampa il risultato completo in JSON")
    args = parser.parse_args()

    connector = YouTubeConnector()
    if not connector.is_configured():
        print("ERRORE: YOUTUBE_API_KEY non configurata nel file .env", file=sys.stderr)
        return 1

    niche = json.loads(json.dumps(EXAMPLES[args.example]))
    if args.max_results:
        niche["filters"]["max_results"] = args.max_results
    if args.second_wave > 0:
        niche["filters"]["second_wave_top_k"] = args.second_wave

    stats: dict = {}
    started = datetime.now(timezone.utc)
    panorama = build_panorama(niche, connector=connector, stats=stats)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    if args.json:
        print(json.dumps({
            "niche": niche["name"], "stats": stats,
            "elapsed_seconds": round(elapsed, 2), **panorama,
        }, ensure_ascii=False, indent=2))
        return 0

    print_report(panorama, stats, elapsed, niche)
    if not panorama["channels"]:
        print("NESSUN CANALE TROVATO: controlla la diagnostica sopra.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
