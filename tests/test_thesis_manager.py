import json
import tempfile
import unittest
from pathlib import Path

from thesis_manager import ThesisManager, InvalidStatusTransition


class TestThesisManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "theses.json"
        self.path.write_text(json.dumps({"theses": [], "version": 1}))
        self.mgr = ThesisManager(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_empty(self):
        self.assertEqual(self.mgr.list_all(), [])

    def test_add_thesis(self):
        t = self.mgr.add(
            ticker="COIN",
            thesis="BTC halving cycle bottom",
            invalidation=["close < 140 for 5 sessions"],
            conviction=7,
            pre_mortem="If BTC doesn't bottom by Q3",
            created="2026-04-17",
        )
        self.assertEqual(t["id"], "coin-2026-04-17")
        self.assertEqual(t["status"], "active")
        self.assertEqual(len(t["invalidation_criteria"]), 1)
        self.assertEqual(t["invalidation_criteria"][0]["type"], "price")

    def test_add_persists_to_disk(self):
        self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        reloaded = ThesisManager(self.path)
        self.assertEqual(len(reloaded.list_all()), 1)

    def test_get_active_by_ticker(self):
        self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        active = self.mgr.get_active("COIN")
        self.assertIsNotNone(active)
        self.assertEqual(active["ticker"], "COIN")

    def test_get_active_returns_none_for_invalidated(self):
        t = self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        self.mgr.set_status(t["id"], "invalidated")
        self.assertIsNone(self.mgr.get_active("COIN"))

    def test_valid_status_transition_active_to_invalidated(self):
        t = self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        self.mgr.set_status(t["id"], "invalidated")
        self.assertEqual(self.mgr.list_all()[0]["status"], "invalidated")

    def test_invalid_transition_raises(self):
        t = self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-04-17",
        )
        self.mgr.set_status(t["id"], "invalidated")
        # Can't go invalidated -> active
        with self.assertRaises(InvalidStatusTransition):
            self.mgr.set_status(t["id"], "active")

    def test_corrupt_json_backs_up_and_starts_empty(self):
        self.path.write_text("{not valid json")
        mgr = ThesisManager(self.path)
        self.assertEqual(mgr.list_all(), [])
        backups = list(self.path.parent.glob("theses.json.corrupt-*"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
