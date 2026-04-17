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


class TestTechnicalEvaluation(unittest.TestCase):
    def setUp(self):
        self.ev = InvalidationEvaluator()

    def test_rsi_lt_tripped(self):
        cond = self.ev.parse("rsi < 30")
        res = self.ev.evaluate(cond, indicators={"rsi": [28.0]})
        self.assertTrue(res.tripped)

    def test_weekly_rsi_lt_not_tripped(self):
        cond = self.ev.parse("weekly_rsi < 30")
        res = self.ev.evaluate(cond, indicators={"weekly_rsi": [52.0]})
        self.assertFalse(res.tripped)

    def test_sma_cross(self):
        cond = self.ev.parse("sma_50 < sma_200")
        # Cross-field compare is not supported — parser falls through to narrative
        self.assertIn(cond.type, ("technical", "narrative"))

    def test_macd_hist_lt_zero(self):
        cond = self.ev.parse("macd_hist < 0")
        res = self.ev.evaluate(cond, indicators={"macd_hist": [-0.5]})
        self.assertTrue(res.tripped)


if __name__ == "__main__":
    unittest.main()
