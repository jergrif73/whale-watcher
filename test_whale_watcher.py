import json
import unittest
from pathlib import Path

from whale_watcher_agent import MarketAgent, TechnicalAnalyzer


class TestMarketAgent(unittest.TestCase):
    """Smoke tests. Full integration tests live under tests/."""

    def setUp(self):
        self.agent = MarketAgent()

    def test_agent_instantiates(self):
        """MarketAgent __init__ should not raise and should set core attrs."""
        self.assertIsNotNone(self.agent.timestamp)
        self.assertEqual(self.agent.recent_signals, [])
        self.assertFalse(self.agent.has_critical_news)

    def test_thesis_manager_present_when_file_exists(self):
        """If docs/data/theses.json exists, thesis_manager is wired up."""
        if Path("docs/data/theses.json").exists():
            self.assertIsNotNone(self.agent.thesis_manager)

    def test_generate_dashboard_html_renders_from_fixture(self):
        """generate_dashboard_html must produce HTML from a pre-built
        dashboard.json fixture without needing network calls."""
        fixture = Path("docs/data/dashboard.json")
        if not fixture.exists():
            self.skipTest("dashboard.json fixture not present")
        with open(fixture, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("whale_activity", [])
        html = self.agent.generate_dashboard_html(data)
        self.assertIn("<html", html.lower())
        self.assertIn("Whale Watcher", html)

    def test_sparkline_png_is_valid(self):
        """_build_sparkline_png must return a data URI whose base64 payload starts with the PNG magic bytes."""
        prices = [100.0 + i * 0.5 for i in range(63)]  # ~3 months of daily prices
        data_uri = TechnicalAnalyzer._build_sparkline_png(prices)
        self.assertTrue(data_uri.startswith("data:image/png;base64,"),
                        "data URI must have PNG MIME prefix")
        b64_payload = data_uri.split(",", 1)[1]
        # PNG magic bytes base64-encode to "iVBORw0KGgo" at the start of the stream
        self.assertTrue(b64_payload.startswith("iVBORw0KGgo"),
                        f"PNG magic bytes not found; got prefix: {b64_payload[:20]!r}")
        print("\n✅ TEST PASSED: sparkline PNG magic bytes confirmed.")

if __name__ == '__main__':
    unittest.main()
