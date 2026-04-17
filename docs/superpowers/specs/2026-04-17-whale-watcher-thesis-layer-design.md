# Whale Watcher — Thesis-Override Layer

**Status:** Design approved, awaiting user review before implementation plan
**Author:** Jeremiah Griffith (with Claude Opus 4.7)
**Date:** 2026-04-17
**Repo:** github.com/jergrif73/whale-watcher

---

## 1. Problem Statement

Whale Watcher's signal engine is working correctly — it has fired `SELL_ALL - hard stop loss triggered at -15%` for COIN on every scheduled run for five consecutive days (Apr 13 – Apr 17, 2026), and twice for MSFT before downgrading to `EVALUATE`. The user has ignored every one of those signals because he holds a thesis the tool does not know about ("Bitcoin halving cycle bottom; COIN tracks BTC beta").

This creates three failure modes simultaneously:

1. **Signal noise** — the same mechanical alert fires twice a day with no new information, training the user to ignore all alerts (including ones he *should* act on).
2. **No discipline enforcement** — the tool has no mechanism to capture *why* the user is overriding, forcing him to hold the full thesis in memory with no invalidation criteria.
3. **No calibration loop** — 6 months from now there will be no record of whether the override was smart or wishful thinking, so the user can never learn from past decisions.

The tool's job should shift from "mechanical alert generator" to "discipline enforcer": capture the thesis, surface a bear-case critique in a fresh LLM context to neutralize sycophancy, silence mechanical alerts while the thesis is active, and escalate hard only when user-defined invalidation conditions trip.

## 2. Goals

- **G1.** Capture thesis + invalidation criteria at the moment a user decides to override a signal
- **G2.** Run a Claude API bear-agent critique in a fresh session (no chat history) at thesis creation time and store it with the thesis
- **G3.** Suppress recurring mechanical alerts for positions with an active thesis, *unless* an invalidation condition trips
- **G4.** Evaluate invalidation conditions on every scheduled run (price + technical conditions machine-computable; narrative conditions flagged for manual check)
- **G5.** Schedule automatic review checkpoints at 30 / 90 / 180 days and on a user-set `review_date`
- **G6.** Produce a conviction-calibration report once there is enough outcome history (>3 closed theses)

## 3. Non-Goals

- Building a web-dashboard "Override" button (Dispatch-first; deferred)
- Multi-model Claude-vs-GPT disagreement flagging (nice-to-have; deferred)
- Auto-trade execution or broker integration (explicitly out of scope)
- Portfolio rebalancing suggestions (out of scope)
- Changes to existing signal computation logic (`PositionAnalyzer`, `TechnicalAnalyzer`, etc.)

## 4. Data Model

### 4.1 `docs/data/theses.json` (new file, git-versioned)

```jsonc
{
  "theses": [
    {
      "id": "coin-2026-04-17",                 // slug format: <ticker-lower>-<date>
      "ticker": "COIN",
      "created": "2026-04-17",                 // ISO date
      "author": "jeremiah",                    // for future multi-user
      "thesis": "Bitcoin halving cycle bottom; COIN tracks BTC beta",
      "enter_tag": "btc_halving_cycle",        // freqtrade-style short slug
      "conviction": 7,                          // 1-10 self-rated at creation
      "pre_mortem": "If this fails it's because BTC doesn't bottom by Q3",

      "invalidation_criteria": [
        {"type": "price",     "condition": "close < 140 for 5 sessions", "auto": true},
        {"type": "technical", "condition": "weekly RSI < 30",            "auto": true},
        {"type": "narrative", "condition": "BTC fails cycle high by Q3", "auto": false}
      ],

      "red_team_critique": "COIN revenue is 95% transaction volume; if BTC consolidates sideways rather than bottoming, volumes compress and margins follow. ...",
      "unverified_claims": [],                 // claims bear agent flagged as unsupported
      "bear_agent_model": "claude-opus-4-7",
      "bear_agent_run_at": "2026-04-17T06:12:00Z",

      "status": "active",                      // active | invalidated | vindicated | expired | orphaned
      "review_date": "2026-10-17",             // 6 months after creation
      "review_checkpoints": {
        "30d":  {"due": "2026-05-17", "completed": false, "verdict": null},
        "90d":  {"due": "2026-07-17", "completed": false, "verdict": null},
        "180d": {"due": "2026-10-17", "completed": false, "verdict": null}
      },

      "override_events": [
        {"date": "2026-04-17", "signal": "hard_stop_loss_-15%", "price": 199.83}
      ],

      "outcome": null  // populated at final review: {closed_at, final_price, pct_from_entry, verdict, lesson}
    }
  ],
  "version": 1
}
```

### 4.2 Status lifecycle

```
  ┌─────────┐  invalidation tripped  ┌──────────────┐
  │ active  │───────────────────────▶│ invalidated  │
  └────┬────┘                        └──────────────┘
       │
       │ user marks correct (at review)
       ▼
  ┌─────────────┐
  │ vindicated  │
  └─────────────┘
       
  active ──(review_date passes w/o user action)──▶ expired
  active ──(ticker sold from portfolio)──────────▶ orphaned
```

## 5. Architecture

```
┌── Dispatch chat ────────────┐         ┌── Claude API (fresh session) ────┐
│ "override COIN, thesis: …,  │         │  BearAgent.critique(thesis) →    │
│  invalidation price<140 …"  │────────▶│  "You are a skeptical short-     │
└──────────┬──────────────────┘         │  seller. Do NOT affirm. List     │
           ▼                            │  3 strongest reasons wrong…"     │
┌── scripts/thesis.py ────────┐         └──────────▲───────────────────────┘
│ add / review / mark-verdict │                    │
│ / status                    │────────────────────┘
└──────────┬──────────────────┘
           ▼
┌── docs/data/theses.json ────┐◀─────────────┐
│ ThesisManager.save()        │              │
│ (atomic write + git commit) │              │
└──────────┬──────────────────┘              │
           ▼                                 │
┌── whale_watcher_agent.py ──────────────────┴──┐
│ On scheduled run:                              │
│  1. ThesisManager.load()                       │
│  2. For each position:                         │
│     a. If active thesis exists:                │
│        - Evaluate invalidation_criteria (auto) │
│        - If tripped → escalate alert, mark     │
│          thesis invalidated                    │
│        - Else → suppress recurring stop-loss   │
│          alert for this position               │
│     b. Check review checkpoints                │
│  3. Render "Active Theses" email section       │
└────────────────────────────────────────────────┘
```

### 5.1 New classes

- **`ThesisManager`** — `whale_watcher_agent.py`. Load/save `theses.json`, evaluate invalidation conditions against current market data, manage status transitions, produce email section HTML. Introduced week 1.
- **`BearAgent`** — `whale_watcher_agent.py`. Wraps Claude API. Single public method `critique(thesis, invalidation, pre_mortem) -> dict`. Runs in a fresh conversation context (no system prompt other than the red-team template; no history). **Introduced week 2** — not present in week 1 deliverable.
- **`InvalidationEvaluator`** — helper class. Parses `condition` strings for auto-evaluable types (`price`, `technical`). Falls back to `manual_check` for narrative. Introduced week 1 (price-only), extended week 2 (technical).

**Note on the architecture diagram above:** the Claude API / BearAgent path is dashed into the end-state, but weeks 1 ships fully without it — `scripts/thesis.py add` writes directly to `theses.json` with no LLM call.

### 5.2 New script

- **`scripts/thesis.py`** — Dispatch-callable CLI. Subcommands:
  - `add --ticker COIN --thesis "..." --invalidation "price<140 for 5d,weekly_rsi<30" --conviction 7 --pre-mortem "..."`
  - `review --id coin-2026-04-17` — shows thesis vs current state, prompts for verdict
  - `mark --id coin-2026-04-17 --verdict vindicated|invalidated --lesson "..."`
  - `list [--status active|all]`
  - `report` — conviction-calibration report (week 3)

## 6. Layered Ship Order

### Week 1 — Silent Journal + Suppression

**Scope:** Everything in §4 data model except `red_team_critique`, `unverified_claims`, `bear_agent_*`. All invalidation conditions limited to `price` type only. Email shows "Active Theses" section. No Anthropic API dependency.

**Exit criteria:**
- `scripts/thesis.py add` writes a thesis + commits `theses.json`
- Recurring `hard_stop_loss` alerts suppressed for positions with `status=active` thesis
- Price-based invalidation evaluated every run; tripping sets `status=invalidated` and escalates alert
- "Active Theses" section in email shows thesis text + current price + distance to price invalidation

### Week 2 — Active Critic

**Scope:** Add `BearAgent` class, `ANTHROPIC_API_KEY` secret, integrate critique at thesis creation. Extend invalidation to `technical` type (RSI, MACD, SMA crossovers). Narrative conditions stored but flagged `manual_check`.

**Exit criteria:**
- `scripts/thesis.py add` runs `BearAgent.critique` in a fresh Claude session and persists the critique in the thesis record
- Email "Active Theses" section includes bear critique in a collapsible `<details>` element (renders as indented block in email clients that strip `<details>`)
- Technical invalidation conditions (weekly RSI < X, close below SMA, etc.) evaluated each run
- Narrative conditions displayed with a "⚠️ manual check" badge; never auto-trip
- If `ANTHROPIC_API_KEY` missing, week 1 behavior preserved; email notes "bear critique unavailable"

### Week 3 — Outcome Tracker + Calibration

**Scope:** Review reminders at 30/90/180 days + `review_date`. `scripts/thesis.py review` and `mark` subcommands. `scripts/thesis.py report` produces calibration summary. Outcome capture on close.

**Exit criteria:**
- On each scheduled run, theses with a due review checkpoint appear in a "Thesis Review Due" email section
- `scripts/thesis.py review --id <id>` shows thesis + current state + bear critique + invalidation progress; prompts user to extend, invalidate, or vindicate
- `scripts/thesis.py mark` persists the verdict and lesson
- `scripts/thesis.py report` computes:
  - Overrides attempted: N
  - Vindicated: X (%)
  - Invalidated: Y (%)
  - Average conviction vs outcome correlation
- When a ticker is sold from the portfolio, any active thesis on it auto-transitions to `status=orphaned` with an email notice

## 7. Bear Agent Prompt

Exact prompt passed to Claude API (opus-4-7). No system prompt, no prior messages.

```
You are a skeptical short-seller reviewing the thesis below.

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
```

### Response parsing (deterministic, no LLM re-prompting)

Given the full Claude response text:

1. **Red-team critique** (`red_team_critique` field): the full response text, trimmed.
2. **Unverified claims** (`unverified_claims` array): every substring matching the regex `\[UNVERIFIED\][^.\n]*[.\n]` captured verbatim. Empty array if none.
3. **Bear floor** (appended to `invalidation_criteria` with `type: "bear_floor"`, `auto: false`): the first line in the response starting with the word `Minimum` (case-insensitive). Stored verbatim, never auto-evaluated.

If the response is empty, non-text, or all three extractions yield nothing, persist raw text as `red_team_critique`, leave the other fields empty, and log a warning.

## 8. Invalidation Evaluator Rules

### Price conditions (auto)
- Grammar: `close {OP} {NUMBER} [for {N} sessions]` where OP ∈ {`<`, `<=`, `>`, `>=`}
- Default duration: 1 session (current close)
- Evaluated against yfinance daily close

### Technical conditions (auto, week 2+)
- Supported left-hand sides: `rsi`, `weekly_rsi`, `macd_hist`, `sma_50`, `sma_200`
- Grammar: `{LHS} {OP} {NUMBER}` with optional `for {N} sessions`
- Computed from existing `TechnicalAnalyzer` output

### Narrative conditions (manual)
- Any condition not matching the above grammar is stored verbatim with `auto: false`
- Never auto-trips; surfaced in email with manual-check badge

### Trip semantics
- All `auto: true` conditions must be evaluated per run (except for theses with `status` ∈ {`orphaned`, `expired`, `invalidated`, `vindicated`} — those are frozen)
- **ANY** `auto: true` condition tripping → thesis status → `invalidated`, alert escalated to red
- The tripping condition is recorded in `outcome.invalidation_trigger`

### Allowed status transitions (enforced in `ThesisManager`)
```
active      → invalidated   (auto: any condition trips)
active      → vindicated    (manual: scripts/thesis.py mark --verdict vindicated)
active      → expired       (auto: review_date passes with no user action)
active      → orphaned      (auto: ticker no longer in portfolio)
orphaned    → invalidated   (manual: user clears via scripts/thesis.py mark)
orphaned    → vindicated    (manual: user clears via scripts/thesis.py mark)
```
All other transitions are invalid and rejected by `ThesisManager.set_status()`.

## 9. Email Changes

### New section: "Active Theses" (between Whale Activity and Positions)

```
🧠 Active Theses

  COIN — entered 2026-04-17 · conviction 7/10
  ┌─ THESIS ──────────────────────────────────────────────┐
  │ Bitcoin halving cycle bottom; COIN tracks BTC beta    │
  └───────────────────────────────────────────────────────┘
  Current: $199.83 · Stop: $140 → 43% buffer
  Invalidation progress:
    ● Price close < 140 for 5d       (not tripped, $59.83 to go)
    ● Weekly RSI < 30                (not tripped, RSI=52)
    ⚠ BTC fails cycle high by Q3     (manual check)

  ▼ Bear critique (from fresh session)
  "COIN revenue is 95% transaction volume; if BTC consolidates…"

  Review due: 2026-10-17 (183 days)
```

### New section: "Thesis Review Due" (only rendered when checkpoints due)

Shows theses with upcoming 30/90/180/review_date checkpoints. Links to `scripts/thesis.py review --id <id>` in body text.

### Behavior change: Stop-loss suppression

Positions with `status=active` thesis skip the existing `hard_stop_loss` and `approaching_stop_loss` alerts UNLESS an invalidation condition trips this run.

## 10. Edge Cases

| Case | Handling |
|---|---|
| `ANTHROPIC_API_KEY` missing | Week 1 features fully functional. Bear critique field left empty. Email notes "bear critique unavailable." |
| Claude API call fails (timeout, rate limit, 5xx) | Log error; critique field left empty; retry on next `scripts/thesis.py add` invocation. Never blocks primary email. |
| `theses.json` malformed / unreadable | Backup to `theses.json.corrupt-{timestamp}`, start empty, email flags error at top. |
| Thesis references a ticker no longer in portfolio | Auto-transition to `status=orphaned`, surface once in email, require manual clearing via `scripts/thesis.py mark`. |
| Narrative invalidation condition | Stored with `auto: false`, displayed with manual-check badge, never auto-trips. |
| Multiple active theses for same ticker | Allowed. All displayed. Stop-loss suppression active if ANY is active. |
| Thesis `review_date` passes with no user action | Auto-transition to `status=expired`, escalate to email alert, retain outcome field null. |
| `BearAgent` returns non-JSON or malformed response | Store raw text in `red_team_critique`, leave `unverified_claims` empty, log warning. |

## 11. Testing Plan

### Unit tests (`test_whale_watcher.py`)

- `ThesisManager.load()` from valid, missing, and corrupt JSON
- `ThesisManager.save()` atomic write + backup rotation
- `InvalidationEvaluator.evaluate()` — all operators + duration windows + technical LHS
- `ThesisManager.check_invalidation(thesis, market_data)` — returns tripped condition or None
- Status transition invariants (active → invalidated only; can't skip to vindicated without review)

### Mocked integration tests

- `BearAgent.critique()` with a stubbed Anthropic client returning a fixture response
- End-to-end: load portfolio → load thesis → evaluate → assert alert suppressed
- End-to-end: load portfolio → load thesis → invalidation tripped → assert alert escalated

### Side quest — pre-existing broken test

`test_whale_watcher.py` on current `main` calls `MarketAgent.generate_report()` which no longer exists. Fix this test (point it at `generate_json_data()` or remove it) so `run_test.yml` resumes protecting against regressions.

## 12. Secrets & Security

- New GitHub Actions secret: `ANTHROPIC_API_KEY` (week 2+)
- Never logged, never committed, only passed to `BearAgent` via `os.environ.get()`
- Budget guard: `BearAgent.critique()` only called at thesis creation (~$0.02–0.05 per call); never in the scheduled cron run. Estimated max monthly spend: $2 at 50 thesis creations/month (vastly higher than expected volume).

## 13. Success Criteria

- **Behavioral:** Within 7 days of shipping week 1, user records a thesis for COIN and MSFT; stop-loss alert spam drops to zero for those positions.
- **Discipline:** Within 30 days, user can name his bear critique's top concern for each active thesis unaided.
- **Calibration:** Within 6 months, `scripts/thesis.py report` shows a non-zero number of vindicated and invalidated theses, with documented lessons in `outcome.lesson`.

## 14. Open Questions

None. All design decisions resolved during brainstorming.

---

**Next step:** Implementation plan via `superpowers:writing-plans` skill.
