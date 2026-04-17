"""Parses and evaluates invalidation conditions for thesis-override layer.

Grammar (price):     close {<,<=,>,>=} {number} [for {N} sessions]
Grammar (technical): <lhs> {<,<=,>,>=} {number} [for {N} sessions]
                     where <lhs> in {rsi, weekly_rsi, macd_hist, sma_50, sma_200}
Grammar (narrative): anything else -> auto=False, manual check only.

Technical conditions are parsed here but evaluation is deferred to Phase 2.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


TECHNICAL_LHS = {"rsi", "weekly_rsi", "macd_hist", "sma_50", "sma_200"}
PRICE_RE = re.compile(
    r"^\s*close\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s+for\s+(\d+)\s+sessions?)?\s*$",
    re.IGNORECASE,
)
TECH_RE = re.compile(
    r"^\s*([a-z_]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)"
    r"(?:\s+for\s+(\d+)\s+sessions?)?\s*$",
    re.IGNORECASE,
)


@dataclass
class Condition:
    type: str                       # "price" | "technical" | "narrative"
    raw: str                        # original text as typed by user
    op: Optional[str] = None        # "<", "<=", ">", ">="
    threshold: Optional[float] = None
    duration_sessions: int = 1
    lhs: Optional[str] = None       # "close" or technical lhs
    auto: bool = True               # False for narrative


@dataclass
class EvalResult:
    tripped: bool
    detail: str = ""


class InvalidationEvaluator:
    """Stateless parser + evaluator. All inputs passed explicitly."""

    def parse(self, raw: str) -> Condition:
        m = PRICE_RE.match(raw)
        if m:
            op, threshold, dur = m.group(1), float(m.group(2)), m.group(3)
            return Condition(
                type="price", raw=raw, op=op, threshold=threshold,
                duration_sessions=int(dur) if dur else 1,
                lhs="close", auto=True,
            )
        m = TECH_RE.match(raw)
        if m and m.group(1).lower() in TECHNICAL_LHS:
            lhs, op, threshold, dur = (
                m.group(1).lower(), m.group(2), float(m.group(3)), m.group(4)
            )
            return Condition(
                type="technical", raw=raw, op=op, threshold=threshold,
                duration_sessions=int(dur) if dur else 1,
                lhs=lhs, auto=True,
            )
        # narrative fallback
        return Condition(type="narrative", raw=raw, auto=False)

    def evaluate(self, cond: Condition, closes: List[float] = None,
                 indicators: dict = None) -> EvalResult:
        if cond.type == "narrative":
            return EvalResult(tripped=False, detail="manual_check")
        if cond.type == "price":
            if not closes:
                return EvalResult(tripped=False, detail="no_data")
            window = closes[-cond.duration_sessions:]
            if len(window) < cond.duration_sessions:
                return EvalResult(tripped=False, detail="insufficient_history")
            all_breach = all(self._compare(c, cond.op, cond.threshold) for c in window)
            if all_breach:
                return EvalResult(
                    tripped=True,
                    detail=f"close={window[-1]} {cond.op} {cond.threshold} "
                           f"for {cond.duration_sessions} sessions",
                )
            return EvalResult(tripped=False, detail=f"close={window[-1]}")
        if cond.type == "technical":
            # Phase 2 implements this; Phase 1 treats as not-yet-evaluable
            return EvalResult(tripped=False, detail="technical_deferred_to_phase_2")
        return EvalResult(tripped=False, detail="unknown_type")

    @staticmethod
    def _compare(value: float, op: str, threshold: float) -> bool:
        return {
            "<":  value <  threshold,
            "<=": value <= threshold,
            ">":  value >  threshold,
            ">=": value >= threshold,
        }[op]
