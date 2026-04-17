import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from thesis_manager import ThesisManager


class TestStopLossSuppression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "theses.json"
        self.path.write_text(json.dumps({"theses": [], "version": 1}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_thesis_lookup_returns_match(self):
        mgr = ThesisManager(self.path)
        mgr.add(
            ticker="COIN",
            thesis="x",
            invalidation=["close < 140 for 5 sessions"],
            conviction=7,
            pre_mortem="y",
            created="2026-04-17",
        )
        fake_agent = MagicMock()
        fake_agent.thesis_manager = mgr
        from whale_watcher_agent import PositionAnalyzer
        analyzer = PositionAnalyzer.__new__(PositionAnalyzer)
        analyzer.market_agent = fake_agent
        analyzer.position = {"ticker": "COIN", "symbol": "COIN"}
        analyzer.ticker = "COIN"
        result = analyzer._active_thesis()
        self.assertIsNotNone(result)
        self.assertEqual(result["ticker"], "COIN")

    def test_no_thesis_manager_returns_none(self):
        from whale_watcher_agent import PositionAnalyzer
        analyzer = PositionAnalyzer.__new__(PositionAnalyzer)
        analyzer.market_agent = None
        analyzer.position = {"ticker": "COIN"}
        analyzer.ticker = "COIN"
        self.assertIsNone(analyzer._active_thesis())

    def test_invalidated_thesis_does_not_suppress(self):
        mgr = ThesisManager(self.path)
        t = mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        mgr.set_status(t["id"], "invalidated")
        fake_agent = MagicMock()
        fake_agent.thesis_manager = mgr
        from whale_watcher_agent import PositionAnalyzer
        analyzer = PositionAnalyzer.__new__(PositionAnalyzer)
        analyzer.market_agent = fake_agent
        analyzer.position = {"ticker": "COIN", "symbol": "COIN"}
        analyzer.ticker = "COIN"
        self.assertIsNone(analyzer._active_thesis())


if __name__ == "__main__":
    unittest.main()
