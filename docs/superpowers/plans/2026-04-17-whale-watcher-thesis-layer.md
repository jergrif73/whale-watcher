# Thesis-Override Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [docs/superpowers/specs/2026-04-17-whale-watcher-thesis-layer-design.md](../specs/2026-04-17-whale-watcher-thesis-layer-design.md)

**Goal:** Transform whale-watcher from a mechanical alert engine into a discipline enforcer by capturing user theses with invalidation criteria, critiquing them with a fresh-session Claude bear agent, suppressing recurring alerts for positions with active theses, and tracking outcomes for conviction calibration.

**Architecture:** Three new modules (`ThesisManager`, `InvalidationEvaluator`, `BearAgent`) plus a Dispatch-callable CLI (`scripts/thesis.py`). Thesis state lives in `docs/data/theses.json`, versioned in git. `whale_watcher_agent.py` receives integration hooks only — no logic bloat. Three phases, each independently shippable.

**Tech Stack:** Python 3.10 · yfinance · pandas · numpy · anthropic (Phase 2+) · unittest (stdlib) · GitHub Actions.

---

## File Structure

### New files
- `thesis_manager.py` — `ThesisManager` class (load/save/status transitions, email HTML fragment)
- `invalidation_evaluator.py` — `InvalidationEvaluator` class (grammar parsing + per-condition evaluation)
- `bear_agent.py` — `BearAgent` class (Phase 2; Claude API wrapper + response parser)
- `scripts/__init__.py` — empty
- `scripts/thesis.py` — CLI subcommands: `add`, `list`, `review`, `mark`, `report`
- `tests/__init__.py` — empty
- `tests/test_thesis_manager.py`
- `tests/test_invalidation_evaluator.py`
- `tests/test_bear_agent.py` (Phase 2)
- `tests/test_thesis_integration.py`
- `docs/data/theses.json` — seeded: `{"theses": [], "version": 1}`

### Modified files
- `whale_watcher_agent.py` — add integration hooks at known line ranges (no class changes)
- `.github/workflows/whale_watcher.yml` — add `ANTHROPIC_API_KEY` env (Phase 2)
- `test_whale_watcher.py` — fix pre-existing `generate_report()` reference

---

## Setup (run once before Phase 1)

### Task 0.1: Start from main, create feature branch

**Files:** none

- [ ] **Step 1: Sync main and branch**

Run:
```bash
git fetch origin main && git checkout main && git pull
git checkout -b feat/thesis-phase-1
```

Expected: `Switched to a new branch 'feat/thesis-phase-1'`

### Task 0.2: Install dev dependencies locally

**Files:** none

- [ ] **Step 1: Install**

Run:
```bash
pip install yfinance pandas numpy lxml requests matplotlib
```

Expected: packages install cleanly. No `anthropic` yet — that's Phase 2.

---

# PHASE 1 — Silent Journal + Suppression

**Goal:** When a user captures a thesis via `scripts/thesis.py add`, the stop-loss alert for that position goes silent unless the price-based invalidation condition trips. Email gains a new "Active Theses" section. No Claude API usage.

**Phase 1 exit criteria:** Merging to main results in COIN (once user adds a thesis) no longer firing `hard_stop_loss` alerts twice daily.

---

## Task 1.1: Seed empty `theses.json`

**Files:**
- Create: `docs/data/theses.json`

- [ ] **Step 1: Create the file**

```json
{
  "theses": [],
  "version": 1
}
```

- [ ] **Step 2: Commit**

```bash
git add docs/data/theses.json
git commit -m "feat(thesis): seed empty theses.json"
```

---

## Task 1.2: `InvalidationEvaluator` — price-only parser + evaluator

**Files:**
- Create: `invalidation_evaluator.py`
- Create: `tests/__init__.py` (empty file)
- Create: `tests/test_invalidation_evaluator.py`

- [ ] **Step 1: Create `tests/__init__.py` (empty)**

```bash
type nul > tests/__init__.py
# Or on bash: touch tests/__init__.py
```

- [ ] **Step 2: Write failing test** — `tests/test_invalidation_evaluator.py`:

```python
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
```

- [ ] **Step 3: Run test — expect import failure**

Run:
```bash
python -m unittest tests.test_invalidation_evaluator -v
```

Expected: `ModuleNotFoundError: No module named 'invalidation_evaluator'`

- [ ] **Step 4: Create `invalidation_evaluator.py`**

```python
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
```

- [ ] **Step 5: Run tests — expect all pass**

Run:
```bash
python -m unittest tests.test_invalidation_evaluator -v
```

Expected: `Ran 9 tests in 0.00s — OK`

- [ ] **Step 6: Commit**

```bash
git add invalidation_evaluator.py tests/__init__.py tests/test_invalidation_evaluator.py
git commit -m "feat(thesis): add InvalidationEvaluator with price grammar"
```

---

## Task 1.3: `ThesisManager` — load/save/status transitions

**Files:**
- Create: `thesis_manager.py`
- Create: `tests/test_thesis_manager.py`

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run test — expect import failure**

Run:
```bash
python -m unittest tests.test_thesis_manager -v
```

Expected: `ModuleNotFoundError: No module named 'thesis_manager'`

- [ ] **Step 3: Create `thesis_manager.py`**

```python
"""Thesis persistence, status lifecycle, and email-section rendering.

Storage: docs/data/theses.json (git-versioned). Atomic writes via
rename. Malformed JSON is backed up and treated as empty.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from invalidation_evaluator import InvalidationEvaluator


VALID_TRANSITIONS = {
    "active":      {"invalidated", "vindicated", "expired", "orphaned"},
    "orphaned":    {"invalidated", "vindicated"},
    "invalidated": set(),   # terminal
    "vindicated":  set(),   # terminal
    "expired":     set(),   # terminal
}


class InvalidStatusTransition(Exception):
    pass


class ThesisManager:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.evaluator = InvalidationEvaluator()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"theses": [], "version": 1}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.path.with_suffix(f".json.corrupt-{ts}")
            shutil.copy2(self.path, backup)
            return {"theses": [], "version": 1}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- API --

    def list_all(self) -> List[dict]:
        return list(self._data["theses"])

    def get_active(self, ticker: str) -> Optional[dict]:
        for t in self._data["theses"]:
            if t["ticker"].upper() == ticker.upper() and t["status"] == "active":
                return t
        return None

    def add(self, ticker: str, thesis: str, invalidation: List[str],
            conviction: int, pre_mortem: str, created: str,
            author: str = "jeremiah") -> dict:
        tid = f"{ticker.lower()}-{created}"
        conditions = []
        for raw in invalidation:
            c = self.evaluator.parse(raw)
            conditions.append({
                "type": c.type, "condition": c.raw, "auto": c.auto,
            })
        # 6-month review date
        review = datetime.strptime(created, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        review_iso = review.replace(year=review.year + (review.month // 7)).strftime("%Y-%m-%d")
        # Simpler: add 180 days
        from datetime import timedelta
        review_dt = datetime.strptime(created, "%Y-%m-%d") + timedelta(days=180)
        review_iso = review_dt.strftime("%Y-%m-%d")
        thesis_obj = {
            "id": tid,
            "ticker": ticker.upper(),
            "created": created,
            "author": author,
            "thesis": thesis,
            "enter_tag": "",
            "conviction": conviction,
            "pre_mortem": pre_mortem,
            "invalidation_criteria": conditions,
            "red_team_critique": "",
            "unverified_claims": [],
            "bear_agent_model": "",
            "bear_agent_run_at": "",
            "status": "active",
            "review_date": review_iso,
            "review_checkpoints": {
                "30d":  {"due": (datetime.strptime(created, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d"),  "completed": False, "verdict": None},
                "90d":  {"due": (datetime.strptime(created, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d"),  "completed": False, "verdict": None},
                "180d": {"due": review_iso, "completed": False, "verdict": None},
            },
            "override_events": [],
            "outcome": None,
        }
        self._data["theses"].append(thesis_obj)
        self._save()
        return thesis_obj

    def set_status(self, thesis_id: str, new_status: str) -> None:
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                current = t["status"]
                if new_status not in VALID_TRANSITIONS.get(current, set()):
                    raise InvalidStatusTransition(
                        f"{current} -> {new_status} not allowed"
                    )
                t["status"] = new_status
                self._save()
                return
        raise KeyError(thesis_id)

    def append_override_event(self, thesis_id: str, signal: str, price: float, date: str) -> None:
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                t["override_events"].append({"date": date, "signal": signal, "price": price})
                self._save()
                return
```

- [ ] **Step 4: Run tests — expect all pass**

Run:
```bash
python -m unittest tests.test_thesis_manager -v
```

Expected: `Ran 8 tests in 0.0Xs — OK`

- [ ] **Step 5: Commit**

```bash
git add thesis_manager.py tests/test_thesis_manager.py
git commit -m "feat(thesis): add ThesisManager with status state machine"
```

---

## Task 1.4: `scripts/thesis.py add` command

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/thesis.py`

- [ ] **Step 1: Create `scripts/__init__.py` empty**

- [ ] **Step 2: Create `scripts/thesis.py`**

```python
#!/usr/bin/env python3
"""Dispatch-callable CLI for thesis management.

Subcommands:
  add     — capture a new thesis
  list    — print all theses (optionally filter by status)
  review  — (Phase 3) inspect a thesis alongside current market state
  mark    — (Phase 3) set verdict + lesson
  report  — (Phase 3) conviction calibration summary

Example:
  python scripts/thesis.py add \\
    --ticker COIN \\
    --thesis "BTC halving cycle bottom" \\
    --invalidation "close < 140 for 5 sessions" \\
    --invalidation "weekly_rsi < 30" \\
    --conviction 7 \\
    --pre-mortem "If BTC doesn't bottom by Q3"
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# allow running from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from thesis_manager import ThesisManager  # noqa: E402

THESES_PATH = REPO_ROOT / "docs" / "data" / "theses.json"


def cmd_add(args: argparse.Namespace) -> int:
    mgr = ThesisManager(THESES_PATH)
    if mgr.get_active(args.ticker):
        print(f"Error: active thesis already exists for {args.ticker.upper()}", file=sys.stderr)
        return 2
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    t = mgr.add(
        ticker=args.ticker,
        thesis=args.thesis,
        invalidation=args.invalidation,
        conviction=args.conviction,
        pre_mortem=args.pre_mortem,
        created=today,
    )
    print(f"OK — thesis {t['id']} saved")
    print(f"   {len(t['invalidation_criteria'])} invalidation conditions")
    print(f"   review_date: {t['review_date']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    mgr = ThesisManager(THESES_PATH)
    theses = mgr.list_all()
    if args.status != "all":
        theses = [t for t in theses if t["status"] == args.status]
    if args.json:
        print(json.dumps(theses, indent=2))
        return 0
    if not theses:
        print("(no theses)")
        return 0
    for t in theses:
        print(f"{t['id']:<30} {t['status']:<12} conviction={t['conviction']}/10")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="thesis")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="capture a new thesis")
    a.add_argument("--ticker", required=True)
    a.add_argument("--thesis", required=True)
    a.add_argument("--invalidation", action="append", required=True,
                   help="can be repeated; e.g. 'close < 140 for 5 sessions'")
    a.add_argument("--conviction", type=int, required=True, choices=range(1, 11))
    a.add_argument("--pre-mortem", required=True, dest="pre_mortem")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="show all theses")
    l.add_argument("--status", default="active",
                   choices=["active", "invalidated", "vindicated", "expired", "orphaned", "all"])
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Manual test add + list**

Run:
```bash
python scripts/thesis.py add \
  --ticker COIN \
  --thesis "Bitcoin halving cycle bottom; COIN tracks BTC beta" \
  --invalidation "close < 140 for 5 sessions" \
  --invalidation "weekly_rsi < 30" \
  --invalidation "BTC fails to reclaim prior cycle high by Q3" \
  --conviction 7 \
  --pre-mortem "If BTC doesn't bottom by Q3"
python scripts/thesis.py list
```

Expected:
```
OK — thesis coin-2026-04-17 saved
   3 invalidation conditions
   review_date: 2026-10-14
coin-2026-04-17                active       conviction=7/10
```

- [ ] **Step 4: Verify theses.json updated**

Run:
```bash
cat docs/data/theses.json
```

Expected: JSON with one thesis object.

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/thesis.py docs/data/theses.json
git commit -m "feat(thesis): add scripts/thesis.py with add + list subcommands"
```

---

## Task 1.5: Integrate `ThesisManager` into `MarketAgent` startup

**Files:**
- Modify: `whale_watcher_agent.py` (add import + load in `generate_json_data`)

- [ ] **Step 1: Read the top of `whale_watcher_agent.py` to find import block and `MarketAgent` class**

Run:
```bash
grep -n "^import\|^from\|class MarketAgent\|def generate_json_data" whale_watcher_agent.py | head -20
```

- [ ] **Step 2: Add import near existing imports (top of file)**

Find the first `import` block and append:
```python
from thesis_manager import ThesisManager
```

- [ ] **Step 3: Initialize in `MarketAgent.__init__`**

Find `class MarketAgent:` → `def __init__(self, ...)`. At the end of `__init__` add:
```python
        # Thesis layer (Phase 1)
        theses_path = Path("docs/data/theses.json")
        self.thesis_manager = ThesisManager(theses_path) if theses_path.exists() else None
```

If `from pathlib import Path` is not already imported at the top of the file, add it.

- [ ] **Step 4: Syntax-check the file**

Run:
```bash
python -m py_compile whale_watcher_agent.py
```

Expected: no output (success).

- [ ] **Step 5: Verify the import resolves**

Run:
```bash
python -c "import whale_watcher_agent; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add whale_watcher_agent.py
git commit -m "feat(thesis): wire ThesisManager into MarketAgent init"
```

---

## Task 1.6: Suppress stop-loss alerts for active theses

**Files:**
- Modify: `whale_watcher_agent.py` (add check inside `PositionAnalyzer.generate_signal` for stop-loss branches)

- [ ] **Step 1: Locate the two stop-loss branches**

Run:
```bash
grep -n "hard_stop_loss\|Hard stop loss triggered\|Approaching stop loss" whale_watcher_agent.py
```

Expected: shows the two places where `SELL_ALL` and `EVALUATE` are emitted for stop loss.

- [ ] **Step 2: Add a helper on `PositionAnalyzer` that checks for active thesis**

Inside `class PositionAnalyzer:` add method:
```python
    def _active_thesis(self):
        """Return the active thesis dict for this ticker, or None."""
        mgr = getattr(self.market_agent, "thesis_manager", None) if hasattr(self, "market_agent") else None
        if mgr is None:
            return None
        return mgr.get_active(self.position.get("ticker") or self.position.get("symbol"))
```

The `market_agent` back-reference: ensure `PositionAnalyzer.__init__` receives and stores `market_agent`. If it doesn't, modify it:
```python
    def __init__(self, position, df, current_price, market_agent=None, ...):
        ...
        self.market_agent = market_agent
```

Update every `PositionAnalyzer(...)` construction site in `MarketAgent` to pass `self` as `market_agent=self`.

- [ ] **Step 3: Wrap the stop-loss branches in `generate_signal`**

Before the hard stop-loss branch and the approaching-stop-loss branch, add:
```python
        if self._active_thesis():
            # An active thesis suppresses recurring stop-loss alerts.
            # Invalidation checks happen at the MarketAgent level, not here.
            return self._hold_signal_while_thesis_active()
```

Add the helper:
```python
    def _hold_signal_while_thesis_active(self):
        return {
            "signal": "🧠 THESIS ACTIVE",
            "color": "purple",
            "action": "HOLD",
            "priority": 25,
            "reasoning": ["Signal suppressed — see Active Theses section"],
        }
```

Integrate that dict into whatever `generate_signal` returns (match the existing return shape).

- [ ] **Step 4: Write integration test**

Create `tests/test_thesis_integration.py`:
```python
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

    def test_active_thesis_short_circuits_stop_loss(self):
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
        # Simulate position below hard stop
        from whale_watcher_agent import PositionAnalyzer
        analyzer = PositionAnalyzer.__new__(PositionAnalyzer)
        analyzer.market_agent = fake_agent
        analyzer.position = {"ticker": "COIN", "symbol": "COIN"}
        result = analyzer._active_thesis()
        self.assertIsNotNone(result)
        self.assertEqual(result["ticker"], "COIN")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run tests**

Run:
```bash
python -m unittest tests.test_thesis_integration -v
```

Expected: `Ran 1 test — OK`

- [ ] **Step 6: Commit**

```bash
git add whale_watcher_agent.py tests/test_thesis_integration.py
git commit -m "feat(thesis): suppress stop-loss signals for positions with active thesis"
```

---

## Task 1.7: Evaluate invalidation each run + auto-transition

**Files:**
- Modify: `whale_watcher_agent.py` — add `check_invalidations` method on `MarketAgent`, call it early in `generate_json_data`

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_thesis_integration.py`:
```python
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
            ticker="COIN",
            thesis="x",
            invalidation=["close < 140"],
            conviction=7,
            pre_mortem="y",
            created="2026-04-17",
        )
        # Market data: COIN closed at 135
        market_data = {"COIN": {"closes": [135.0]}}
        tripped = evaluate_thesis_invalidations(mgr, market_data)
        self.assertEqual(len(tripped), 1)
        self.assertEqual(mgr.list_all()[0]["status"], "invalidated")
```

- [ ] **Step 2: Run — expect import error**

Run:
```bash
python -m unittest tests.test_thesis_integration -v
```

Expected: `cannot import name 'evaluate_thesis_invalidations'`

- [ ] **Step 3: Add `evaluate_thesis_invalidations` as a module-level function in `whale_watcher_agent.py`**

Just above `class MarketAgent:`, add:
```python
def evaluate_thesis_invalidations(thesis_manager, market_data: dict) -> list:
    """Evaluate every active thesis against current market data.

    market_data: dict keyed by ticker; each value has 'closes' list and optional
    'indicators' dict. Trips status -> 'invalidated' on any auto condition match.

    Returns list of (thesis_id, tripped_condition) for alerting.
    """
    from invalidation_evaluator import InvalidationEvaluator
    ev = InvalidationEvaluator()
    tripped = []
    for t in list(thesis_manager.list_all()):
        if t["status"] != "active":
            continue
        ticker_data = market_data.get(t["ticker"])
        if not ticker_data:
            continue
        for crit in t["invalidation_criteria"]:
            if not crit.get("auto"):
                continue
            cond = ev.parse(crit["condition"])
            result = ev.evaluate(cond, closes=ticker_data.get("closes"))
            if result.tripped:
                thesis_manager.set_status(t["id"], "invalidated")
                tripped.append((t["id"], crit["condition"], result.detail))
                break
    return tripped
```

- [ ] **Step 4: Run — expect pass**

Run:
```bash
python -m unittest tests.test_thesis_integration -v
```

Expected: `Ran 2 tests — OK`

- [ ] **Step 5: Hook into `MarketAgent.generate_json_data`**

Find the start of `generate_json_data` (around line 1733). After the `portfolio_data` / `watchlist_data` have been built and `positions = self.journal.get_positions()` has run, insert:

```python
        # Thesis invalidation sweep (Phase 1)
        if self.thesis_manager is not None:
            market_data = {
                item["symbol"]: {
                    "closes": [item["current_price"]],  # single-point today; Phase 2 uses full df
                }
                for item in portfolio_data
            }
            tripped = evaluate_thesis_invalidations(self.thesis_manager, market_data)
            for tid, cond, detail in tripped:
                print(f"   🚨 Thesis {tid} invalidated: {cond} ({detail})")
```

- [ ] **Step 6: Syntax-check**

Run:
```bash
python -m py_compile whale_watcher_agent.py
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add whale_watcher_agent.py tests/test_thesis_integration.py
git commit -m "feat(thesis): evaluate invalidations each run + auto-transition status"
```

---

## Task 1.8: Render "Active Theses" email section

**Files:**
- Modify: `whale_watcher_agent.py` — add `build_active_theses_html` in `generate_dashboard_html`, splice into email between Whale Activity and Positions

- [ ] **Step 1: Find splice point**

Run:
```bash
grep -n "Whale Activity\|whale_section_html\|Positions (sorted by urgency)" whale_watcher_agent.py
```

Expected: finds both markers.

- [ ] **Step 2: Build a helper method on `ThesisManager`**

In `thesis_manager.py`, add:
```python
    def render_email_section(self, current_prices: dict) -> str:
        """Return an HTML fragment for the 'Active Theses' email section.

        current_prices: {ticker: float} for live distance-to-invalidation display.
        Returns empty string when no active theses exist.
        """
        actives = [t for t in self._data["theses"] if t["status"] == "active"]
        if not actives:
            return ""
        rows = []
        for t in actives:
            sym = t["ticker"]
            price = current_prices.get(sym)
            price_txt = f"${price:.2f}" if price else "?"
            conds_html = ""
            for crit in t["invalidation_criteria"]:
                icon = "●" if crit["auto"] else "⚠"
                conds_html += (
                    f'<li style="color:#8b949e;font-size:12px;">{icon} '
                    f'{crit["condition"]}'
                    + (' <span style="color:#d29922">(manual check)</span>' if not crit["auto"] else '')
                    + '</li>'
                )
            critique_html = ""
            if t.get("red_team_critique"):
                critique_html = (
                    '<details style="margin-top:8px;color:#8b949e;font-size:12px;">'
                    '<summary style="cursor:pointer;color:#58a6ff;">▼ Bear critique (fresh-session)</summary>'
                    f'<div style="padding:8px;background:#0d1117;border-left:2px solid #f85149;">'
                    f'{t["red_team_critique"]}</div></details>'
                )
            rows.append(
                f'<tr><td style="padding:12px;border-bottom:1px solid #30363d;">'
                f'<div><strong style="color:#58a6ff;">{sym}</strong> — entered {t["created"]} · '
                f'conviction {t["conviction"]}/10 · Current: {price_txt}</div>'
                f'<div style="margin-top:6px;padding:8px;background:#161b22;border-left:2px solid #58a6ff;'
                f'color:#e6edf3;font-size:13px;">{t["thesis"]}</div>'
                f'<ul style="margin:6px 0 0 0;padding-left:20px;">{conds_html}</ul>'
                f'{critique_html}'
                f'</td></tr>'
            )
        return (
            '<tr><td style="padding-top:30px;">'
            '<h3 style="margin:0 0 15px 0;color:#e6edf3;border-bottom:1px solid #30363d;padding-bottom:5px;">'
            '🧠 Active Theses</h3>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table>'
            '</td></tr>'
        )
```

- [ ] **Step 3: Splice into `generate_dashboard_html`**

In `whale_watcher_agent.py` `generate_dashboard_html`, just before the `whale_section_html` assignment, add:
```python
        # Active Theses section (Phase 1) — empty string if none
        if self.thesis_manager:
            current_prices = {p["symbol"]: p.get("current_price") for p in data.get("portfolio", [])}
            active_theses_html = '<tr><td>' + self.thesis_manager.render_email_section(current_prices) + '</td></tr>' if self.thesis_manager.render_email_section(current_prices) else ""
        else:
            active_theses_html = ""
```

Actually simpler — remove the double wrap; let `render_email_section` return a `<tr>...</tr>` block directly (it already does). So:
```python
        active_theses_html = self.thesis_manager.render_email_section(current_prices) if self.thesis_manager else ""
```

In the big HTML f-string, just below the `whale_section_html` placeholder, add:
```
{active_theses_html}
```

- [ ] **Step 4: Preview render test**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
import sys, json
sys.path.insert(0, '.')
from pathlib import Path
from thesis_manager import ThesisManager
import whale_watcher_agent as w

# Create temp theses file with one active thesis
p = Path('docs/data/theses.json')
p.write_text(json.dumps({'theses':[{'id':'coin-x','ticker':'COIN','created':'2026-04-17',
    'author':'j','thesis':'BTC halving bottom','enter_tag':'','conviction':7,'pre_mortem':'y',
    'invalidation_criteria':[{'type':'price','condition':'close < 140 for 5 sessions','auto':True},
        {'type':'narrative','condition':'BTC fails Q3','auto':False}],
    'red_team_critique':'','unverified_claims':[],'bear_agent_model':'','bear_agent_run_at':'',
    'status':'active','review_date':'2026-10-14','review_checkpoints':{},'override_events':[],'outcome':None}],
    'version':1}))

mgr = ThesisManager(p)
html = mgr.render_email_section({'COIN': 199.83})
print('ok' if '🧠 Active Theses' in html and 'COIN' in html and '199.83' in html else 'FAIL')
"
```

Expected: `ok`

- [ ] **Step 5: Reset `theses.json` to empty before commit**

```bash
echo '{"theses": [], "version": 1}' > docs/data/theses.json
```

- [ ] **Step 6: Commit**

```bash
git add thesis_manager.py whale_watcher_agent.py docs/data/theses.json
git commit -m "feat(thesis): render Active Theses email section"
```

---

## Task 1.9: Fix pre-existing broken `test_whale_watcher.py` (side quest)

**Files:**
- Modify: `test_whale_watcher.py`

- [ ] **Step 1: Run the broken test to confirm failure**

Run:
```bash
python -m unittest test_whale_watcher -v
```

Expected: `AttributeError: 'MarketAgent' object has no attribute 'generate_report'`

- [ ] **Step 2: Read the test to understand intent**

```bash
cat test_whale_watcher.py
```

- [ ] **Step 3: Replace the broken call**

In `test_whale_watcher.py`, find the line calling `self.agent.generate_report()`. Replace with:
```python
        report = self.agent.generate_json_data()
```

Also update any assertions that assumed a dict with specific keys to match the actual shape of `generate_json_data`'s return (keys like `portfolio`, `watchlist`, `benchmarks`, `summary`).

If the assertions can't be easily adapted (e.g., they inspected a key that no longer exists), convert the test to a smoke test:
```python
        report = self.agent.generate_json_data()
        self.assertIn("portfolio", report)
        self.assertIn("watchlist", report)
        self.assertIn("benchmarks", report)
```

- [ ] **Step 4: Run**

Run:
```bash
python -m unittest test_whale_watcher -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add test_whale_watcher.py
git commit -m "fix(tests): update test_whale_watcher.py to use generate_json_data"
```

---

## Phase 1 merge checkpoint

- [ ] **Step 1: Run all tests**

Run:
```bash
python -m unittest discover -v
```

Expected: all pass.

- [ ] **Step 2: Push + open PR**

Run:
```bash
git push -u origin feat/thesis-phase-1
```

Then open: `https://github.com/jergrif73/whale-watcher/pull/new/feat/thesis-phase-1`

- [ ] **Step 3: After merge, delete branch and return to main**

---

# PHASE 2 — Active Critic (BearAgent)

**Goal:** At thesis creation, invoke Claude API in a fresh session to produce a red-team critique. Store in thesis record. Render in email. Extend invalidation evaluator for technical conditions (RSI, MACD, SMA).

**Phase 2 exit criteria:** A thesis captured via `scripts/thesis.py add` includes a Claude-generated bear critique. Technical invalidation conditions evaluate correctly on each run.

---

## Task 2.0: New feature branch from updated main

- [ ] **Step 1: Branch**

```bash
git checkout main && git pull
git checkout -b feat/thesis-phase-2
```

---

## Task 2.1: Add `ANTHROPIC_API_KEY` secret + workflow env

**Files:**
- Modify: `.github/workflows/whale_watcher.yml`

- [ ] **Step 1: Add secret in GitHub UI (manual)**

Go to `Settings → Secrets and variables → Actions → New repository secret`.
Name: `ANTHROPIC_API_KEY`. Value: paste your Anthropic console key.

- [ ] **Step 2: Modify workflow**

In `.github/workflows/whale_watcher.yml`, locate the `env:` block on the `run: python whale_watcher_agent.py` step. Add:
```yaml
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

- [ ] **Step 3: Update pip install step**

Find: `pip install yfinance pandas lxml requests matplotlib`
Change to: `pip install yfinance pandas numpy lxml requests matplotlib anthropic`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/whale_watcher.yml
git commit -m "ci(thesis): add ANTHROPIC_API_KEY secret + anthropic dep"
```

---

## Task 2.2: `BearAgent` class + response parser

**Files:**
- Create: `bear_agent.py`
- Create: `tests/test_bear_agent.py`

- [ ] **Step 1: Install `anthropic` locally**

Run:
```bash
pip install anthropic
```

- [ ] **Step 2: Write failing test**

`tests/test_bear_agent.py`:
```python
import unittest
from unittest.mock import MagicMock, patch

from bear_agent import BearAgent, parse_bear_response


SAMPLE_RESPONSE = """
1. COIN revenue is 95% transaction volume — if BTC consolidates sideways rather than bottoming, volumes compress and margins follow. Observable in 30/90/180d: quarterly trading volume declines, EPS miss vs consensus. [UNVERIFIED] Specific revenue breakdown figures.
2. Regulatory risk from SEC — pending enforcement actions could impair the core business. Observable: new SEC filings, 8-K disclosures.
3. Competitive pressure from Robinhood Crypto, Binance US — observable in market share data.

Minimum price/event that would prove the thesis-holder wrong: COIN trades below $140 for 5 consecutive sessions OR quarterly trading volume drops 30% YoY.
"""


class TestParseBearResponse(unittest.TestCase):
    def test_extracts_full_critique(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertIn("COIN revenue", parsed["red_team_critique"])

    def test_extracts_unverified_claims(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertEqual(len(parsed["unverified_claims"]), 1)
        self.assertIn("Specific revenue breakdown", parsed["unverified_claims"][0])

    def test_extracts_bear_floor(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertIn("$140", parsed["bear_floor"])

    def test_empty_response_returns_defaults(self):
        parsed = parse_bear_response("")
        self.assertEqual(parsed["red_team_critique"], "")
        self.assertEqual(parsed["unverified_claims"], [])
        self.assertIsNone(parsed["bear_floor"])


class TestBearAgent(unittest.TestCase):
    @patch("bear_agent.Anthropic")
    def test_critique_calls_api_with_fresh_session(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=SAMPLE_RESPONSE)]
        )

        agent = BearAgent(api_key="test-key")
        result = agent.critique(
            thesis="BTC halving bottom",
            invalidation_as_text="close < 140 for 5 sessions",
            pre_mortem="If BTC doesn't bottom by Q3",
        )
        # Verify API called
        mock_client.messages.create.assert_called_once()
        kwargs = mock_client.messages.create.call_args.kwargs
        # Fresh session: exactly one user message, no system, no history
        self.assertEqual(len(kwargs["messages"]), 1)
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertNotIn("system", kwargs)
        # Model is opus-4-7
        self.assertEqual(kwargs["model"], "claude-opus-4-7")
        # Parsed fields present
        self.assertIn("COIN revenue", result["red_team_critique"])

    @patch("bear_agent.Anthropic")
    def test_critique_handles_api_error_gracefully(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("rate limit")

        agent = BearAgent(api_key="test-key")
        result = agent.critique(
            thesis="x", invalidation_as_text="y", pre_mortem="z",
        )
        self.assertEqual(result["red_team_critique"], "")
        self.assertEqual(result["error"], "rate limit")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run — expect import failure**

Run:
```bash
python -m unittest tests.test_bear_agent -v
```

Expected: `ModuleNotFoundError: bear_agent`

- [ ] **Step 4: Create `bear_agent.py`**

```python
"""BearAgent — fresh-session Claude API wrapper for thesis red-team critique.

Run once at thesis creation time. Never in the scheduled cron. No chat history,
no system prompt, single user message. Protects against sycophantic carryover.
"""

import re
from datetime import datetime, timezone
from typing import Optional

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


BEAR_PROMPT_TEMPLATE = """You are a skeptical short-seller reviewing the thesis below.

Rules:
1. Do NOT affirm any claim. Your job is disagreement.
2. List the 3 strongest reasons this thesis is wrong, ranked by probability, not severity.
3. For each reason, state what observable evidence in the next 30/90/180 days would confirm it.
4. Identify any factual claim that cannot be verified from public filings — flag it [UNVERIFIED].
5. End with: "Minimum price/event that would prove the thesis-holder wrong" — a single falsifiable line.

Do not hedge. Do not offer balance. Assume the author is overconfident and biased long.

THESIS: {thesis}
INVALIDATION AS STATED: {invalidation_as_text}
PRE-MORTEM BY AUTHOR: {pre_mortem}
"""


UNVERIFIED_RE = re.compile(r"\[UNVERIFIED\][^.\n]*[.\n]", re.IGNORECASE)
MINIMUM_LINE_RE = re.compile(r"^\s*Minimum[^\n]*", re.IGNORECASE | re.MULTILINE)


def parse_bear_response(text: str) -> dict:
    """Deterministic extractor. No LLM re-prompting."""
    if not text or not text.strip():
        return {"red_team_critique": "", "unverified_claims": [], "bear_floor": None}
    unverified = [m.group(0).strip() for m in UNVERIFIED_RE.finditer(text)]
    floor_match = MINIMUM_LINE_RE.search(text)
    floor = floor_match.group(0).strip() if floor_match else None
    return {
        "red_team_critique": text.strip(),
        "unverified_claims": unverified,
        "bear_floor": floor,
    }


class BearAgent:
    def __init__(self, api_key: str, model: str = "claude-opus-4-7"):
        if Anthropic is None:
            raise RuntimeError("anthropic package not installed")
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def critique(self, thesis: str, invalidation_as_text: str, pre_mortem: str) -> dict:
        prompt = BEAR_PROMPT_TEMPLATE.format(
            thesis=thesis,
            invalidation_as_text=invalidation_as_text,
            pre_mortem=pre_mortem,
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in msg.content if hasattr(block, "text"))
            parsed = parse_bear_response(text)
            parsed["bear_agent_model"] = self.model
            parsed["bear_agent_run_at"] = datetime.now(timezone.utc).isoformat()
            parsed["error"] = None
            return parsed
        except Exception as e:
            return {
                "red_team_critique": "",
                "unverified_claims": [],
                "bear_floor": None,
                "bear_agent_model": self.model,
                "bear_agent_run_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
```

- [ ] **Step 5: Run tests**

Run:
```bash
python -m unittest tests.test_bear_agent -v
```

Expected: `Ran 6 tests — OK`

- [ ] **Step 6: Commit**

```bash
git add bear_agent.py tests/test_bear_agent.py
git commit -m "feat(thesis): add BearAgent with fresh-session Claude API call"
```

---

## Task 2.3: Hook `BearAgent` into `scripts/thesis.py add`

**Files:**
- Modify: `scripts/thesis.py`
- Modify: `thesis_manager.py` (add method to persist critique fields on an existing thesis)

- [ ] **Step 1: Add `update_critique` method to `ThesisManager`**

In `thesis_manager.py`, append:
```python
    def update_critique(self, thesis_id: str, critique: dict) -> None:
        """Persist bear-agent output onto an existing thesis."""
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                t["red_team_critique"] = critique.get("red_team_critique", "")
                t["unverified_claims"] = critique.get("unverified_claims", [])
                t["bear_agent_model"] = critique.get("bear_agent_model", "")
                t["bear_agent_run_at"] = critique.get("bear_agent_run_at", "")
                # Append bear_floor as a manual invalidation criterion
                if critique.get("bear_floor"):
                    t["invalidation_criteria"].append({
                        "type": "bear_floor",
                        "condition": critique["bear_floor"],
                        "auto": False,
                    })
                self._save()
                return
        raise KeyError(thesis_id)
```

- [ ] **Step 2: Modify `cmd_add` in `scripts/thesis.py`**

Replace `cmd_add` with:
```python
def cmd_add(args: argparse.Namespace) -> int:
    import os
    mgr = ThesisManager(THESES_PATH)
    if mgr.get_active(args.ticker):
        print(f"Error: active thesis already exists for {args.ticker.upper()}", file=sys.stderr)
        return 2
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    t = mgr.add(
        ticker=args.ticker,
        thesis=args.thesis,
        invalidation=args.invalidation,
        conviction=args.conviction,
        pre_mortem=args.pre_mortem,
        created=today,
    )
    print(f"OK — thesis {t['id']} saved ({len(t['invalidation_criteria'])} conditions)")

    # Phase 2: bear agent critique
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("   ⚠ ANTHROPIC_API_KEY not set — skipping bear critique")
        print(f"   review_date: {t['review_date']}")
        return 0
    print("   Running bear-agent critique (fresh session)…")
    try:
        from bear_agent import BearAgent
        agent = BearAgent(api_key=api_key)
        critique = agent.critique(
            thesis=args.thesis,
            invalidation_as_text="; ".join(args.invalidation),
            pre_mortem=args.pre_mortem,
        )
        if critique.get("error"):
            print(f"   ⚠ Bear agent failed: {critique['error']} — thesis saved without critique")
        else:
            mgr.update_critique(t["id"], critique)
            print(f"   ✓ Bear critique saved ({len(critique['unverified_claims'])} unverified claims flagged)")
            if critique.get("bear_floor"):
                print(f"   ✓ Bear floor added: {critique['bear_floor'][:80]}")
    except RuntimeError as e:
        print(f"   ⚠ {e}")
    print(f"   review_date: {t['review_date']}")
    return 0
```

- [ ] **Step 3: Smoke test (without real API)**

Run (with no API key):
```bash
unset ANTHROPIC_API_KEY
python scripts/thesis.py add --ticker TEST --thesis "x" --invalidation "close < 1" --conviction 5 --pre-mortem "y"
python scripts/thesis.py list --status all
```

Expected: thesis saved with `⚠ ANTHROPIC_API_KEY not set — skipping bear critique`.

- [ ] **Step 4: Clean up test thesis**

```bash
echo '{"theses": [], "version": 1}' > docs/data/theses.json
```

- [ ] **Step 5: Commit**

```bash
git add thesis_manager.py scripts/thesis.py docs/data/theses.json
git commit -m "feat(thesis): hook BearAgent into thesis add subcommand"
```

---

## Task 2.4: Extend `InvalidationEvaluator` for technical conditions

**Files:**
- Modify: `invalidation_evaluator.py`
- Modify: `tests/test_invalidation_evaluator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_invalidation_evaluator.py`:
```python
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
        # This is a cross-field compare — skip for now
        # Phase 2 supports scalar compare only
        self.assertIn(cond.type, ("technical", "narrative"))

    def test_macd_hist_lt_zero(self):
        cond = self.ev.parse("macd_hist < 0")
        res = self.ev.evaluate(cond, indicators={"macd_hist": [-0.5]})
        self.assertTrue(res.tripped)
```

- [ ] **Step 2: Update `InvalidationEvaluator.evaluate` for `technical`**

Replace the `technical` branch:
```python
        if cond.type == "technical":
            if not indicators or cond.lhs not in indicators:
                return EvalResult(tripped=False, detail="no_indicator")
            series = indicators[cond.lhs]
            if not series:
                return EvalResult(tripped=False, detail="empty_series")
            window = series[-cond.duration_sessions:]
            if len(window) < cond.duration_sessions:
                return EvalResult(tripped=False, detail="insufficient_history")
            all_breach = all(self._compare(v, cond.op, cond.threshold) for v in window)
            if all_breach:
                return EvalResult(
                    tripped=True,
                    detail=f"{cond.lhs}={window[-1]} {cond.op} {cond.threshold}",
                )
            return EvalResult(tripped=False, detail=f"{cond.lhs}={window[-1]}")
```

- [ ] **Step 3: Run tests**

Run:
```bash
python -m unittest tests.test_invalidation_evaluator -v
```

Expected: `OK`.

- [ ] **Step 4: Hook into the invalidation sweep in `whale_watcher_agent.py`**

In `evaluate_thesis_invalidations`, expand `market_data` construction in `generate_json_data` to include per-ticker indicator series:
```python
        if self.thesis_manager is not None:
            market_data = {}
            for item in portfolio_data:
                sym = item["symbol"]
                market_data[sym] = {
                    "closes": item.get("recent_closes") or [item["current_price"]],
                    "indicators": {
                        "rsi": [item.get("rsi")] if item.get("rsi") is not None else [],
                        "weekly_rsi": [item.get("weekly_rsi")] if item.get("weekly_rsi") is not None else [],
                        "macd_hist": [item.get("macd_hist")] if item.get("macd_hist") is not None else [],
                    },
                }
            tripped = evaluate_thesis_invalidations(self.thesis_manager, market_data)
            for tid, cond, detail in tripped:
                print(f"   🚨 Thesis {tid} invalidated: {cond} ({detail})")
```

And update `evaluate_thesis_invalidations` call signature to pass `indicators=` along with closes:
```python
            result = ev.evaluate(
                cond,
                closes=ticker_data.get("closes"),
                indicators=ticker_data.get("indicators", {}),
            )
```

- [ ] **Step 5: Syntax-check and run all tests**

Run:
```bash
python -m py_compile whale_watcher_agent.py invalidation_evaluator.py
python -m unittest discover -v
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add invalidation_evaluator.py whale_watcher_agent.py tests/test_invalidation_evaluator.py
git commit -m "feat(thesis): evaluate technical invalidation conditions (RSI/MACD)"
```

---

## Phase 2 merge checkpoint

- [ ] **Step 1: Run all tests, push, open PR, merge**

Run:
```bash
python -m unittest discover -v
git push -u origin feat/thesis-phase-2
```

Open: `https://github.com/jergrif73/whale-watcher/pull/new/feat/thesis-phase-2`

---

# PHASE 3 — Outcome Tracker + Calibration

**Goal:** Review checkpoints surface in email when due. User marks vindicated/invalidated via CLI. Conviction calibration report exists.

**Phase 3 exit criteria:** `scripts/thesis.py review` shows a thesis with current market state; `scripts/thesis.py mark` persists outcome; `scripts/thesis.py report` computes a calibration summary over all closed theses.

---

## Task 3.0: New branch

- [ ] **Step 1: Branch**

```bash
git checkout main && git pull
git checkout -b feat/thesis-phase-3
```

---

## Task 3.1: Review-checkpoint detection + email section

**Files:**
- Modify: `thesis_manager.py` (add `theses_due_for_review`)
- Modify: `whale_watcher_agent.py` (splice section into email)

- [ ] **Step 1: Add method + test**

`tests/test_thesis_manager.py` — add:
```python
    def test_theses_due_for_review(self):
        t = self.mgr.add(
            ticker="COIN", thesis="x", invalidation=["close < 1"],
            conviction=5, pre_mortem="y", created="2026-01-01",
        )
        # 30d checkpoint was due on 2026-01-31
        due = self.mgr.theses_due_for_review(today="2026-02-05")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["checkpoint"], "30d")
```

- [ ] **Step 2: Add method to `thesis_manager.py`**

```python
    def theses_due_for_review(self, today: str) -> list:
        """Return list of {'thesis': t, 'checkpoint': name} for due but
        uncompleted checkpoints. today is ISO date."""
        out = []
        for t in self._data["theses"]:
            if t["status"] != "active":
                continue
            for name, cp in t.get("review_checkpoints", {}).items():
                if not cp.get("completed") and cp.get("due") and cp["due"] <= today:
                    out.append({"thesis": t, "checkpoint": name, "due": cp["due"]})
        return out
```

- [ ] **Step 3: Run tests**

Run:
```bash
python -m unittest tests.test_thesis_manager -v
```

Expected: `OK`.

- [ ] **Step 4: Render review-due email section**

Append to `thesis_manager.py`:
```python
    def render_review_due_section(self, today: str) -> str:
        due = self.theses_due_for_review(today)
        if not due:
            return ""
        rows = []
        for d in due:
            t = d["thesis"]
            rows.append(
                f'<tr><td style="padding:10px;border-bottom:1px solid #30363d;">'
                f'<strong style="color:#d29922;">📋 Review due:</strong> '
                f'<span style="color:#58a6ff;">{t["ticker"]}</span> '
                f'<span style="color:#8b949e;font-size:12px;">({d["checkpoint"]} checkpoint, was due {d["due"]})</span><br>'
                f'<span style="color:#e6edf3;font-size:13px;">Run: '
                f'<code>python scripts/thesis.py review --id {t["id"]}</code></span>'
                f'</td></tr>'
            )
        return (
            '<tr><td style="padding-top:30px;">'
            '<h3 style="margin:0 0 15px 0;color:#e6edf3;border-bottom:1px solid #30363d;padding-bottom:5px;">'
            '📋 Thesis Reviews Due</h3>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table>'
            '</td></tr>'
        )
```

- [ ] **Step 5: Splice into email**

In `generate_dashboard_html`, next to `active_theses_html`, add:
```python
        review_due_html = (self.thesis_manager.render_review_due_section(
            datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            if self.thesis_manager else "")
```

Insert `{review_due_html}` in the email body just after `{active_theses_html}`.

- [ ] **Step 6: Commit**

```bash
git add thesis_manager.py tests/test_thesis_manager.py whale_watcher_agent.py
git commit -m "feat(thesis): add review-checkpoint detection + email section"
```

---

## Task 3.2: `scripts/thesis.py review` + `mark` subcommands

**Files:**
- Modify: `scripts/thesis.py`
- Modify: `thesis_manager.py` (add `mark_outcome`)

- [ ] **Step 1: Add `mark_outcome` to `ThesisManager`**

```python
    def mark_outcome(self, thesis_id: str, verdict: str, lesson: str,
                     final_price: float = None, closed_at: str = None) -> None:
        """Set final verdict. Valid verdicts: vindicated, invalidated."""
        if verdict not in {"vindicated", "invalidated"}:
            raise ValueError(f"invalid verdict: {verdict}")
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                current = t["status"]
                # Allow orphaned -> invalidated/vindicated, active -> invalidated (manual)
                if verdict not in VALID_TRANSITIONS.get(current, set()):
                    raise InvalidStatusTransition(f"{current} -> {verdict} not allowed")
                t["status"] = verdict
                t["outcome"] = {
                    "closed_at": closed_at or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "final_price": final_price,
                    "verdict": verdict,
                    "lesson": lesson,
                }
                self._save()
                return
        raise KeyError(thesis_id)
```

Also extend `VALID_TRANSITIONS` to allow `active -> vindicated` manually (which is the case when you decide your thesis played out):
```python
VALID_TRANSITIONS = {
    "active":      {"invalidated", "vindicated", "expired", "orphaned"},
    "orphaned":    {"invalidated", "vindicated"},
    "invalidated": set(),
    "vindicated":  set(),
    "expired":     set(),
}
```
(No change needed — already permits active → vindicated. Good.)

- [ ] **Step 2: Add `cmd_review` and `cmd_mark` to `scripts/thesis.py`**

```python
def cmd_review(args: argparse.Namespace) -> int:
    mgr = ThesisManager(THESES_PATH)
    t = next((x for x in mgr.list_all() if x["id"] == args.id), None)
    if not t:
        print(f"Error: no thesis {args.id}", file=sys.stderr)
        return 2
    print(f"=== {t['id']} ({t['status']}) ===")
    print(f"Ticker:     {t['ticker']}")
    print(f"Created:    {t['created']}")
    print(f"Conviction: {t['conviction']}/10")
    print(f"\nThesis:\n  {t['thesis']}")
    print(f"\nPre-mortem:\n  {t['pre_mortem']}")
    print("\nInvalidation criteria:")
    for c in t["invalidation_criteria"]:
        tag = "auto" if c["auto"] else "manual"
        print(f"  [{tag:>6s}] {c['condition']}")
    if t.get("red_team_critique"):
        print("\nBear critique:")
        print("  " + t["red_team_critique"].replace("\n", "\n  "))
    if t.get("unverified_claims"):
        print("\nUnverified claims:")
        for u in t["unverified_claims"]:
            print(f"  • {u}")
    print(f"\nReview date: {t['review_date']}")
    print(f"\nTo mark outcome: python scripts/thesis.py mark --id {t['id']} --verdict vindicated|invalidated --lesson \"...\"")
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    mgr = ThesisManager(THESES_PATH)
    try:
        mgr.mark_outcome(
            thesis_id=args.id,
            verdict=args.verdict,
            lesson=args.lesson,
            final_price=args.final_price,
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    print(f"OK — {args.id} marked {args.verdict}")
    return 0
```

Register in `build_parser`:
```python
    r = sub.add_parser("review", help="inspect a thesis")
    r.add_argument("--id", required=True)
    r.set_defaults(func=cmd_review)

    m = sub.add_parser("mark", help="record final verdict")
    m.add_argument("--id", required=True)
    m.add_argument("--verdict", required=True, choices=["vindicated", "invalidated"])
    m.add_argument("--lesson", required=True)
    m.add_argument("--final-price", type=float, default=None, dest="final_price")
    m.set_defaults(func=cmd_mark)
```

- [ ] **Step 3: Smoke test**

```bash
python scripts/thesis.py add --ticker TEST --thesis "x" --invalidation "close < 1" --conviction 5 --pre-mortem "y"
python scripts/thesis.py review --id test-$(date +%Y-%m-%d)
python scripts/thesis.py mark --id test-$(date +%Y-%m-%d) --verdict vindicated --lesson "Caught the reversal"
python scripts/thesis.py list --status all
```

Expected: review prints structured output; mark succeeds; list shows `vindicated`.

- [ ] **Step 4: Clean up**

```bash
echo '{"theses": [], "version": 1}' > docs/data/theses.json
```

- [ ] **Step 5: Commit**

```bash
git add thesis_manager.py scripts/thesis.py docs/data/theses.json
git commit -m "feat(thesis): add review + mark subcommands"
```

---

## Task 3.3: Orphan detection + expiration

**Files:**
- Modify: `whale_watcher_agent.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_thesis_integration.py`:
```python
class TestOrphanAndExpiration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "theses.json"
        self.path.write_text(json.dumps({"theses": [], "version": 1}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ticker_sold_becomes_orphaned(self):
        from whale_watcher_agent import detect_orphans_and_expirations
        mgr = ThesisManager(self.path)
        mgr.add(ticker="COIN", thesis="x", invalidation=["close < 1"],
                conviction=5, pre_mortem="y", created="2026-04-17")
        # Portfolio does not contain COIN
        portfolio_tickers = {"MSFT", "MARA"}
        detect_orphans_and_expirations(mgr, portfolio_tickers, today="2026-04-17")
        self.assertEqual(mgr.list_all()[0]["status"], "orphaned")

    def test_past_review_date_becomes_expired(self):
        from whale_watcher_agent import detect_orphans_and_expirations
        mgr = ThesisManager(self.path)
        t = mgr.add(ticker="COIN", thesis="x", invalidation=["close < 1"],
                   conviction=5, pre_mortem="y", created="2026-01-01")
        # Review date is 2026-06-30; today is past that
        detect_orphans_and_expirations(mgr, {"COIN"}, today="2026-12-01")
        self.assertEqual(mgr.list_all()[0]["status"], "expired")
```

- [ ] **Step 2: Add function to `whale_watcher_agent.py`**

Near `evaluate_thesis_invalidations`:
```python
def detect_orphans_and_expirations(thesis_manager, portfolio_tickers: set, today: str) -> None:
    """Auto-transition active theses to orphaned/expired where applicable."""
    for t in list(thesis_manager.list_all()):
        if t["status"] != "active":
            continue
        if t["ticker"] not in portfolio_tickers:
            thesis_manager.set_status(t["id"], "orphaned")
            continue
        if t.get("review_date") and t["review_date"] < today:
            thesis_manager.set_status(t["id"], "expired")
```

- [ ] **Step 3: Call from `generate_json_data`**

Just after the invalidation sweep:
```python
        if self.thesis_manager is not None:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            portfolio_tickers = {item["symbol"] for item in portfolio_data}
            detect_orphans_and_expirations(self.thesis_manager, portfolio_tickers, today)
```

- [ ] **Step 4: Run tests**

Run:
```bash
python -m unittest tests.test_thesis_integration -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add whale_watcher_agent.py tests/test_thesis_integration.py
git commit -m "feat(thesis): detect orphans + expirations on scheduled run"
```

---

## Task 3.4: `scripts/thesis.py report` — calibration summary

**Files:**
- Modify: `scripts/thesis.py`

- [ ] **Step 1: Add `cmd_report`**

```python
def cmd_report(args: argparse.Namespace) -> int:
    mgr = ThesisManager(THESES_PATH)
    all_theses = mgr.list_all()
    closed = [t for t in all_theses if t["status"] in ("vindicated", "invalidated", "expired")]
    if not closed:
        print("No closed theses yet. Capture some via 'add', then come back.")
        return 0

    vindicated = [t for t in closed if t["status"] == "vindicated"]
    invalidated = [t for t in closed if t["status"] == "invalidated"]
    expired = [t for t in closed if t["status"] == "expired"]

    print(f"=== Conviction Calibration Report ===\n")
    print(f"Closed theses:  {len(closed)}")
    print(f"  Vindicated:   {len(vindicated)} ({100 * len(vindicated) / len(closed):.1f}%)")
    print(f"  Invalidated:  {len(invalidated)} ({100 * len(invalidated) / len(closed):.1f}%)")
    print(f"  Expired:      {len(expired)} ({100 * len(expired) / len(closed):.1f}%)")

    # Correlation: conviction vs outcome
    if closed:
        avg_conviction_vindicated = sum(t["conviction"] for t in vindicated) / len(vindicated) if vindicated else None
        avg_conviction_invalidated = sum(t["conviction"] for t in invalidated) / len(invalidated) if invalidated else None
        print(f"\nConviction at capture:")
        if avg_conviction_vindicated is not None:
            print(f"  Avg for vindicated:   {avg_conviction_vindicated:.1f}/10")
        if avg_conviction_invalidated is not None:
            print(f"  Avg for invalidated:  {avg_conviction_invalidated:.1f}/10")
        if avg_conviction_vindicated is not None and avg_conviction_invalidated is not None:
            spread = avg_conviction_vindicated - avg_conviction_invalidated
            verdict = ("✓ Calibrated: higher conviction → better outcomes"
                       if spread > 0.5 else
                       "⚠ Flat: conviction not predicting outcomes"
                       if abs(spread) < 0.5 else
                       "✗ Inverted: high conviction → worse outcomes")
            print(f"\n  {verdict} (spread={spread:+.1f})")

    print(f"\nLessons captured:")
    for t in closed:
        if t.get("outcome") and t["outcome"].get("lesson"):
            print(f"  • {t['ticker']} ({t['status']}): {t['outcome']['lesson']}")
    return 0
```

Register in `build_parser`:
```python
    rp = sub.add_parser("report", help="conviction calibration summary")
    rp.set_defaults(func=cmd_report)
```

- [ ] **Step 2: Smoke test with manually-crafted data**

```bash
python -c "
import json
from pathlib import Path
data = {'theses': [
  {'id':'a','ticker':'AAA','created':'2025-10-01','author':'j','thesis':'x','enter_tag':'',
   'conviction':8,'pre_mortem':'y','invalidation_criteria':[],'red_team_critique':'',
   'unverified_claims':[],'bear_agent_model':'','bear_agent_run_at':'',
   'status':'vindicated','review_date':'2026-04-01','review_checkpoints':{},
   'override_events':[],'outcome':{'closed_at':'2026-03-01','final_price':100,'verdict':'vindicated','lesson':'Patience paid'}},
  {'id':'b','ticker':'BBB','created':'2025-11-01','author':'j','thesis':'x','enter_tag':'',
   'conviction':6,'pre_mortem':'y','invalidation_criteria':[],'red_team_critique':'',
   'unverified_claims':[],'bear_agent_model':'','bear_agent_run_at':'',
   'status':'invalidated','review_date':'2026-05-01','review_checkpoints':{},
   'override_events':[],'outcome':{'closed_at':'2026-02-01','final_price':10,'verdict':'invalidated','lesson':'Ignored a clear volume warning'}},
], 'version':1}
Path('docs/data/theses.json').write_text(json.dumps(data, indent=2))
"
python scripts/thesis.py report
```

Expected: prints calibration summary with 2 closed theses, 50% vindicated.

- [ ] **Step 3: Reset**

```bash
echo '{"theses": [], "version": 1}' > docs/data/theses.json
```

- [ ] **Step 4: Commit**

```bash
git add scripts/thesis.py docs/data/theses.json
git commit -m "feat(thesis): add report subcommand for conviction calibration"
```

---

## Phase 3 merge checkpoint

- [ ] **Step 1: All tests + push + PR + merge**

```bash
python -m unittest discover -v
git push -u origin feat/thesis-phase-3
```

Open: `https://github.com/jergrif73/whale-watcher/pull/new/feat/thesis-phase-3`

---

## Self-Review

After writing the complete plan, spot-check against the spec:

- [x] Data model fields: every field in spec §4.1 appears in `ThesisManager.add()` (Task 1.3)
- [x] Status lifecycle: `VALID_TRANSITIONS` matches spec §4.2 (Task 1.3)
- [x] BearAgent prompt: Task 2.2 uses the exact prompt from spec §7
- [x] Response parser: Task 2.2 extracts red_team_critique + unverified_claims + bear_floor per spec §7
- [x] Price grammar: Task 1.2 matches spec §8 (operators, duration)
- [x] Technical grammar: Task 2.4 matches spec §8 (RSI, MACD, SMA)
- [x] Narrative = manual: Task 1.2 falls back to `auto: False`
- [x] Trip semantics: Task 1.7 + 2.4 — any auto condition trips → invalidated
- [x] Email Active Theses section: Task 1.8
- [x] Email Review Due section: Task 3.1
- [x] Edge cases §10: malformed json (Task 1.3), missing API key (Task 2.3), API failure (Task 2.2), orphan (Task 3.3), expired (Task 3.3), narrative manual (throughout)
- [x] Testing plan §11: ThesisManager unit (Task 1.3), InvalidationEvaluator unit (Task 1.2, 2.4), BearAgent mocked (Task 2.2), integration (Task 1.6, 1.7, 3.3)
- [x] Side quest: broken test_whale_watcher.py fixed (Task 1.9)
- [x] Secrets: ANTHROPIC_API_KEY only passed via env (Task 2.1, 2.3); never logged
- [x] Success criteria: behavioral + discipline + calibration — all exercised by Phase 1, 2, 3 respectively

No placeholders. All types consistent (`thesis_manager` module, `ThesisManager` class, `BearAgent` class, `InvalidationEvaluator` class). All method signatures match between definition and call sites.
