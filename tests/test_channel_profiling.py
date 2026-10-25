"""Test del motore semantico delle nicchie (milestone N2–N4).

Pool finto di riferimento: canali di musica, cucina e tech, più un
canale ibrido food-music per i cerchi multi-etichetta.
"""

import unittest

from app.channel_profiling import (
    channel_depth_documents,
    circle_intersection,
    compute_channel_profiles,
    compute_idf,
    cosine,
    emerging_circles,
    extract_themes,
    percentile_ranks,
    pool_themes,
    score_channels,
    similarity_report,
    tokenize,
)


def _video(title, description="", tags=None, comments_text=""):
    return {
        "title": title,
        "description": description,
        "tags": tags or [],
        "comments_text": comments_text,
        "views": 1000,
        "likes": 50,
        "comments": 10,
    }


def _channel(cid, title, description, videos, **metrics):
    channel = {
        "channel_id": cid,
        "channel_title": title,
        "description": description,
        "videos": videos,
        "avg_views": 1000,
        "subscribers": 10000,
        "engagement_rate": 0.05,
    }
    channel.update(metrics)
    return channel


def _music_pool():
    return [
        _channel(
            "UCmus1", "Palco Live", "Canale di musica dal vivo",
            [
                _video("Maneskin live a Sanremo", "Il concerto completo", ["musica", "live"]),
                _video("Concerto rock dal vivo", "Serata di musica rock", ["musica", "concerto"]),
            ],
        ),
        _channel(
            "UCmus2", "Rock Italiano", "Musica rock italiana",
            [
                _video("Live concerto musica rock", "Musica dal vivo", ["musica", "live"]),
                _video("Intervista alla band rock", "Parla la band", ["rock", "intervista"]),
            ],
        ),
        _channel(
            "UCcuc1", "Fornello Facile", "Ricette di cucina italiana",
            [
                _video("Pasta carbonara ricetta", "Ricetta tradizionale romana", ["cucina", "pasta"]),
                _video("Torta al cioccolato ricetta", "Dolce facile di cucina", ["cucina", "dolci"]),
            ],
        ),
        _channel(
            "UCtech1", "Tutto Tech", "Recensioni di tecnologia",
            [
                _video("Recensione smartphone tech", "Prova sul campo", ["tech", "smartphone"]),
                _video("Migliori auricolari tech", "Confronto recensione", ["tech", "auricolari"]),
            ],
        ),
    ]


class TokenizeTest(unittest.TestCase):
    def test_unigrams_and_bigrams_without_stopwords(self):
        tokens = tokenize("Il concerto di musica dal vivo")
        self.assertIn("concerto", tokens)
        self.assertIn("musica", tokens)
        self.assertIn("vivo", tokens)
        # Stopwords italiane rimosse.
        self.assertNotIn("il", tokens)
        self.assertNotIn("di", tokens)
        self.assertNotIn("dal", tokens)
        # Bigrammi generati dai termini filtrati.
        self.assertIn("concerto musica", tokens)

    def test_short_tokens_and_digits_are_dropped(self):
        tokens = tokenize("Top 10 gol del 2024 in tv")
        self.assertNotIn("10", tokens)
        self.assertNotIn("2024", tokens)
        self.assertNotIn("tv", tokens)  # sotto la lunghezza minima
        self.assertIn("gol", tokens)

    def test_english_stopwords(self):
        tokens = tokenize("The best video about the channel")
        self.assertNotIn("the", tokens)
        self.assertNotIn("about", tokens)
        self.assertIn("best", tokens)

    def test_urls_and_domains_are_not_themes(self):
        """URL e domini nudi nelle descrizioni non diventano temi del pool."""
        tokens = tokenize(
            "Seguimi su https://www.instagram.com/mario oppure mario.gg "
            "per ricette di cucina"
        )
        for junk in ("https", "www", "instagram", "com", "gg", "mario gg"):
            self.assertNotIn(junk, tokens)
        self.assertIn("ricette", tokens)
        self.assertIn("cucina", tokens)


class ChannelProfilingTest(unittest.TestCase):
    def test_themes_contain_expected_terms_per_channel(self):
        """Pool musica/cucina/tech: i temi riflettono il tema del canale."""
        profiles, _, _ = compute_channel_profiles(_music_pool())
        by_id = {profile["channel_id"]: profile for profile in profiles}
        music_terms = {t["term"] for t in by_id["UCmus1"]["themes"]}
        kitchen_terms = {t["term"] for t in by_id["UCcuc1"]["themes"]}
        tech_terms = {t["term"] for t in by_id["UCtech1"]["themes"]}
        self.assertTrue(music_terms & {"musica", "live", "concerto", "rock"})
        self.assertTrue(kitchen_terms & {"cucina", "pasta", "ricetta"})
        self.assertTrue(tech_terms & {"tech", "recensione", "smartphone"})

    def test_idf_is_dynamic_with_pool_composition(self):
        """Lo stesso termine pesa di meno se il calderone lo condivide."""
        target = _channel(
            "UCtarget", "Target", "",
            [_video("Maneskin live maneskin", "", ["musica"])],
        )
        other_a = _channel("UCa", "A", "", [_video("Cucina pasta ricetta", "", ["cucina"])])
        other_b = _channel("UCb", "B", "", [_video("Tech smartphone futuro", "", ["tech"])])
        profiles_solo, _, _ = compute_channel_profiles([target, other_a, other_b])
        vector_solo = profiles_solo[0]["vector"]

        shared_a = _channel("UCa", "A", "", [_video("Maneskin concerto", "", ["musica"])])
        shared_b = _channel("UCb", "B", "", [_video("Maneskin intervista", "", ["musica"])])
        profiles_shared, _, _ = compute_channel_profiles([target, shared_a, shared_b])
        vector_shared = profiles_shared[0]["vector"]

        self.assertGreater(vector_solo["maneskin"], vector_shared["maneskin"])

    def test_noise_filter_drops_single_occurrence_terms(self):
        """Termini con una sola occorrenza in un solo canale: scartati."""
        channel = _channel(
            "UCx", "X", "",
            [_video("Cucina pasta ricetta zibaldone", "", ["cucina"])],
        )
        other = _channel("UCy", "Y", "", [_video("Tech futuro smartphone", "", ["tech"])])
        profiles, _, _ = compute_channel_profiles([channel, other])
        vector = profiles[0]["vector"]
        # "zibaldone" compare una sola volta in un solo canale: rumore.
        self.assertNotIn("zibaldone", vector)
        # "cucina" compare più volte nello stesso canale: resta.
        self.assertIn("cucina", vector)

    def test_theme_anomaly_flag_and_dominant_themes_stable(self):
        """Un video fuori tema è anomalia, non sposta i temi dominanti."""
        channel = _channel(
            "UCcuc2", "Chef di Casa", "Cucina casalinga",
            [
                _video("Ricetta pasta al pomodoro", "Piatto di cucina", ["cucina", "pasta"]),
                _video("Ricetta risotto ai funghi", "Ricetta di cucina", ["cucina", "risotto"]),
                _video("Ricetta dolce tiramisù", "Dolce di cucina", ["cucina", "dolci"]),
                _video("Viaggio nello spazio tra galassie", "Astronomia per tutti", ["spazio"]),
            ],
        )
        others = [
            _channel("UCm", "M", "", [_video("Musica live concerto", "", ["musica"])]),
            _channel("UCt", "T", "", [_video("Tech smartphone recensione", "", ["tech"])]),
        ]
        profiles, _, _ = compute_channel_profiles([channel, *others])
        profile = profiles[0]
        videos = channel["videos"]
        self.assertTrue(videos[3]["theme_anomaly"])      # il video spaziale
        self.assertFalse(videos[0]["theme_anomaly"])     # i video di cucina no
        self.assertEqual(profile["anomalous_videos"], 1)
        # I temi dominanti restano di cucina.
        top_terms = [t["term"] for t in profile["themes"][:3]]
        self.assertTrue(set(top_terms) & {"cucina", "ricetta"})
        self.assertNotIn("spazio", top_terms[:1])

    def test_evidence_depth_levels(self):
        """I temi dichiarano la profondità minima della loro evidenza."""
        channel = _channel(
            "UCd", "Depth", "",
            [
                _video(
                    "Titolo con marchioveloce",
                    "La descrizione parla di sottotitolo",
                    ["tagvisibile"],
                    comments_text="Nei commenti si parla di retroscena",
                ),
                _video("Altro marchioveloce video", "Ancora sottotitolo qui", ["tagvisibile"],
                       comments_text="Anche qui retroscena"),
            ],
        )
        other = _channel("UCo", "O", "", [_video("Cucina pasta ricetta", "", ["cucina"])])
        profiles, _, _ = compute_channel_profiles([channel, other], depth="P3")
        themes = {t["term"]: t["depth"] for t in profiles[0]["themes"]}
        self.assertEqual(themes.get("marchioveloce"), "P1")   # solo nei titoli
        self.assertEqual(themes.get("sottotitolo"), "P2")     # solo nelle descrizioni
        self.assertEqual(themes.get("retroscena"), "P3")      # solo nei commenti

    def test_pool_themes_rank_by_coverage(self):
        profiles, _, _ = compute_channel_profiles(_music_pool())
        themes = pool_themes([p["vector"] for p in profiles], min_channels=2)
        self.assertTrue(themes)
        # I temi del pool compaiono in almeno due canali e sono ordinati
        # per copertura decrescente.
        coverages = [t["channels"] for t in themes]
        self.assertEqual(coverages, sorted(coverages, reverse=True))
        self.assertTrue(all(t["channels"] >= 2 for t in themes))
        top_terms = {t["term"] for t in themes}
        self.assertTrue(top_terms & {"musica", "live", "cucina"})


class SimilarityTest(unittest.TestCase):
    def test_similarity_report_prefers_matching_theme(self):
        """Una descrizione su "cucina" pesa di più i canali di cucina."""
        profiles, idf, n_docs = compute_channel_profiles(_music_pool())
        by_id = {p["channel_id"]: p for p in profiles}
        kitchen = similarity_report(
            "ricette di cucina italiana", by_id["UCcuc1"]["vector"], idf, n_docs,
        )
        music = similarity_report(
            "ricette di cucina italiana", by_id["UCmus1"]["vector"], idf, n_docs,
        )
        self.assertGreater(kitchen["score"], music["score"])
        shared_terms = {t["term"] for t in kitchen["shared_terms"]}
        self.assertTrue(shared_terms & {"cucina", "ricetta"})

    def test_cosine_edge_cases(self):
        self.assertEqual(cosine({}, {"a": 1.0}), 0.0)
        self.assertEqual(cosine({"a": 1.0}, {"b": 1.0}), 0.0)
        self.assertAlmostEqual(cosine({"a": 1.0}, {"a": 1.0}), 1.0)


class CompositeScoreTest(unittest.TestCase):
    def _scored_pool(self):
        channels = [
            _channel("UCa", "A", "", [_video("x")], avg_views=100000, subscribers=900000,
                     engagement_rate=0.10),
            _channel("UCb", "B", "", [_video("y")], avg_views=50000, subscribers=100000,
                     engagement_rate=0.05),
            _channel("UCc", "C", "", [_video("z")], avg_views=1000, subscribers=5000,
                     engagement_rate=0.01),
        ]
        return channels

    def test_score_breakdown_components_and_weights(self):
        scored = score_channels(
            self._scored_pool(),
            query_text="",
            weights={"w_theme": 1.0, "w_geo": 0.0},
        )
        self.assertEqual(len(scored), 3)
        for channel in scored:
            breakdown = channel["score_breakdown"]
            self.assertEqual(
                set(breakdown),
                {"theme", "geo", "size", "popularity", "engagement", "velocity"},
            )
            for value in breakdown.values():
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)
        # Il canale con più views/iscrizioni/engagement vince il confronto.
        self.assertEqual(scored[0]["channel_id"], "UCa")
        # Percentili nel pool, non valori assoluti.
        self.assertEqual(scored[0]["score_breakdown"]["popularity"], 1.0)

    def test_weights_change_the_ranking(self):
        channels = [
            _channel("UCviews", "Views", "",
                     [_video("calcio gol partita"), _video("calcio partita gol")],
                     avg_views=100000),
            _channel("UCtheme", "Theme", "",
                     [_video("cucina pasta ricetta"), _video("cucina ricetta dolci")],
                     avg_views=100),
        ]
        profiles, idf, n_docs = compute_channel_profiles(channels)
        vectors = {p["channel_id"]: p["vector"] for p in profiles}
        for channel in channels:
            channel["vector"] = vectors[channel["channel_id"]]
        popularity_first = score_channels(
            channels, query_text="cucina ricette", idf=idf, n_docs=n_docs,
            weights={"w_theme": 0.0, "w_popularity": 1.0, "w_geo": 0.0,
                     "w_size": 0.0, "w_engagement": 0.0, "w_velocity": 0.0},
        )
        theme_first = score_channels(
            channels, query_text="cucina ricette", idf=idf, n_docs=n_docs,
            weights={"w_theme": 1.0, "w_popularity": 0.0, "w_geo": 0.0,
                     "w_size": 0.0, "w_engagement": 0.0, "w_velocity": 0.0},
        )
        self.assertEqual(popularity_first[0]["channel_id"], "UCviews")
        self.assertEqual(theme_first[0]["channel_id"], "UCtheme")
        # I termini condivisi spiegano il punteggio del vincitore tematico.
        shared = {t["term"] for t in theme_first[0]["shared_terms"]}
        self.assertIn("cucina", shared)

    def test_cross_theme_ranking_normalizes_within_theme(self):
        """Il ranking cross-tema non premia i temi con views più alte."""
        channels = [
            _channel("UCgame1", "Game Uno", "", [_video("gameplay boss finale")],
                     avg_views=100000),
            _channel("UCgame2", "Game Due", "", [_video("gameplay livello segreto")],
                     avg_views=50000),
            _channel("UCfin1", "Finanza Uno", "", [_video("investimenti etf spiegati")],
                     avg_views=1000),
            _channel("UCfin2", "Finanza Due", "", [_video("finanza personale base")],
                     avg_views=500),
        ]
        profiles, idf, n_docs = compute_channel_profiles(channels)
        vectors = {p["channel_id"]: p["vector"] for p in profiles}
        for channel in channels:
            channel["vector"] = vectors[channel["channel_id"]]
        groups = ["gaming", "gaming", "finanza", "finanza"]
        global_score = score_channels(
            channels, idf=idf, n_docs=n_docs,
            weights={"w_theme": 0.0, "w_popularity": 1.0, "w_geo": 0.0,
                     "w_size": 0.0, "w_engagement": 0.0, "w_velocity": 0.0},
        )
        cross_score = score_channels(
            channels, idf=idf, n_docs=n_docs,
            weights={"w_theme": 0.0, "w_popularity": 1.0, "w_geo": 0.0,
                     "w_size": 0.0, "w_engagement": 0.0, "w_velocity": 0.0},
            theme_groups=groups, cross_theme=True,
        )
        global_fin1 = next(c for c in global_score if c["channel_id"] == "UCfin1")
        cross_fin1 = next(c for c in cross_score if c["channel_id"] == "UCfin1")
        # Nel pool globale il miglior canale di finanza è schiacciato dalle
        # views del gaming; nel ranking cross-tema è il top del suo tema.
        self.assertLess(global_fin1["score_breakdown"]["popularity"], 1.0)
        self.assertEqual(cross_fin1["score_breakdown"]["popularity"], 1.0)
        self.assertGreater(cross_fin1["score"], global_fin1["score"])

    def test_cross_theme_singleton_groups_are_neutral(self):
        """Un canale solo nel suo tema non prende 1.0 gratis: vale 0.5."""
        channels = [
            _channel("UCg1", "G1", "", [_video("gameplay boss")], avg_views=100000),
            _channel("UCg2", "G2", "", [_video("gameplay segreto")], avg_views=50000),
            _channel("UClone", "Solo", "", [_video("finanza etf")], avg_views=100),
        ]
        profiles, idf, n_docs = compute_channel_profiles(channels)
        vectors = {p["channel_id"]: p["vector"] for p in profiles}
        for channel in channels:
            channel["vector"] = vectors[channel["channel_id"]]
        scored = score_channels(
            channels, idf=idf, n_docs=n_docs,
            weights={"w_theme": 0.0, "w_popularity": 1.0, "w_geo": 0.0,
                     "w_size": 0.0, "w_engagement": 0.0, "w_velocity": 0.0},
            theme_groups=["gaming", "gaming", "finanza"], cross_theme=True,
        )
        lone = next(c for c in scored if c["channel_id"] == "UClone")
        self.assertEqual(lone["score_breakdown"]["popularity"], 0.5)
        # Dentro il tema gaming la competizione resta reale.
        g1 = next(c for c in scored if c["channel_id"] == "UCg1")
        self.assertEqual(g1["score_breakdown"]["popularity"], 1.0)

    def test_velocity_is_zero_when_no_data(self):
        scored = score_channels(self._scored_pool(), query_text="")
        for channel in scored:
            self.assertEqual(channel["score_breakdown"]["velocity"], 0.0)

    def test_percentile_ranks_ties_share_the_average(self):
        ranks = percentile_ranks([10.0, 10.0, 30.0])
        self.assertEqual(ranks[0], ranks[1])
        self.assertGreater(ranks[2], ranks[0])
        self.assertEqual(percentile_ranks([0.0, 0.0]), [0.0, 0.0])


class EmergingCirclesTest(unittest.TestCase):
    def _hybrid_pool(self):
        pool = _music_pool()
        pool.append(
            _channel(
                "UChybrid", "Cucina Rock", "Cucina con la musica giusta",
                [
                    _video("Pasta e musica live", "Cucina con musica dal vivo",
                           ["cucina", "musica"]),
                    _video("Ricetta rock in cucina", "Musica e ricette", ["cucina", "rock"]),
                ],
            )
        )
        return pool

    def test_circles_emerge_with_readable_labels(self):
        """Pool musica/cucina/tech: i cerchi emergono con label attendibili."""
        profiles, _, _ = compute_channel_profiles(self._hybrid_pool())
        circles = emerging_circles(profiles, top_n=8)
        self.assertTrue(circles)
        for circle in circles:
            # Label: 2–3 termini principali + conteggio canali.
            self.assertIn(f"({circle['channel_count']} canali)", circle["label"])
            self.assertTrue(1 <= len(circle["label_terms"]) <= 3)
            self.assertEqual(circle["channel_count"], len(circle["channels"]))
        # I temi attesi emergono come cerchi.
        circle_terms = {circle["term"] for circle in circles}
        self.assertTrue(circle_terms & {"musica", "cucina"})

    def test_hybrid_channel_belongs_to_two_circles(self):
        """Il canale ibrido food-music appartiene a entrambi i cerchi."""
        profiles, _, _ = compute_channel_profiles(self._hybrid_pool())
        circles = emerging_circles(profiles, top_n=8)
        memberships = [
            circle["term"] for circle in circles if "UChybrid" in circle["channels"]
        ]
        self.assertIn("musica", memberships)
        self.assertIn("cucina", memberships)

    def test_circle_intersection_returns_hybrid_channels(self):
        """L'intersezione di due cerchi restituisce esattamente gli ibridi."""
        profiles, _, _ = compute_channel_profiles(self._hybrid_pool())
        circles = emerging_circles(profiles, top_n=8)
        by_term = {circle["term"]: circle for circle in circles}
        intersection = circle_intersection(
            circles, by_term["musica"]["id"], by_term["cucina"]["id"],
        )
        self.assertEqual(intersection["channels"], ["UChybrid"])
        self.assertEqual(intersection["count"], 1)

    def test_intersection_with_unknown_circle_is_empty(self):
        profiles, _, _ = compute_channel_profiles(self._hybrid_pool())
        circles = emerging_circles(profiles)
        self.assertEqual(circle_intersection(circles, "nope", "circle-0")["count"], 0)


if __name__ == "__main__":
    unittest.main()
