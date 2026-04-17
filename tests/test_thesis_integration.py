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


class TestInvalidationTripTransitionsStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "theses.json"
        self.path.write_text(json.dumps({"theses": [], "version": 1}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_price_invalidation_trips_to_invalidated(self):
        from whale_watcher_agent import evaluate_thesis_invalidations
        mgr = ThesisManager(self.path)
        mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 140"],
            conviction=7, pre_mortem="y", created="2026-04-17",
        )
        market_data = {"COIN": {"closes": [135.0]}}
        tripped = evaluate_thesis_invalidations(mgr, market_data)
        self.assertEqual(len(tripped), 1)
        self.assertEqual(mgr.list_all()[0]["status"], "invalidated")

    def test_price_not_tripped_stays_active(self):
        from whale_watcher_agent import evaluate_thesis_invalidations
        mgr = ThesisManager(self.path)
        mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 140"],
            conviction=7, pre_mortem="y", created="2026-04-17",
        )
        market_data = {"COIN": {"closes": [199.83]}}
        tripped = evaluate_thesis_invalidations(mgr, market_data)
        self.assertEqual(tripped, [])
        self.assertEqual(mgr.list_all()[0]["status"], "active")


if __name__ == "__main__":
    unittest.main()
