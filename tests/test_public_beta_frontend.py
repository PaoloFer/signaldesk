import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


class PublicBetaFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.landing = (STATIC / "landing.html").read_text(encoding="utf-8")
        cls.try_html = (STATIC / "try.html").read_text(encoding="utf-8")
        cls.try_js = (STATIC / "try.js").read_text(encoding="utf-8")
        cls.main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    def test_landing_leads_to_accountless_preview(self):
        self.assertIn("Inserisci un argomento, alcuni canali o video", self.landing)
        self.assertIn('href="/try"', self.landing)
        self.assertIn("Prova senza account", self.landing)

    def test_try_page_has_search_results_and_account_boundary(self):
        for element_id in (
            "public-analysis-form", "topic", "channels", "videos",
            "analysis-progress", "analysis-results", "metric-grid",
            "term-chart", "format-chart", "channel-list",
        ):
            self.assertIn(f'id="{element_id}"', self.try_html)
        self.assertIn("Questa preview non viene salvata", self.try_html)
        self.assertIn("/api/public/preview", self.try_js)

    def test_public_routes_are_indexed_and_api_is_whitelisted(self):
        self.assertIn('@app.get("/try")', self.main)
        self.assertIn('@app.post("/api/public/preview")', self.main)
        self.assertIn('"/api/public/preview"', self.main)
        self.assertIn("{origin}/try", self.main)


if __name__ == "__main__":
    unittest.main()
