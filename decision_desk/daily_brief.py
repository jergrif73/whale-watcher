"""Daily brief: weekdays about 30 minutes after the US close.

    python -m decision_desk.daily_brief --dry-run     # print prompt + token/cost estimate, no API call
    python -m decision_desk.daily_brief               # real run
    python -m decision_desk.daily_brief --scheduled   # cron mode: skips weekends, pre-close, and repeats

Gathers positions, lots, cost basis, day/week moves, allocation drift and
Alpha Vantage news, asks a Sonnet-class model for a structured per-holding
brief, writes briefs/YYYY-MM-DD.json and docs/today.html.
"""

import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta

from decision_desk import common as c
from decision_desk import prompts, render

MAX_TOKENS = int(os.environ.get("DESK_DAILY_MAX_TOKENS", "8000"))
EFFORT = "medium"


def previous_brief(today):
    if not c.BRIEFS_DIR.exists():
        return None
    older = sorted(p for p in c.BRIEFS_DIR.glob("*.json") if p.stem < today.isoformat())
    if not older:
        return None
    b = c.load_json(older[-1], {})
    return {"date": b.get("date"),
            "thesis_status": {h["ticker"]: h["thesis_status"] for h in (b.get("output") or {}).get("holdings", [])}}


def build_request(theses, decisions, today):
    snapshot = c.build_snapshot(theses)
    triggers = c.rule_triggers(snapshot, theses, decisions.get("decisions", []), today)
    tickers = [h["ticker"] for h in snapshot["holdings"]]
    news = c.fetch_news(theses, tickers)
    cutoff = (today - timedelta(days=30)).isoformat()
    recent = [d for d in decisions.get("decisions", []) if d.get("date", "") >= cutoff][-20:]
    payload = {
        "date": today.isoformat(),
        "snapshot": c.strip_private(snapshot),
        "rule_triggers": triggers,
        "news": news,
        "recent_decisions": recent,
        "previous_brief": previous_brief(today),
    }
    system = prompts.system_blocks(prompts.DAILY_RUBRIC, theses)
    user = ("Today's data for the brief, as JSON. Fill the schema for every holding in snapshot.holdings.\n\n"
            + json.dumps(payload, indent=1, default=str))
    return snapshot, triggers, news, system, [{"role": "user", "content": user}]


def make_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic(max_retries=3)


def should_skip_scheduled(today, brief_path):
    now = datetime.now(c.NY)
    if now.weekday() >= 5:
        return "weekend"
    if now.time() < time(16, 15):
        return f"before 16:15 New York ({now:%H:%M}); the later cron slot covers standard time"
    if brief_path.exists():
        return f"{brief_path.name} already exists"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scheduled", action="store_true")
    args = ap.parse_args(argv)

    today = c.today_ny()
    brief_path = c.BRIEFS_DIR / f"{today.isoformat()}.json"
    if args.scheduled and not args.dry_run:
        why = should_skip_scheduled(today, brief_path)
        if why:
            print(f"Skipping scheduled daily brief: {why}.")
            return 0

    theses = c.load_json(c.THESES_PATH, {"holdings": []})
    decisions = c.load_json(c.DECISIONS_PATH, {"version": 1, "decisions": []})
    if not args.dry_run and c.backfill_decision_prices(decisions, theses):
        c.write_json(c.DECISIONS_PATH, decisions)

    print(f"Decision Desk daily brief for {today} ({'DRY RUN' if args.dry_run else 'live'})")
    snapshot, triggers, news, system, messages = build_request(theses, decisions, today)
    if not snapshot["holdings"]:
        print("No open holdings in the trade journal; nothing to brief.")
        return 0

    client = make_client()
    in_tokens, how = c.count_input_tokens(client, c.DAILY_MODEL, system, messages)
    # Worst case: every input token billed as a cache write, every output token used.
    worst = c.estimate_cost(c.DAILY_MODEL, cache_write_tokens=in_tokens, output_tokens=MAX_TOKENS)
    mtd = c.month_to_date_spend()

    if args.dry_run:
        print("\n" + "=" * 30 + " SYSTEM (cached prefix) " + "=" * 30)
        for b in system:
            print(b["text"])
            print("-" * 84)
        print("=" * 30 + " USER " + "=" * 30)
        print(messages[0]["content"])
        print("=" * 84)
        print(f"Model {c.DAILY_MODEL}, effort {EFFORT}, max_tokens {MAX_TOKENS}")
        print(f"Input tokens: {in_tokens} ({how})")
        print(f"Typical cost (cache write on prefix, ~1.5k output): "
              f"${c.estimate_cost(c.DAILY_MODEL, cache_write_tokens=in_tokens, output_tokens=1500):.4f}")
        print(f"Worst case at max_tokens: ${worst:.4f}")
        print(f"Month to date: ${mtd:.2f} of ${c.MTD_CAP_USD:.0f} cap")
        print("DRY RUN: no Messages API call made, nothing written.")
        return 0

    if client is None:
        print("ANTHROPIC_API_KEY is not set. Use --dry-run, or set the secret.")
        return 1
    try:
        c.check_budget(worst, "daily brief")
    except c.BudgetExceeded as ex:
        print(str(ex))
        return 2

    brief = {"date": today.isoformat(), "generated_at_utc": c.now_utc().isoformat(timespec="seconds"),
             "model": c.DAILY_MODEL, "snapshot": c.strip_private(snapshot), "rule_triggers": triggers,
             "news": news, "output": None, "usage": None, "error": None}
    resp = client.beta.messages.create(
        model=c.DAILY_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": prompts.DAILY_SCHEMA}},
        # Server-side refusal fallback: if the model declines, the API reruns
        # the request on a fallback model inside the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    brief["model"] = resp.model
    brief["usage"] = c.log_cost("daily", today.isoformat(), resp.model, resp.usage)
    if resp.stop_reason == "refusal":
        cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
        brief["error"] = f"Model declined the request (category {cat}). No brief today."
    elif resp.stop_reason == "max_tokens":
        brief["error"] = f"Output hit max_tokens ({MAX_TOKENS}) before the JSON finished. Raise DESK_DAILY_MAX_TOKENS."
    else:
        text = next(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
        # Code-computed numbers win over anything the model restated.
        by_t = {h["ticker"]: h for h in snapshot["holdings"]}
        for h in out["holdings"]:
            alloc = (by_t.get(h["ticker"]) or {}).get("allocation")
            if alloc:
                h["allocation_drift"].update({k: alloc[k] for k in ("current_pct", "target_pct", "drift_pts")})
        brief["output"] = out

    c.write_json(brief_path, brief)
    print(f"   wrote briefs/{brief_path.name}")
    render.render_today(brief, decisions.get("decisions", []))
    if brief["error"]:
        print(brief["error"])
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
