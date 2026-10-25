import unittest
from pathlib import Path


STATIC = Path(__file__).resolve().parent.parent / "static"


class DataGuidanceFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "style.css").read_text(encoding="utf-8")

    def test_dashboard_explains_data_provenance(self):
        for label in ("OSSERVATO", "CALCOLATO", "EURISTICO"):
            self.assertIn(label, self.html)
        self.assertIn("I risultati descrivono il campione raccolto", self.html)
        self.assertIn("module-guide", self.html)
        self.assertGreaterEqual(self.html.count("INDIVIDUA"), 5)
        self.assertGreaterEqual(self.html.count("COME NASCE"), 4)
        self.assertGreaterEqual(self.html.count("TI AIUTA A"), 5)

    def test_ambiguous_metrics_have_scope_notes(self):
        html = self.html.lower()
        for explanation in (
            "views cumulative attuali",
            "non equivale alla sovrapposizione di viewer o subscriber",
            "non quota di spesa o di mercato",
            "non misura investimento, impression sponsorizzate o ROI",
            "corrispondenza normalizzata esatta",
        ):
            self.assertIn(explanation.lower(), html)

    def test_metric_cards_expose_data_kind(self):
        self.assertIn("kindLabels", self.js)
        self.assertIn('"heuristic"', self.js)
        self.assertIn(".data-kind", self.css)
        self.assertIn(".module-guide", self.css)
        self.assertIn(".panel-note", self.css)

    def test_modules_use_truthful_comparative_visuals(self):
        for visual in (
            "ranked-row", "niche-meter", "trajectory-meter",
            "overlap-meter", "ranked-sponsor", "is-peak",
        ):
            self.assertIn(visual, self.js)
            self.assertIn(f".{visual}", self.css)
        self.assertIn("item.content_share", self.js)
        self.assertIn("item.shared_authors", self.js)
        self.assertIn("Math.abs(item.growth_percent)", self.js)


if __name__ == "__main__":
    unittest.main()
