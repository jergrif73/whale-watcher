# 🐳 Whale Watcher

An automated market intelligence agent that tracks your portfolio, monitors whale activity, and provides actionable signals via email and a live web dashboard.

![Dashboard Preview](https://img.shields.io/badge/Status-Active-green) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

### 📊 Portfolio Tracking
- **Position Management** - Track entry prices, dates, and holding periods
- **P/L Calculations** - Real-time gain/loss percentages
- **Time-Aware Signals** - Day 0 protection, settling periods, tax status
- **Benchmark Comparison** - Compare your performance vs SPY/QQQ

### 🐳 Whale Detection
- **Volume Eruptions** - Alerts when volume exceeds 3.5x average
- **News Monitoring** - Scans for mentions of major institutions
- **Insider Activity** - Tracks insider purchases

### 📧 Smart Notifications
- **Critical Alerts** - Immediate emails for sell signals and stop losses
- **Daily Summaries** - Routine updates at 8 AM/PM
- **Weekly Reports** - Performance summaries every Sunday

### 🌐 Live Dashboard
- **GitHub Pages** - Free hosted dashboard
- **Real-Time Data** - Updates every hour
- **Mobile Friendly** - Responsive design

---

## Quick Start

### 1. Fork This Repository

Click the **Fork** button at the top right.

### 2. Enable GitHub Pages

1. Go to **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** / **docs** folder
4. Save

Your dashboard will be live at: `https://YOUR_USERNAME.github.io/whale-watcher/`

### 3. Add Secrets

Go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret | Description |
|--------|-------------|
| `SENDER_EMAIL` | Gmail address for the bot |
| `SENDER_PASSWORD` | [Google App Password](https://support.google.com/accounts/answer/185833) (16 chars) |
| `RECEIVER_EMAIL` | Your email to receive reports |

### 4. Configure Your Portfolio

Edit `whale_watcher_agent.py` and update `MY_PORTFOLIO`:

```python
MY_PORTFOLIO = {
    # When you BUY - add entry price and date:
    'NVDA': {'entry': 130.50, 'date': '2024-12-20'},
    'TSLA': {'entry': 425.00, 'date': '2024-12-15'},
    
    # Watching only (no position):
    'SMCI': {'entry': 0.00, 'date': '2025-12-26'},
    'MARA': {'entry': 0.00, 'date': '2025-12-26'},
}
```

### 5. Run Manually (Optional)

Go to **Actions** → **Whale Watcher Agent** → **Run workflow**

---

## File Structure

```
whale-watcher/
├── whale_watcher_agent.py    # Main agent script
├── data/
│   ├── dashboard.json        # Live data for web dashboard
│   └── trade_journal.csv     # Historical trade signals
├── docs/
│   └── index.html            # GitHub Pages dashboard
├── .github/
│   └── workflows/
│       └── whale_watcher.yml # GitHub Actions automation
└── README.md
```

---

## Signal Reference

### Portfolio Signals (Owned Positions)

| Signal | Condition | Action |
|--------|-----------|--------|
| 🆕 JUST BOUGHT | Day 0 | No signals, confirming purchase |
| 💎 HOLDING | Between thresholds | Stay the course |
| ⚠️ VOLATILE - Settling | -8% during days 1-3 | Monitor, don't panic |
| 💰 SELL NOW | +20% gain | Consider taking profit |
| 🛑 STOP LOSS | -8% (after day 3) | Consider cutting losses |
| 📗 LONG-TERM | Held 365+ days | Favorable tax treatment |
| ⏳ Xd to LT | Approaching 365 days | Consider holding for tax |

### Watchlist Signals

| Signal | Condition |
|--------|-----------|
| 🚨 BREAKING NEWS | >10% daily move |
| 🐳 WHALE ERUPTION | >3.5x average volume |
| 🔥 EXTREME OVERBOUGHT | RSI > 85 |
| 🩸 EXTREME OVERSOLD | RSI < 15 |
| 🚀 RALLY | Volume >1.5x + uptrend |
| ⚠️ PRESSURE | Volume >1.5x + downtrend |
| ✅ BUY DIP | RSI < 30 |
| 💰 TAKE PROFIT | RSI > 70 |
| NEUTRAL | Normal conditions |

---

## Configuration

### Position Settings

```python
PROFIT_TARGET_PCT = 20.0      # Sell signal threshold
STOP_LOSS_PCT = -8.0          # Stop loss threshold
LONG_TERM_DAYS = 365          # Long-term capital gains
TAX_WARNING_DAYS = 30         # Warn before LT threshold
SETTLING_PERIOD_DAYS = 3      # Suppress panic on days 1-3
```

### Whale Keywords

The agent monitors news for mentions of:
- Sovereign Wealth Funds (PIF, ADIA, Norges, etc.)
- Activist Investors (Elliott, Icahn, Ackman, etc.)
- Major Hedge Funds (Citadel, Bridgewater, etc.)
- Institutional Giants (Berkshire, BlackRock, Vanguard)

### Schedule

| Time (UTC) | Event |
|------------|-------|
| Every hour | Check for critical signals |
| 4:00, 16:00 | Send routine daily report |
| Sunday 16:00 | Send weekly summary |

---

## Trade Journal

All significant signals are logged to `data/trade_journal.csv`:

```csv
timestamp,ticker,action,price,entry_price,gain_loss_pct,holding_days,notes
2024-12-26T10:00:00,NVDA,SELL_SIGNAL,155.50,130.50,19.2,6,Profit target reached
2024-12-26T10:00:00,SMCI,WHALE_ACTIVITY,45.20,,,5.2x volume
```

---

## Customization

### Add New Tickers to Watchlist

```python
STOCKS_TO_WATCH = [
    'MSTR', 'SMCI', 'COIN', 'TSLA', 'MARA', 'PLTR',
    # Add your tickers here:
    'AAPL', 'AMZN', 'NFLX',
]

CRYPTO_TO_WATCH = [
    'BTC-USD', 'ETH-USD', 'SOL-USD',
    # Add crypto (must end in -USD):
    'XRP-USD', 'ADA-USD',
]
```

### Adjust Alert Thresholds

Edit the signal logic in `fetch_data()` method:

```python
# Example: Lower RSI oversold threshold
elif current_rsi < 20:  # Changed from 15
    signal = "🩸 EXTREME OVERSOLD"
```

---

## Troubleshooting

### Emails Not Sending

1. Verify secrets are set correctly in GitHub
2. Ensure you're using a Google App Password, not your regular password
3. Check the Actions log for error messages

### Dashboard Not Updating

1. Verify GitHub Pages is enabled
2. Check that the workflow completed successfully
3. Data updates every hour on schedule

### No Portfolio Data

1. Ensure at least one ticker has `entry > 0`
2. Check that the date format is `YYYY-MM-DD`
3. Run the workflow manually to see debug output

---

## License

MIT License - feel free to modify and use for personal trading.

---

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research before making investment decisions. Past performance does not guarantee future results.

---

**Built with 🐍 Python, ⚡ GitHub Actions, and ☕ caffeine**
