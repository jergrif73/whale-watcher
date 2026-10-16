"""Weekly deep review (Sunday) through the Message Batches API (50% off).

    python -m decision_desk.weekly_review --dry-run   # print prompts + token/cost estimate, no API call
    python -m decision_desk.weekly_review             # submit, wait, collect
    python -m decision_desk.weekly_review --collect   # only collect a batch left pending by an earlier run

One request per holding plus one portfolio-level request (concentration,
correlation, DCA pacing, rule violations, decision-journal scoring), all on
an Opus-class model. Writes reviews/YYYY-WW.json and docs/weekly.html.
"""

import argparse
import json
import os
import sys
import time as _time
from datetime import datetime, timedelta

from decision_desk import common as c
from decision_desk import prompts, render

HOLDING_MAX_TOKENS = int(os.environ.get("DESK_WEEKLY_HOLDING_MAX_TOKENS", "10000"))
PORTFOLIO_MAX_TOKENS = int(os.environ.get("DESK_WEEKLY_PORTFOLIO_MAX_TOKENS", "16000"))
EFFORT = "high"
WAIT_MINUTES = int(os.environ.get("DESK_BATCH_WAIT_MIN", "330"))
PENDING_PATH = c.REVIEWS_DIR / "pending.json"
BENCHMARKS = {"SPY": "SPY", "QQQ": "QQQ", "BTC": "BTC-USD"}


def week_briefs(today):
    start = today - timedelta(days=6)
    out = []
    for p in sorted(c.BRIEFS_DIR.glob("*.json")) if c.BRIEFS_DIR.exists() else []:
        if start.isoformat() <= p.stem <= today.isoformat():
            b = c.load_json(p, {})
            out.append({"date": b.get("date"), "error": b.get("error"),
                        "status": {h["ticker"]: h["thesis_status"] for h in (b.get("output") or {}).get("holdings", [])},
                        "triggers": {h["ticker"]: [t["rule"] for t in h.get("rule_triggers", [])]
                                     for h in (b.get("output") or {}).get("holdings", [])}})
    return out


def correlation_table(histories):
    import pandas as pd
    series = {t: df["Close"] for t, df in histories.items()}
    for name, sym in BENCHMARKS.items():
        if name not in series:
            df = c.fetch_history(sym, period="6mo")
            if df is not None:
                series[name] = df["Close"]
    frame = pd.DataFrame(series).dropna().tail(91)
    rets = frame.pct_change().dropna()
    if len(rets) < 20:
        return {"note": f"only {len(rets)} overlapping days, correlation not meaningful"}
    corr = rets.corr().round(2)
    return {"window_days": len(rets), "matrix": {a: {b: float(corr.loc[a, b]) for b in corr.columns} for a in corr.index}}


def decision_outcomes(decisions, histories, theses):
    by_ticker = {h["ticker"]: h for h in theses.get("holdings", [])}
    out = []
    today = c.today_ny()
    for d in decisions:
        t = d.get("ticker")
        df = histories.get(t)
        if df is None and t:
            try:
                df = c.fetch_history(c._yf_symbol(t, by_ticker.get(t)))
            except Exception:  # noqa: BLE001
                df = None
        px_then = d.get("price_at_decision")
        if px_then is None and df is not None and d.get("date"):
            px_then = c.close_on(df, datetime.fromisoformat(d["date"][:10]).date())
        px_now = float(df["Close"].iloc[-1]) if df is not None else None
        out.append({
            "id": d.get("id"), "date": d.get("date"), "ticker": t, "action": d.get("action"),
            "amount_usd": d.get("amount_usd"), "reasoning": d.get("reasoning"),
            "thesis_status_at_time": d.get("thesis_status_at_time"),
            "price_at_decision": px_then, "price_now": px_now,
            "price_change_since_pct": c._pct(px_now, px_then),
            "days_since": (today - datetime.fromisoformat(d["date"][:10]).date()).days if d.get("date") else None,
            "reading_note": "For sell, trim, skip_dca or hold-instead-of-buy, a price drop since means the decision helped; for buy or add, a rise helped.",
        })
    return out


def dca_history(snapshot):
    hist = {}
    for h in snapshot["holdings"]:
        months = {}
        for l in h.get("lots", []):
            months[l["date"][:7]] = months.get(l["date"][:7], 0) + 1
        hist[h["ticker"]] = {"lots": h.get("lots", []), "buys_per_month": months}
    return hist


def build_requests(theses, decisions, today):
    snapshot = c.build_snapshot(theses)
    histories = snapshot["_histories"]
    triggers = c.rule_triggers(snapshot, theses, decisions, today)
    tickers = [h["ticker"] for h in snapshot["holdings"]]
    news = c.fetch_news(theses, tickers)
    briefs = week_briefs(today)
    outcomes = decision_outcomes(decisions, histories, theses)
    corr = correlation_table(histories)
    snap = c.strip_private(snapshot)

    reqs = []
    hold_sys = prompts.system_blocks(prompts.WEEKLY_HOLDING_RUBRIC, theses)
    for h in snap["holdings"]:
        t = h["ticker"]
        df = histories.get(t)
        monthly = ([{"month": str(k)[:7], "close": round(float(v), 4)}
                    for k, v in df["Close"].groupby(lambda d: d.strftime("%Y-%m")).last().items()]
                   if df is not None else [])
        payload = {"week_ending": today.isoformat(), "holding": h, "monthly_closes_1y": monthly,
                   "rule_triggers": triggers.get(t, []), "daily_briefs_this_week": briefs,
                   "news": news.get(t), "decisions_for_ticker": [o for o in outcomes if o["ticker"] == t]}
        reqs.append({"custom_id": f"holding-{t}", "max_tokens": HOLDING_MAX_TOKENS,
                     "schema": prompts.WEEKLY_HOLDING_SCHEMA, "system": hold_sys,
                     "messages": [{"role": "user", "content": f"Weekly review for {t}. Data as JSON:\n\n"
                                   + json.dumps(payload, indent=1, default=str)}]})
    port_payload = {"week_ending": today.isoformat(), "portfolio": {k: v for k, v in snap.items() if k != "holdings"},
                    "holdings": snap["holdings"], "correlation_90d": corr, "rule_triggers": triggers,
                    "dca_history": dca_history(snap), "daily_briefs_this_week": briefs,
                    "all_decisions": outcomes}
    reqs.append({"custom_id": "portfolio", "max_tokens": PORTFOLIO_MAX_TOKENS,
                 "schema": prompts.WEEKLY_PORTFOLIO_SCHEMA,
                 "system": prompts.system_blocks(prompts.WEEKLY_PORTFOLIO_RUBRIC, theses),
                 "messages": [{"role": "user", "content": "Portfolio-level weekly review. Data as JSON:\n\n"
                               + json.dumps(port_payload, indent=1, default=str)}]})
    context = {"snapshot": snap, "correlation_90d": corr, "decision_outcomes": outcomes, "rule_triggers": triggers}
    return reqs, context


def make_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic(max_retries=3)


def submit(client, reqs):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    batch = client.messages.batches.create(requests=[
        Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(
            model=c.WEEKLY_MODEL, max_tokens=r["max_tokens"], system=r["system"], messages=r["messages"],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": r["schema"]}},
        )) for r in reqs])
    print(f"   submitted batch {batch.id} with {len(reqs)} requests")
    return batch.id


def collect(client, pending):
    batch_id = pending["batch_id"]
    deadline = _time.time() + WAIT_MINUTES * 60
    while True:
        b = client.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            break
        if _time.time() > deadline:
            print(f"Batch {batch_id} still {b.processing_status} after {WAIT_MINUTES} min. "
                  "It stays in reviews/pending.json; run the workflow again with collect_only to finish.")
            return None
        print(f"   batch {b.processing_status}: {b.request_counts.processing} processing")
        _time.sleep(60)

    review = {"week": pending["week"], "batch_id": batch_id, "model": c.WEEKLY_MODEL,
              "generated_at_utc": c.now_utc().isoformat(timespec="seconds"),
              "holdings": [], "portfolio": None, "errors": [], "usage": [], **pending["context"]}
    for res in client.messages.batches.results(batch_id):
        cid, r = res.custom_id, res.result
        if r.type != "succeeded":
            review["errors"].append(f"{cid}: {r.type}")
            continue
        msg = r.message
        review["model"] = msg.model
        review["usage"].append({"custom_id": cid, **c.log_cost("weekly", f"{pending['week']}:{cid}", msg.model,
                                                                msg.usage, batch=True)})
        if msg.stop_reason != "end_turn":
            review["errors"].append(f"{cid}: stop_reason {msg.stop_reason}, no usable output")
            continue
        out = json.loads(next(x.text for x in msg.content if x.type == "text"))
        if cid == "portfolio":
            review["portfolio"] = out
        else:
            review["holdings"].append(out)
    review["holdings"].sort(key=lambda h: h["ticker"])
    return review


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--collect", action="store_true", help="only collect a pending batch")
    args = ap.parse_args(argv)
    client = make_client()

    pending = c.load_json(PENDING_PATH, None)
    if pending and not args.dry_run:
        if client is None:
            print("ANTHROPIC_API_KEY is not set.")
            return 1
        print(f"Collecting pending batch {pending['batch_id']} for week {pending['week']}")
        return finish(client, pending)
    if args.collect:
        print("No pending batch to collect.")
        return 0

    today = c.today_ny()
    week = c.iso_week_label(today)
    theses = c.load_json(c.THESES_PATH, {"holdings": []})
    decisions = c.load_json(c.DECISIONS_PATH, {"version": 1, "decisions": []})
    if not args.dry_run and c.backfill_decision_prices(decisions, theses):
        c.write_json(c.DECISIONS_PATH, decisions)

    print(f"Decision Desk weekly review for {week} ({'DRY RUN' if args.dry_run else 'live'})")
    reqs, context = build_requests(theses, decisions.get("decisions", []), today)
    worst = 0.0
    typical = 0.0
    for r in reqs:
        n, how = c.count_input_tokens(client, c.WEEKLY_MODEL, r["system"], r["messages"])
        r["input_tokens"], r["count_method"] = n, how
        worst += c.estimate_cost(c.WEEKLY_MODEL, cache_write_tokens=n, output_tokens=r["max_tokens"], batch=True)
        typical += c.estimate_cost(c.WEEKLY_MODEL, cache_write_tokens=n, output_tokens=3000, batch=True)
    mtd = c.month_to_date_spend()

    if args.dry_run:
        shown = [reqs[0], reqs[-1]] if len(reqs) > 1 else reqs
        for r in shown:
            print("\n" + "=" * 25 + f" {r['custom_id']}: SYSTEM (cached prefix) " + "=" * 25)
            for b in r["system"]:
                print(b["text"])
                print("-" * 84)
            print("=" * 25 + f" {r['custom_id']}: USER " + "=" * 25)
            print(r["messages"][0]["content"])
        print("=" * 84)
        for r in reqs:
            print(f"{r['custom_id']}: {r['input_tokens']} input tokens ({r['count_method']}), max_tokens {r['max_tokens']}")
        print(f"Model {c.WEEKLY_MODEL} via Message Batches (50% off), effort {EFFORT}")
        print(f"Typical cost (~3k output each): ${typical:.4f}   Worst case at max_tokens: ${worst:.4f}")
        print(f"Month to date: ${mtd:.2f} of ${c.MTD_CAP_USD:.0f} cap")
        print("DRY RUN: no batch submitted, nothing written.")
        return 0

    if client is None:
        print("ANTHROPIC_API_KEY is not set. Use --dry-run, or set the secret.")
        return 1
    try:
        c.check_budget(worst, "weekly review")
    except c.BudgetExceeded as ex:
        print(str(ex))
        return 2
    batch_id = submit(client, reqs)
    pending = {"batch_id": batch_id, "week": week, "submitted_at_utc": c.now_utc().isoformat(timespec="seconds"),
               "context": context}
    c.write_json(PENDING_PATH, pending)
    return finish(client, pending)


def finish(client, pending):
    review = collect(client, pending)
    if review is None:
        return 0
    path = c.REVIEWS_DIR / f"{pending['week']}.json"
    c.write_json(path, review)
    PENDING_PATH.unlink(missing_ok=True)
    print(f"   wrote reviews/{path.name}")
    render.render_weekly(review)
    return 3 if review["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
