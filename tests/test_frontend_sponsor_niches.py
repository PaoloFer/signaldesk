"""Contratti statici UI dei bacini sponsor (milestone N7)."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


STATIC = Path(__file__).resolve().parent.parent / "static"


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag, attrs):
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.add(element_id)


class SponsorNichesFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "style.css").read_text(encoding="utf-8")

    def test_sponsor_workspace_controls_exist(self):
        parser = _IdCollector()
        parser.feed(self.html)
        required = {
            "sponsor-basin", "sponsor-basin-content", "sponsor-niche-form",
            "sponsor-niche-name", "create-sponsor-niche", "niche-brand-list",
            "sponsor-compare-left", "sponsor-compare-right",
            "sponsor-compare-button", "sponsor-comparison",
        }
        self.assertTrue(required.issubset(parser.ids))
        self.assertIn("Crea nicchia da questo brand", self.html)

    def test_n7_endpoints_and_payload_are_wired(self):
        for endpoint in (
            "/sponsor-basin?days=", "/api/adv/niches/brands?",
            "/api/adv/compare?", "/api/niches/from-sponsor",
        ):
            self.assertIn(endpoint, self.js)
        for field in ("project_id", "entity_id", "name", "days", "platform"):
            self.assertIn(f"{field}:", self.js)

    def test_project_reset_and_all_ui_states_are_present(self):
        self.assertGreaterEqual(self.js.count("resetSponsorWorkspace()"), 3)
        for label in ("Caricamento", "Impossibile", "Nessun", "non disponibile"):
            self.assertIn(label, self.js)
        self.assertIn("brand-share", self.css)
        self.assertIn("sponsor-overlap", self.css)


if __name__ == "__main__":
    unittest.main()
