"""Contratti statici del wizard frontend video/panorama (milestone N5)."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


STATIC = Path(__file__).resolve().parent.parent / "static"


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])


class PanoramaFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "style.css").read_text(encoding="utf-8")

    def test_wizard_controls_exist_and_ids_are_unique(self):
        parser = _IdCollector()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        required = {
            "wizard-mode-videos", "wizard-mode-channels",
            "wizard-niche-max-subs", "wizard-evidence-depth",
            "wizard-second-wave", "wizard-cross-theme",
            "preview-min-subs", "preview-max-subs",
            "preview-channel-min-views", "preview-channel-max-views",
            "preview-themes-include", "preview-themes-exclude",
            "preview-promoted-only", "wizard-quota-estimate",
            "materialize-curated", "materialize-rule-based",
        }
        self.assertTrue(required.issubset(set(parser.ids)))
        self.assertIn("POPOLARI REGIONALI", self.html)
        self.assertNotIn("<span>PANORAMA</span>", self.html)

    def test_api_contracts_keep_video_flow_and_add_panorama(self):
        self.assertIn('mode: state.wizardMode', self.js)
        self.assertIn('/preview`', self.js)
        self.assertIn('/materialize`', self.js)
        self.assertIn('/channels`', self.js)
        self.assertIn('membership_mode: membershipMode', self.js)
        self.assertIn('materializeWizard("curated")', self.js)
        self.assertIn('materializeWizard("rule_based")', self.js)
        self.assertIn('/populate`', self.js)
        self.assertIn('content_ids: Array.from(state.wizardSelected)', self.js)

    def test_advanced_filters_and_dialog_merge_are_wired(self):
        for key in (
            "evidence_depth", "second_wave_top_k", "cross_theme_ranking",
            "max_subscribers",
        ):
            self.assertIn(key, self.js)
        self.assertIn('filters[`w_${name}`]', self.js)
        self.assertIn('["theme", "geo", "size", "popularity", "engagement", "velocity"]', self.js)
        self.assertIn("...(existing?.filters || {})", self.js)
        self.assertIn("...(existing?.definition || {})", self.js)

    def test_channel_table_has_mobile_card_layout(self):
        self.assertIn("channel-preview-table", self.js)
        self.assertIn("score-breakdown", self.js)
        self.assertIn("channel-themes", self.js)
        self.assertIn(".channel-preview-table td::before", self.css)
        self.assertIn("content: attr(data-label)", self.css)


if __name__ == "__main__":
    unittest.main()
