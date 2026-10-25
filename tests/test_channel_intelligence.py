import unittest

from app.channel_intelligence import build_channel_overlap


class ChannelOverlapTest(unittest.TestCase):
    def test_jaccard_overlap_between_channels(self):
        comments = [
            {"author_hash": "a1", "channel_title": "Canale A"},
            {"author_hash": "a2", "channel_title": "Canale A"},
            {"author_hash": "a2", "channel_title": "Canale B"},
            {"author_hash": "a3", "channel_title": "Canale B"},
            {"author_hash": "a4", "channel_title": "Canale C"},
        ]
        result = build_channel_overlap(comments)
        self.assertEqual(result["channels"], ["Canale A", "Canale B", "Canale C"])

        pair = next(p for p in result["top_pairs"] if p["left"] == "Canale A" and p["right"] == "Canale B")
        # A={a1,a2}, B={a2,a3} -> intersezione=1, unione=3 -> 0.333
        self.assertAlmostEqual(pair["overlap"], 1 / 3, places=3)
        self.assertEqual(pair["shared_authors"], 1)

        # A e C non hanno autori in comune
        no_overlap = [p for p in result["top_pairs"] if "Canale C" in {p["left"], p["right"]}]
        self.assertEqual(no_overlap, [])

    def test_empty_comments(self):
        result = build_channel_overlap([])
        self.assertEqual(result["channels"], [])
        self.assertEqual(result["matrix"], [])
        self.assertEqual(result["top_pairs"], [])


if __name__ == "__main__":
    unittest.main()
