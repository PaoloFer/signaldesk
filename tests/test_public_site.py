import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


class PublicSiteContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.landing = (STATIC / "landing.html").read_text(encoding="utf-8")
        cls.login_js = (STATIC / "login.js").read_text(encoding="utf-8")
        cls.main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    def test_landing_has_search_metadata_and_product_content(self):
        self.assertIn('<meta name="description"', self.landing)
        self.assertIn('<meta name="robots" content="index,follow', self.landing)
        self.assertIn('itemtype="https://schema.org/SoftwareApplication"', self.landing)
        self.assertIn('href="/login"', self.landing)
        self.assertIn('id="funzioni"', self.landing)

    def test_private_app_and_search_endpoints_are_wired(self):
        self.assertIn('@app.get("/app")', self.main)
        self.assertIn('@app.get("/robots.txt")', self.main)
        self.assertIn('@app.get("/sitemap.xml")', self.main)
        self.assertIn('window.location.href = "/app"', self.login_js)


if __name__ == "__main__":
    unittest.main()
