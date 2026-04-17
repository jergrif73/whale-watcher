import unittest
from invalidation_evaluator import InvalidationEvaluator, Condition, EvalResult


class TestInvalidationEvaluator(unittest.TestCase):
    def setUp(self):
        self.ev = InvalidationEvaluator()

    # --- parsing ---
    def test_parses_simple_price_lt(self):
        cond = self.ev.parse("close < 140")
        self.assertEqual(cond.type, "price")
        self.assertEqual(cond.op, "<")
        self.assertEqual(cond.threshold, 140.0)
        self.assertEqual(cond.duration_sessions, 1)

    def test_parses_price_with_duration(self):
        cond = self.ev.parse("close < 140 for 5 sessions")
        self.assertEqual(cond.duration_sessions, 5)

    def test_parses_all_operators(self):
        for op in ["<", "<=", ">", ">="]:
            cond = self.ev.parse(f"close {op} 100")
            self.assertEqual(cond.op, op)

    def test_parses_narrative_as_manual(self):
        cond = self.ev.parse("BTC fails to reclaim cycle high by Q3")
        self.assertEqual(cond.type, "narrative")
        self.assertFalse(cond.auto)

    # --- evaluation: price ---
    def test_evaluate_price_lt_tripped(self):
        cond = self.ev.parse("close < 140")
        res = self.ev.evaluate(cond, closes=[138.0])
        self.assertTrue(res.tripped)
        self.assertIn("close=138.0", res.detail)

    def test_evaluate_price_lt_not_tripped(self):
        cond = self.ev.parse("close < 140")
        res = self.ev.evaluate(cond, closes=[150.0])
        self.assertFalse(res.tripped)

    def test_evaluate_price_duration_requires_sustained_breach(self):
        cond = self.ev.parse("close < 140 for 5 sessions")
        # Only 3 of last 5 below threshold -> not tripped
        res = self.ev.evaluate(cond, closes=[150, 138, 142, 137, 139])
        self.assertFalse(res.tripped)

    def test_evaluate_price_duration_tripped_on_all_5(self):
        cond = self.ev.parse("close < 140 for 5 sessions")
        res = self.ev.evaluate(cond, closes=[138, 137, 139, 135, 134])
        self.assertTrue(res.tripped)

    def test_evaluate_narrative_is_never_tripped(self):
        cond = self.ev.parse("BTC fails by Q3")
        res = self.ev.evaluate(cond, closes=[1.0])
        self.assertFalse(res.tripped)
        self.assertEqual(res.detail, "manual_check")


if __name__ == "__main__":
    unittest.main()
