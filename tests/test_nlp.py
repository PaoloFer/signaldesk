import unittest

from app.nlp import analyze_text


class NlpRuleBasedTest(unittest.TestCase):
    def test_detects_positive_italian(self):
        result = analyze_text("Video molto utile e ben fatto, grazie!")
        self.assertEqual(result["sentiment"], "positive")
        self.assertGreater(result["sentiment_score"], 0)
        self.assertEqual(result["intent"], "appreciation")

    def test_detects_negative_italian(self):
        result = analyze_text("Pessimo video, orribile contenuto")
        self.assertEqual(result["sentiment"], "negative")
        self.assertLess(result["sentiment_score"], 0)

    def test_detects_question(self):
        result = analyze_text("Come posso iniziare ad allenarmi?")
        self.assertEqual(result["intent"], "question")

    def test_detects_toxicity(self):
        result = analyze_text("Sei un idiota, questo video fa schifo")
        self.assertGreater(result["toxicity_score"], 0)
        self.assertTrue(any("idiota" in flag for flag in result["flags"]))

    def test_complaint_pattern(self):
        result = analyze_text("Non funziona il link che hai messo in descrizione")
        self.assertEqual(result["intent"], "complaint")


if __name__ == "__main__":
    unittest.main()
