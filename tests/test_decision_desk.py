"""Offline tests for the Decision Desk: cost math, budget guardrail, rule
checks, schemas, and page rendering. No network, no API calls."""

import json
from datetime import date

import pytest

from decision_desk import common as c
from decision_desk import prompts, render


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "COSTS_PATH", tmp_path / "api_costs.csv")
    monkeypatch.setattr(c, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(render, "DOCS_DIR", tmp_path / "docs")
    return tmp_path


def test_estimate_cost_sonnet_and_batch_discount():
    # 1M input + 1M output on Sonnet 5.5 = $2 + $10
    assert c.estimate_cost("claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(12.0)
    # Batch halves every line
    assert c.estimate_cost("claude-opus-5-5", input_tokens=1_000_000, batch=True) == pytest.approx(2.0)
    # Unknown model priced at the most expensive row, never under-counted
    assert c.estimate_cost("claude-mystery", output_tokens=1_000_000) == pytest.approx(50.0)


def test_log_cost_and_month_to_date(tmp_paths):
    usage = {"input_tokens": 1000, "output_tokens": 2000, "cache_creation_input_tokens": 3000,
             "cache_read_input_tokens": 0}
    row = c.log_cost("daily", "t", "claude-sonnet-5-5", usage)
    assert row["est_cost_usd"] == pytest.approx((1000 * 2 + 2000 * 10 + 3000 * 2.5) / 1e6)
    assert c.month_to_date_spend() == pytest.approx(row["est_cost_usd"], abs=1e-4)


def test_budget_guardrail(tmp_paths, monkeypatch):
    monkeypatch.setattr(c, "MTD_CAP_USD", 1.0)
    c.check_budget(0.5, "ok")
    c.log_cost("daily", "t", "claude-opus-5-5", {"output_tokens": 45_000})  # $0.90
    with pytest.raises(c.BudgetExceeded):
        c.check_budget(0.2, "would pass cap")
    c.log_cost("daily", "t", "claude-opus-5-5", {"output_tokens": 10_000})  # now $1.10
    with pytest.raises(c.BudgetExceeded):
        c.check_budget(0.0, "already past cap")


def _snapshot(pl_pct=-2.0, dd=-3.0, current=4.0, last_buy="2026-10-07"):
    return {"holdings": [{
        "ticker": "BTC", "value_usd": 40, "unrealized_pl_pct": pl_pct, "drawdown_from_peak_pct": dd,
        "last_buy_date": last_buy, "lots": [{"date": last_buy}],
        "allocation": {"current_pct": current, "target_pct": 10, "drift_pts": current - 10},
    }]}


def _theses(**dca):
    return {"portfolio": {"max_position_pct": 10, "rebalance_band_pts": 5, "stop_loss_soft_pct": -8,
                          "stop_loss_hard_pct": -15, "trailing_stop_pct": 12},
            "holdings": [{"ticker": "BTC", "review_status": "REVIEWED", "review_by": "2027-01-01",
                          "dca_rules": {"frequency": "weekly", "max_buys_per_month": 4,
                                        "min_days_between_buys": 7, **dca}}]}


def _hit(trigs):
    return {t["rule"] for t in trigs["BTC"] if t["triggered"]}


def test_rules_quiet_when_within_bounds():
    hits = _hit(c.rule_triggers(_snapshot(current=9.0, last_buy="2026-10-08"), _theses(frequency="biweekly"),
                                [], date(2026, 10, 16)))
    assert hits == set()


def test_rules_fire():
    hits = _hit(c.rule_triggers(_snapshot(pl_pct=-16, dd=-20, current=30, last_buy="2026-10-01"),
                                _theses(), [], date(2026, 10, 16)))
    assert {"stop_loss_soft", "stop_loss_hard", "trailing_stop", "max_position_pct",
            "allocation_band", "dca_due"} <= hits


def test_missing_and_unreviewed_thesis():
    th = _theses()
    th["holdings"][0]["review_status"] = "NEEDS JEREMIAH REVIEW"
    assert "thesis_reviewed" in _hit(c.rule_triggers(_snapshot(), th, [], date(2026, 10, 16)))
    snap = _snapshot()
    snap["holdings"][0]["ticker"] = "ETH"
    trig = c.rule_triggers(snap, th, [], date(2026, 10, 16))
    assert trig["ETH"][0]["rule"] == "thesis_on_file"


def test_schemas_are_strict_objects():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False
            assert set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    for schema in (prompts.DAILY_SCHEMA, prompts.WEEKLY_HOLDING_SCHEMA, prompts.WEEKLY_PORTFOLIO_SCHEMA):
        walk(schema)
        json.dumps(schema)


def test_system_prompt_is_stable_and_cached():
    th = {"b": 1, "a": 2}
    a = prompts.system_blocks(prompts.DAILY_RUBRIC, th)
    b = prompts.system_blocks(prompts.DAILY_RUBRIC, {"a": 2, "b": 1})
    assert a == b
    assert a[-1]["cache_control"] == {"type": "ephemeral"}


def test_no_em_dashes_in_prompts_or_pages():
    for text in (prompts.DAILY_RUBRIC, prompts.WEEKLY_HOLDING_RUBRIC, prompts.WEEKLY_PORTFOLIO_RUBRIC,
                 render.DECISION_FORM, c.FOOTER_TEXT):
        assert chr(0x2014) not in text


def test_render_pages_carry_footer(tmp_paths):
    brief = {"date": "2026-10-16", "model": "claude-sonnet-5-5", "error": None,
             "snapshot": {"total_value_usd": 43.27, "total_cost_basis_usd": 44.14, "planned_capital_usd": 1000,
                          "cash_usd": 956.73, "holdings": [{"ticker": "BTC", "price": 81627.06,
                                                            "day_change_pct": -0.63, "week_change_pct": -2.45,
                                                            "unrealized_pl_pct": -1.98, "cost_basis_usd": 44.14}]},
             "output": {"portfolio_note": "One small position.", "journal_nudge": "Log the hold.",
                        "holdings": [{"ticker": "BTC", "what_changed": "<b>Quiet</b> week.", "thesis_status": "watch",
                                      "allocation_drift": {"current_pct": 4.33, "target_pct": 10, "drift_pts": -5.67,
                                                           "comment": "Under target."},
                                      "rule_triggers": [{"rule": "dca_due", "detail": "9 days"}],
                                      "questions_before_acting": ["Is the thesis still yours?"]}]}}
    render.render_today(brief, [])
    render.render_weekly(None)
    today = (tmp_paths / "docs" / "today.html").read_text(encoding="utf-8")
    weekly = (tmp_paths / "docs" / "weekly.html").read_text(encoding="utf-8")
    for page in (today, weekly):
        assert "Research aid, not financial advice" in page
    assert "&lt;b&gt;Quiet&lt;/b&gt;" in today  # model text is escaped
    assert "data/decisions.json" in today
