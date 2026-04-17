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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# allow running from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from thesis_manager import ThesisManager  # noqa: E402

THESES_PATH = REPO_ROOT / "docs" / "data" / "theses.json"


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
    print(f"OK - thesis {t['id']} saved ({len(t['invalidation_criteria'])} conditions)")

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
