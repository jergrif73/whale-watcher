"""Shared plumbing for the Decision Desk: paths, cost ledger and guardrail,
market snapshot, deterministic rule checks.

Research aid only. Nothing in this package places trades or talks to a
brokerage. It reads the trade journal, prices from yfinance, news from
Alpha Vantage, and writes JSON + static HTML.
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

THESES_PATH = ROOT / "data" / "theses.json"
DECISIONS_PATH = ROOT / "data" / "decisions.json"
COSTS_PATH = ROOT / "data" / "api_costs.csv"
TRADE_JOURNAL_PATH = ROOT / "docs" / "data" / "trade_journal.json"
BRIEFS_DIR = ROOT / "briefs"
REVIEWS_DIR = ROOT / "reviews"
DOCS_DIR = ROOT / "docs"

NY = ZoneInfo("America/New_York")

MTD_CAP_USD = float(os.environ.get("DESK_MTD_CAP_USD", "150"))

DAILY_MODEL = "claude-sonnet-5-5"
WEEKLY_MODEL = "claude-opus-5-5"

# USD per million tokens. cache_write is the 5-minute TTL rate (1.25x input).
# Batch requests bill at 50% of every line. Unknown models (for example a
# server-side refusal fallback) are priced at the most expensive row so the
# ledger never under-counts.
PRICING = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    "claude-opus-5-5":   {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-opus-5":     {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-fable-5-1":  {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 0.25},
}
FALLBACK_PRICING = PRICING["claude-fable-5-1"]
BATCH_DISCOUNT = 0.5

COST_FIELDS = [
    "timestamp_utc", "run_type", "run_id", "model", "batch",
    "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens",
    "est_cost_usd", "note",
]

FOOTER_TEXT = "Research aid, not financial advice. Nothing here places trades or calls a brokerage."


class BudgetExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------- io helpers

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_ny() -> date:
    return datetime.now(NY).date()


# ------------------------------------------------------------- cost ledger

def price_for(model: str) -> dict:
    return PRICING.get(model, FALLBACK_PRICING)


def estimate_cost(model: str, input_tokens: int = 0, output_tokens: int = 0,
                  cache_write_tokens: int = 0, cache_read_tokens: int = 0,
                  batch: bool = False) -> float:
    p = price_for(model)
    usd = (input_tokens * p["input"] + output_tokens * p["output"]
           + cache_write_tokens * p["cache_write"] + cache_read_tokens * p["cache_read"]) / 1_000_000
    return usd * (BATCH_DISCOUNT if batch else 1.0)


def usage_cost(model: str, usage, batch: bool = False) -> dict:
    """Pull token counts off an SDK usage object (or dict) and price them."""
    def g(name):
        v = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
        return int(v or 0)
    row = {
        "input_tokens": g("input_tokens"),
        "cache_write_tokens": g("cache_creation_input_tokens"),
        "cache_read_tokens": g("cache_read_input_tokens"),
        "output_tokens": g("output_tokens"),
    }
    row["est_cost_usd"] = round(estimate_cost(model, batch=batch, **row), 6)
    return row


def log_cost(run_type: str, run_id: str, model: str, usage, batch: bool = False,
             note: str = "") -> dict:
    row = {
        "timestamp_utc": now_utc().isoformat(timespec="seconds"),
        "run_type": run_type,
        "run_id": run_id,
        "model": model,
        "batch": "yes" if batch else "no",
        **usage_cost(model, usage, batch=batch),
        "note": note,
    }
    COSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not COSTS_PATH.exists()
    with COSTS_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COST_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)
    print(f"   cost: {model} in={row['input_tokens']} cw={row['cache_write_tokens']} "
          f"cr={row['cache_read_tokens']} out={row['output_tokens']} -> ${row['est_cost_usd']:.4f}")
    return row


def read_costs() -> list:
    if not COSTS_PATH.exists():
        return []
    with COSTS_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def month_to_date_spend(on: date = None) -> float:
    on = on or now_utc().date()
    prefix = on.strftime("%Y-%m")
    return round(sum(float(r["est_cost_usd"] or 0) for r in read_costs()
                     if r["timestamp_utc"].startswith(prefix)), 4)


def check_budget(projected_usd: float, label: str) -> float:
    """Abort before a call when month-to-date spend has passed the cap, or
    when this call's worst case would push it past. Returns MTD."""
    mtd = month_to_date_spend()
    if mtd >= MTD_CAP_USD:
        raise BudgetExceeded(f"{label}: month-to-date spend ${mtd:.2f} has reached the ${MTD_CAP_USD:.0f} cap. Aborting.")
    if mtd + projected_usd > MTD_CAP_USD:
        raise BudgetExceeded(
            f"{label}: worst case ${projected_usd:.2f} on top of ${mtd:.2f} month-to-date "
            f"would pass the ${MTD_CAP_USD:.0f} cap. Aborting.")
    return mtd


def count_input_tokens(client, model: str, system, messages) -> tuple:
    """Exact count via the free count_tokens endpoint when a client is
    available, else a conservative character heuristic. Returns (tokens, how)."""
    if client is not None:
        try:
            r = client.messages.count_tokens(model=model, system=system, messages=messages)
            return r.input_tokens, "count_tokens"
        except Exception as e:  # noqa: BLE001 - estimate only, never fatal
            print(f"   count_tokens failed ({e}); using heuristic")
    chars = sum(len(b["text"]) for b in system) + sum(
        len(m["content"]) if isinstance(m["content"], str) else 0 for m in messages)
    return int(chars / 3.2) + 50, "heuristic (chars / 3.2)"


# ---------------------------------------------------------- market snapshot

def _yf_symbol(ticker: str, thesis: dict) -> str:
    if thesis and thesis.get("yf_symbol"):
        return thesis["yf_symbol"]
    from whale_watcher_agent import CRYPTO_SYMBOLS
    return f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker


def fetch_history(symbol: str, period: str = "1y"):
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return None
    df = df[["Close", "Volume"]].copy()
    df.index = [d.date() for d in df.index]
    return df


def close_on(df, day: date):
    """First close on or after `day`; falls back to the last close before it."""
    after = [d for d in df.index if d >= day]
    if after:
        return float(df.loc[after[0], "Close"])
    return float(df["Close"].iloc[-1])


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


def load_holdings() -> dict:
    """Current positions from the dashboard's trade journal (dollar based,
    FIFO lots), using the agent's own TradeJournal so the math matches."""
    from whale_watcher_agent import TradeJournal
    return TradeJournal(str(TRADE_JOURNAL_PATH)).get_positions()


def build_snapshot(theses: dict) -> dict:
    """Positions, lots, cost basis, day/week moves, allocation vs target."""
    thesis_by_ticker = {h["ticker"]: h for h in theses.get("holdings", [])}
    portfolio_cfg = theses.get("portfolio", {})
    positions = load_holdings()
    holdings = []
    histories = {}
    for ticker, pos in sorted(positions.items()):
        th = thesis_by_ticker.get(ticker)
        sym = _yf_symbol(ticker, th)
        df = fetch_history(sym)
        if df is None:
            holdings.append({"ticker": ticker, "error": f"no price data for {sym}"})
            continue
        histories[ticker] = df
        closes = df["Close"]
        price = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        week_ago = float(closes.iloc[-6]) if len(closes) > 5 else None
        lots = []
        cost_basis = 0.0
        value = 0.0
        for lot in pos["lots"]:
            d = datetime.fromisoformat(lot["date"][:10]).date()
            buy_px = close_on(df, d)
            lot_value = lot["amount"] * price / buy_px if buy_px else lot["amount"]
            cost_basis += lot["amount"]
            value += lot_value
            lots.append({"date": d.isoformat(), "amount_usd": round(lot["amount"], 2),
                         "price_at_buy": round(buy_px, 4), "value_now": round(lot_value, 2),
                         "pl_pct": _pct(lot_value, lot["amount"])})
        first_buy = min(datetime.fromisoformat(l["date"]).date() for l in lots) if lots else None
        peak = float(closes[[d >= first_buy for d in closes.index]].max()) if first_buy else price
        holdings.append({
            "ticker": ticker,
            "price": round(price, 4),
            "day_change_pct": _pct(price, prev),
            "week_change_pct": _pct(price, week_ago),
            "cost_basis_usd": round(cost_basis, 2),
            "value_usd": round(value, 2),
            "unrealized_pl_usd": round(value - cost_basis, 2),
            "unrealized_pl_pct": _pct(value, cost_basis),
            "peak_since_first_buy": round(peak, 4),
            "drawdown_from_peak_pct": _pct(price, peak),
            "first_buy_date": first_buy.isoformat() if first_buy else None,
            "last_buy_date": max(l["date"] for l in lots) if lots else None,
            "lots": lots,
            "has_thesis": th is not None,
        })
    total_value = sum(h.get("value_usd", 0) for h in holdings)
    planned = portfolio_cfg.get("planned_capital_usd")
    denom = max(planned or 0, total_value) or 1
    for h in holdings:
        if "value_usd" not in h:
            continue
        th = thesis_by_ticker.get(h["ticker"]) or {}
        cur = round(h["value_usd"] / denom * 100, 2)
        tgt = th.get("target_allocation_pct")
        h["allocation"] = {
            "current_pct": cur,
            "target_pct": tgt,
            "drift_pts": round(cur - tgt, 2) if tgt is not None else None,
            "denominator": "planned_capital_usd" if planned and planned >= total_value else "total_value",
        }
    return {
        "as_of_utc": now_utc().isoformat(timespec="seconds"),
        "as_of_ny": datetime.now(NY).isoformat(timespec="minutes"),
        "total_value_usd": round(total_value, 2),
        "total_cost_basis_usd": round(sum(h.get("cost_basis_usd", 0) for h in holdings), 2),
        "planned_capital_usd": planned,
        "cash_usd": round(planned - total_value, 2) if planned and planned >= total_value else None,
        "holdings": holdings,
        "_histories": histories,
    }


def google_news(query: str, limit: int = 8) -> list:
    """Headlines from the Google News RSS search feed (no key). Titles only."""
    import requests
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    r = requests.get("https://news.google.com/rss/search",
                     params={"q": f"{query} when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    items = []
    for it in ET.fromstring(r.content).findall("./channel/item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        items.append({"time": when.isoformat(timespec="minutes"), "source": it.findtext("source") or "",
                      "title": (it.findtext("title") or "")[:160]})
    items.sort(key=lambda x: x["time"], reverse=True)
    return items[:limit]


def fetch_news(theses: dict, tickers: list) -> dict:
    """Alpha Vantage NEWS_SENTIMENT first (through the agent's own client).
    That endpoint answers "premium endpoint" on the current free key, so
    fall back to Google News RSS headlines with no sentiment score."""
    key = os.environ.get("ALPHA_VANTAGE_KEY", "")
    agent = None
    if key:
        from whale_watcher_agent import AIResearchAgent
        agent = AIResearchAgent(key)
    by_ticker = {h["ticker"]: h for h in theses.get("holdings", [])}
    out = {}
    for t in tickers:
        th = by_ticker.get(t) or {}
        r = agent.get_news_sentiment(th.get("news_symbol") or t) if agent else None
        if r and r.get("news_count"):
            out[t] = {"source": "Alpha Vantage NEWS_SENTIMENT", "sentiment_label": r["sentiment_label"],
                      "sentiment_score": r["sentiment_score"], "headlines": r["headlines"]}
            continue
        query = th.get("news_query") or t
        try:
            out[t] = {"source": f"Google News RSS, query {query!r}, last 3 days, no sentiment score",
                      "headlines": google_news(query)}
        except Exception as e:  # noqa: BLE001 - news is optional context
            out[t] = {"note": f"no news available ({e})"}
    return out


# ----------------------------------------------------------- rule checks

def _days_between(a: str, b: date) -> int:
    return (b - datetime.fromisoformat(a[:10]).date()).days


def rule_triggers(snapshot: dict, theses: dict, decisions: list, on: date) -> dict:
    """Deterministic checks against my own written rules. The model gets
    these as facts; it does not recompute them."""
    pcfg = theses.get("portfolio", {})
    by_ticker = {h["ticker"]: h for h in theses.get("holdings", [])}
    out = {}
    for h in snapshot["holdings"]:
        if "value_usd" not in h:
            continue
        t = h["ticker"]
        th = by_ticker.get(t)
        trig = []

        def add(rule, triggered, detail):
            trig.append({"rule": rule, "triggered": bool(triggered), "detail": detail})

        if th is None:
            add("thesis_on_file", True, "No entry in data/theses.json for this holding.")
            out[t] = trig
            continue
        add("thesis_reviewed", th.get("review_status") != "REVIEWED",
            f"review_status is {th.get('review_status')!r}.")
        rb = th.get("review_by")
        add("thesis_review_date", bool(rb) and on.isoformat() > rb, f"review_by {rb}.")
        alloc = h["allocation"]
        band = pcfg.get("rebalance_band_pts", 5)
        if alloc["drift_pts"] is not None:
            add("allocation_band", abs(alloc["drift_pts"]) > band,
                f"{alloc['current_pct']}% vs target {alloc['target_pct']}% (band +/-{band} pts).")
        mx = pcfg.get("max_position_pct")
        if mx is not None:
            add("max_position_pct", alloc["current_pct"] > mx, f"{alloc['current_pct']}% vs max {mx}%.")
        pl = h["unrealized_pl_pct"]
        soft, hard = pcfg.get("stop_loss_soft_pct", -8), pcfg.get("stop_loss_hard_pct", -15)
        add("stop_loss_soft", pl is not None and pl <= soft, f"P/L {pl}% vs soft stop {soft}%.")
        add("stop_loss_hard", pl is not None and pl <= hard, f"P/L {pl}% vs hard stop {hard}%.")
        trail = pcfg.get("trailing_stop_pct", 12)
        dd = h["drawdown_from_peak_pct"]
        add("trailing_stop", dd is not None and dd <= -trail, f"{dd}% from peak vs trailing stop -{trail}%.")
        dca = th.get("dca_rules") or {}
        freq_days = {"weekly": 7, "biweekly": 14, "monthly": 30}.get(dca.get("frequency"), None)
        if freq_days and h["last_buy_date"]:
            since = _days_between(h["last_buy_date"], on)
            add("dca_due", since >= freq_days,
                f"{since} days since last buy; cadence is {dca.get('frequency')} ({freq_days} days). "
                "Due only means the calendar says so; pause conditions still apply.")
            mind = dca.get("min_days_between_buys")
            if mind:
                add("dca_too_soon_to_add", since < mind, f"{since} days since last buy vs minimum {mind}.")
        mbpm = dca.get("max_buys_per_month")
        if mbpm:
            month = on.strftime("%Y-%m")
            buys = sum(1 for l in h["lots"] if l["date"].startswith(month))
            add("dca_monthly_pace", buys > mbpm, f"{buys} buys this month vs max {mbpm}.")
        out[t] = trig
    return out


def backfill_decision_prices(decisions: dict, theses: dict) -> bool:
    """Fill price_at_decision on journal entries logged from the form."""
    by_ticker = {h["ticker"]: h for h in theses.get("holdings", [])}
    changed = False
    cache = {}
    for d in decisions.get("decisions", []):
        if d.get("price_at_decision") is not None or not d.get("ticker") or not d.get("date"):
            continue
        sym = _yf_symbol(d["ticker"], by_ticker.get(d["ticker"]))
        if sym not in cache:
            try:
                cache[sym] = fetch_history(sym)
            except Exception as e:  # noqa: BLE001
                print(f"   price backfill failed for {sym}: {e}")
                cache[sym] = None
        df = cache[sym]
        if df is not None:
            d["price_at_decision"] = round(close_on(df, datetime.fromisoformat(d["date"][:10]).date()), 4)
            changed = True
    return changed


def strip_private(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if not k.startswith("_")}


def iso_week_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-{w:02d}"
