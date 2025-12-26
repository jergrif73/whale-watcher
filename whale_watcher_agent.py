import smtplib
import yfinance as yf
import pandas as pd
import os
import json
import csv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
is_manual_env = os.environ.get("IS_MANUAL_RUN", "false").lower()
IS_MANUAL = is_manual_env == "true"

EMAIL_SUBJECT_BASE = "Market Intelligence Report"

# --- FILE PATHS ---
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
DASHBOARD_JSON = DATA_DIR / "dashboard.json"
TRADE_JOURNAL_CSV = DATA_DIR / "trade_journal.csv"
PERFORMANCE_JSON = DATA_DIR / "performance.json"

# --- 💼 YOUR PORTFOLIO DASHBOARD ---
# STATUS: 0.00 = Not Owned (Watching Only)
# ACTION: Add entry price and purchase date when you buy.
# EXAMPLE: 'SMCI': {'entry': 45.50, 'date': '2024-11-15'},
MY_PORTFOLIO = {
    # --- STOCKS ---
    'SMCI': {'entry': 0.00, 'date': '2025-12-26'},
    'MARA': {'entry': 0.00, 'date': '2025-12-26'},
    'MSTR': {'entry': 0.00, 'date': '2025-12-26'},
    'COIN': {'entry': 0.00, 'date': '2025-12-26'},
    'TSLA': {'entry': 0.00, 'date': '2025-12-26'},
    'PLTR': {'entry': 0.00, 'date': '2025-12-26'},
    'NVDA': {'entry': 0.00, 'date': '2025-12-26'},
    'AMD':  {'entry': 0.00, 'date': '2025-12-26'},
    'AVGO': {'entry': 0.00, 'date': '2025-12-26'},
    'META': {'entry': 0.00, 'date': '2025-12-26'},
    'GOOGL': {'entry': 0.00, 'date': '2025-12-26'},
    'MSFT': {'entry': 0.00, 'date': '2025-12-26'},
    'SOXL': {'entry': 0.00, 'date': '2025-12-26'},
    'TQQQ': {'entry': 0.00, 'date': '2025-12-26'},
    'SPY':  {'entry': 0.00, 'date': '2025-12-26'},
    'QQQ':  {'entry': 0.00, 'date': '2025-12-26'},

    # --- CRYPTO ---
    'BTC':  {'entry': 0.00, 'date': '2025-12-26'},
    'ETH':  {'entry': 0.00, 'date': '2025-12-26'},
    'SOL':  {'entry': 0.00, 'date': '2025-12-26'},
    'FET':  {'entry': 0.00, 'date': '2025-12-26'},
    'RNDR': {'entry': 0.00, 'date': '2025-12-26'},
    'DOGE': {'entry': 0.00, 'date': '2025-12-26'},
    'PEPE': {'entry': 0.00, 'date': '2025-12-26'}
}

# --- POSITION SETTINGS ---
PROFIT_TARGET_PCT = 20.0      # Take profit at +20%
STOP_LOSS_PCT = -8.0          # Stop loss at -8%
LONG_TERM_DAYS = 365          # Days until long-term capital gains
TAX_WARNING_DAYS = 30         # Warn this many days before long-term threshold
SETTLING_PERIOD_DAYS = 3      # Don't panic on volatility during first N days

# --- THE WHALE LIST ---
WHALE_KEYWORDS = [
    "Public Investment Fund", "PIF", "Norges", "NBIM", 
    "Abu Dhabi Investment", "ADIA", "Mubadala", "Qatar Investment", "QIA",
    "Elliott", "Pershing Square", "Ackman", "Third Point", "Loeb", 
    "Icahn", "Trian", "Peltz", "Starboard",
    "Citadel", "Bridgewater", "Millennium", "Point72", "D. E. Shaw",
    "Berkshire", "Buffett", "BlackRock", "Vanguard"
]

STOCKS_TO_WATCH = [
    'MSTR', 'SMCI', 'COIN', 'TSLA', 'MARA', 'PLTR',
    'NVDA', 'AMD', 'AVGO', 'META', 'GOOGL', 'MSFT',
    'SOXL', 'TQQQ', 'SPY', 'QQQ'
]

CRYPTO_TO_WATCH = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'FET-USD', 
    'RNDR-USD', 'DOGE-USD', 'PEPE-USD'
]

# --- BENCHMARKS ---
BENCHMARKS = ['SPY', 'QQQ']


def is_owned(ticker):
    """Check if a ticker is owned (has valid entry data)."""
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None:
        return False
    if isinstance(position, dict):
        return position.get('entry', 0) > 0
    return position > 0


def get_position(ticker):
    """Get position details for an owned ticker."""
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None:
        return None
    if isinstance(position, dict):
        entry = position.get('entry', 0)
        date_str = position.get('date')
        if entry <= 0:
            return None
        entry_date = None
        if date_str:
            try:
                entry_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                pass
        return {'entry': entry, 'date': entry_date}
    if position > 0:
        return {'entry': position, 'date': None}
    return None


def calc_holding_days(entry_date):
    """Calculate days held from entry date."""
    if entry_date is None:
        return None
    return (datetime.now() - entry_date).days


def format_duration(days):
    """Format holding duration for display."""
    if days is None:
        return "—"
    if days == 0:
        return "Today"
    if days < 7:
        return f"{days}d"
    elif days < 30:
        weeks = days // 7
        return f"{weeks}w {days % 7}d"
    elif days < 365:
        months = days // 30
        return f"{months}mo"
    else:
        years = days // 365
        months = (days % 365) // 30
        return f"{years}y {months}mo"


def ensure_data_dir():
    """Create data directory if it doesn't exist."""
    DATA_DIR.mkdir(exist_ok=True)


def get_benchmark_performance(days=7):
    """Get benchmark performance over specified days."""
    benchmarks = {}
    for ticker in BENCHMARKS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1mo")
            if len(df) >= days:
                current = df['Close'].iloc[-1]
                past = df['Close'].iloc[-days] if days <= len(df) else df['Close'].iloc[0]
                pct = ((current - past) / past) * 100
                benchmarks[ticker] = {
                    'current': round(current, 2),
                    'change_pct': round(pct, 2),
                    'period_days': days
                }
        except Exception as e:
            print(f"   [ERROR] Benchmark {ticker}: {e}")
    return benchmarks


class TradeJournal:
    """Manages the trade journal CSV."""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self._ensure_file()
    
    def _ensure_file(self):
        """Create CSV with headers if it doesn't exist."""
        if not self.filepath.exists():
            with open(self.filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'ticker', 'action', 'price', 
                    'entry_price', 'gain_loss_pct', 'holding_days', 'notes'
                ])
    
    def log_signal(self, ticker, action, price, entry_price=None, 
                   gain_loss_pct=None, holding_days=None, notes=""):
        """Log a trading signal to the journal."""
        with open(self.filepath, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                ticker,
                action,
                price,
                entry_price or "",
                f"{gain_loss_pct:.1f}" if gain_loss_pct else "",
                holding_days or "",
                notes
            ])
    
    def get_recent_trades(self, limit=20):
        """Get recent trade log entries."""
        trades = []
        if self.filepath.exists():
            with open(self.filepath, 'r') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
        return trades[-limit:] if len(trades) > limit else trades


class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.has_critical_news = False
        self.portfolio_data = []
        self.watchlist_data = []
        self.benchmarks = {}
        ensure_data_dir()
        self.journal = TradeJournal(TRADE_JOURNAL_CSV)

    def check_whale_intel(self, ticker_obj, symbol):
        intel = []
        try:
            news_list = ticker_obj.news
            for story in news_list:
                title = story.get('title', '').lower()
                for whale in WHALE_KEYWORDS:
                    if whale.lower() in title:
                        intel.append(f"🐳 <b>{whale}</b> mentioned in news")
        except: pass

        if "-" not in symbol: 
            try:
                insiders = ticker_obj.insider_transactions
                if insiders is not None and not insiders.empty:
                    insiders = insiders.sort_index(ascending=False).head(3)
                    for idx, row in insiders.iterrows():
                        text = str(row.get('Text', '')).lower()
                        shares = row.get('Shares', 0)
                        if "purchase" in text:
                            intel.append(f"👔 <b>Insider Buy:</b> {shares} shares")
                            self.has_critical_news = True 
            except: pass
        return "<br>".join(list(set(intel))) 

    def fetch_data(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            if len(df) < 2: return None
            
            current_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            current_vol = df['Volume'].iloc[-1]
            
            # Historical prices for charts
            price_history = []
            for date, row in df.tail(30).iterrows():
                price_history.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'close': round(row['Close'], 2),
                    'volume': int(row['Volume'])
                })
            
            # Calculations
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else current_price
            trend = "UP" if current_price > sma_50 else "DOWN"
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            # Weekly change
            week_ago_price = df['Close'].iloc[-6] if len(df) >= 6 else df['Close'].iloc[0]
            weekly_change = ((current_price - week_ago_price) / week_ago_price) * 100
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            whale_intel = self.check_whale_intel(stock, ticker)
            
            # --- SIGNAL LOGIC ---
            signal = "NEUTRAL"
            color = "black"
            clean_ticker = ticker.replace("-USD", "")
            
            holding_days = None
            tax_note = ""
            
            # --- SCENARIO A: YOU OWN THIS STOCK (STRICT MODE) ---
            position = get_position(ticker)
            if position:
                entry_price = position['entry']
                entry_date = position['date']
                holding_days = calc_holding_days(entry_date)
                gain_loss_pct = ((current_price - entry_price) / entry_price) * 100
                
                annualized_return = None
                if holding_days is not None and holding_days > 0:
                    annualized_return = (gain_loss_pct / holding_days) * 365
                
                if holding_days is not None and holding_days > 0:
                    days_to_long_term = LONG_TERM_DAYS - holding_days
                    if days_to_long_term <= 0:
                        tax_note = "📗 LONG-TERM"
                    elif days_to_long_term <= TAX_WARNING_DAYS:
                        tax_note = f"⏳ {days_to_long_term}d to LT"
                
                duration_str = format_duration(holding_days) if holding_days is not None else "No date"
                print(f"   [OWNED] {clean_ticker}: Entry ${entry_price} | Curr ${round(current_price,2)} | P/L {round(gain_loss_pct,1)}% | Held {duration_str}")

                is_day_zero = holding_days is not None and holding_days == 0
                is_settling = holding_days is not None and 0 < holding_days <= SETTLING_PERIOD_DAYS
                
                if is_day_zero:
                    signal = "🆕 JUST BOUGHT"
                    color = "blue"
                elif gain_loss_pct >= PROFIT_TARGET_PCT:
                    signal = f"💰 SELL NOW (+{round(gain_loss_pct, 1)}%)"
                    color = "green"
                    self.has_critical_news = True
                    self.journal.log_signal(clean_ticker, "SELL_SIGNAL", round(current_price, 2),
                                           entry_price, gain_loss_pct, holding_days, "Profit target reached")
                elif gain_loss_pct <= STOP_LOSS_PCT:
                    if is_settling:
                        signal = f"⚠️ VOLATILE ({round(gain_loss_pct, 1)}%) - Settling"
                        color = "orange"
                    else:
                        signal = f"🛑 STOP LOSS ({round(gain_loss_pct, 1)}%)"
                        color = "red"
                        self.has_critical_news = True
                        self.journal.log_signal(clean_ticker, "STOP_LOSS_SIGNAL", round(current_price, 2),
                                               entry_price, gain_loss_pct, holding_days, "Stop loss triggered")
                else:
                    signal = f"💎 HOLDING ({round(gain_loss_pct, 1)}%)"
                    color = "blue"
                
                if tax_note:
                    signal = f"{signal} {tax_note}"

                return {
                    "symbol": clean_ticker,
                    "price": round(current_price, 2),
                    "entry_price": entry_price,
                    "trend": trend,
                    "rsi": current_rsi,
                    "signal": signal,
                    "color": color,
                    "whale_intel": whale_intel,
                    "holding_days": holding_days,
                    "gain_loss_pct": round(gain_loss_pct, 1),
                    "weekly_change": round(weekly_change, 2),
                    "vol_ratio": vol_ratio,
                    "price_history": price_history,
                    "is_owned": True
                }

            # --- SCENARIO B: WATCHING (FULL MARKET LOGIC) ---
            else:
                if abs(pct_change) > 10.0:
                    signal = f"🚨 BREAKING NEWS ({round(pct_change,1)}%)"
                    color = "purple"
                    self.has_critical_news = True
                    self.journal.log_signal(clean_ticker, "BREAKING_NEWS", round(current_price, 2),
                                           notes=f"{round(pct_change,1)}% daily move")
                elif vol_ratio > 3.5:
                    signal = f"🐳 WHALE ERUPTION ({vol_ratio}x Vol)"
                    color = "purple"
                    self.has_critical_news = True
                    self.journal.log_signal(clean_ticker, "WHALE_ACTIVITY", round(current_price, 2),
                                           notes=f"{vol_ratio}x volume")
                elif current_rsi > 85:
                    signal = "🔥 EXTREME OVERBOUGHT"
                    color = "red"
                elif current_rsi < 15:
                    signal = "🩸 EXTREME OVERSOLD"
                    color = "green"
                    self.has_critical_news = True
                elif vol_ratio > 1.5:
                    if trend == "UP": signal = "🚀 RALLY"; color = "green"
                    else: signal = "⚠️ PRESSURE"; color = "orange"
                elif current_rsi < 30: signal = "✅ BUY DIP"; color = "green"
                elif current_rsi > 70: signal = "💰 TAKE PROFIT"; color = "red"

            return {
                "symbol": clean_ticker,
                "price": round(current_price, 2),
                "trend": trend,
                "rsi": current_rsi,
                "signal": signal,
                "color": color,
                "whale_intel": whale_intel,
                "daily_change": round(pct_change, 2),
                "weekly_change": round(weekly_change, 2),
                "vol_ratio": vol_ratio,
                "price_history": price_history,
                "is_owned": False
            }
        except Exception as e:
            print(f"   [ERROR] {ticker}: {e}")
            return None

    def calculate_portfolio_summary(self):
        """Calculate overall portfolio performance."""
        if not self.portfolio_data:
            return None
        
        total_invested = 0
        total_current = 0
        
        for item in self.portfolio_data:
            if item.get('entry_price') and item.get('price'):
                total_invested += item['entry_price']
                total_current += item['price']
        
        if total_invested == 0:
            return None
        
        total_gain_loss = total_current - total_invested
        total_gain_loss_pct = ((total_current - total_invested) / total_invested) * 100
        
        return {
            'total_invested': round(total_invested, 2),
            'total_current': round(total_current, 2),
            'total_gain_loss': round(total_gain_loss, 2),
            'total_gain_loss_pct': round(total_gain_loss_pct, 2),
            'position_count': len(self.portfolio_data)
        }

    def export_dashboard_data(self):
        """Export data for the web dashboard."""
        summary = self.calculate_portfolio_summary()
        
        dashboard_data = {
            'generated_at': self.timestamp,
            'portfolio': self.portfolio_data,
            'watchlist': self.watchlist_data,
            'benchmarks': self.benchmarks,
            'summary': summary,
            'recent_signals': self.journal.get_recent_trades(10),
            'settings': {
                'profit_target': PROFIT_TARGET_PCT,
                'stop_loss': STOP_LOSS_PCT,
                'settling_days': SETTLING_PERIOD_DAYS
            }
        }
        
        with open(DASHBOARD_JSON, 'w') as f:
            json.dump(dashboard_data, f, indent=2)
        
        print(f"📊 Dashboard data exported to {DASHBOARD_JSON}")

    def generate_report(self):
        print("\n--- 🔍 PORTFOLIO CHECK ---")
        owned_count = 0
        for ticker, position in MY_PORTFOLIO.items():
            if is_owned(ticker):
                details = get_position(ticker)
                entry = details['entry']
                d_str = details['date'].strftime('%Y-%m-%d') if details['date'] else "Legacy"
                print(f"✅ TRACKING: {ticker} @ ${entry} (since {d_str})")
                owned_count += 1
        if owned_count == 0:
            print("❌ WARNING: Bot sees NO owned stocks. Did you save the file?")
        print("---------------------------\n")

        # Fetch benchmark data
        print("--- 📈 FETCHING BENCHMARKS ---")
        self.benchmarks = get_benchmark_performance(days=7)
        for ticker, data in self.benchmarks.items():
            print(f"   {ticker}: ${data['current']} ({data['change_pct']:+.2f}% / 7d)")
        print("---------------------------\n")

        html = f"""
        <html><body>
        <h2>{EMAIL_SUBJECT_BASE}: {self.timestamp}</h2>
        <hr>
        """
        
        # Benchmark summary
        if self.benchmarks:
            html += "<h3>📈 Market Benchmarks (7-Day)</h3><table border='1' cellpadding='5' cellspacing='0'><tr><th>Index</th><th>Price</th><th>7-Day Change</th></tr>"
            for ticker, data in self.benchmarks.items():
                color = "green" if data['change_pct'] >= 0 else "red"
                html += f"<tr><td><b>{ticker}</b></td><td>${data['current']}</td><td style='color:{color}'>{data['change_pct']:+.2f}%</td></tr>"
            html += "</table><hr>"

        html += """
        <h3>💰 Your Holdings (Position Tracker)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Asset</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Held</th>
            <th>P/L</th>
            <th>Week</th>
            <th>Action</th>
            <th>Intel</th>
        </tr>
        """
        
        # PORTFOLIO LOOP
        for ticker in MY_PORTFOLIO.keys():
            if not is_owned(ticker): continue
                
            yf_ticker = f"{ticker}-USD" if ticker in ['BTC','ETH','SOL','FET','RNDR','DOGE','PEPE'] else ticker
            data = self.fetch_data(yf_ticker)
            if data:
                self.portfolio_data.append(data)
                entry_display = f"${data.get('entry_price', '—')}"
                duration_display = format_duration(data.get('holding_days'))
                gain_loss = data.get('gain_loss_pct', 0)
                weekly = data.get('weekly_change', 0)
                gl_color = "green" if gain_loss >= 0 else "red"
                wk_color = "green" if weekly >= 0 else "red"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>{entry_display}</td>
                    <td>${data['price']}</td>
                    <td>{duration_display}</td>
                    <td style="color:{gl_color}">{gain_loss:+.1f}%</td>
                    <td style="color:{wk_color}">{weekly:+.1f}%</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                    <td style="font-size:12px">{data['whale_intel']}</td>
                </tr>"""

        # Portfolio summary
        summary = self.calculate_portfolio_summary()
        if summary:
            sum_color = "green" if summary['total_gain_loss_pct'] >= 0 else "red"
            html += f"""
            <tr style="background-color:#f0f0f0; font-weight:bold;">
                <td>TOTAL ({summary['position_count']} positions)</td>
                <td>${summary['total_invested']}</td>
                <td>${summary['total_current']}</td>
                <td colspan="2" style="color:{sum_color}">{summary['total_gain_loss_pct']:+.2f}% (${summary['total_gain_loss']:+.2f})</td>
                <td colspan="3"></td>
            </tr>"""

        html += """
        </table>
        <hr>
        <h3>⚡ Market Opportunities (Watchlist)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Trend</th><th>RSI</th><th>Day</th><th>Week</th><th>Signal</th><th>Whale Intel</th></tr>
        """
        
        # WATCHLIST LOOP
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            if is_owned(ticker): continue
            
            data = self.fetch_data(ticker)
            if data:
                self.watchlist_data.append(data)
                trend_icon = "📈" if data['trend'] == "UP" else "📉"
                daily = data.get('daily_change', 0)
                weekly = data.get('weekly_change', 0)
                d_color = "green" if daily >= 0 else "red"
                w_color = "green" if weekly >= 0 else "red"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{trend_icon}</td>
                    <td>{data['rsi']}</td>
                    <td style="color:{d_color}">{daily:+.1f}%</td>
                    <td style="color:{w_color}">{weekly:+.1f}%</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                    <td style="font-size:12px">{data['whale_intel']}</td>
                </tr>"""
                
        html += """
        </table>
        <hr>
        <p style="font-size:11px; color:gray;">
            <b>Portfolio Signals:</b> 
            🆕 Just Bought (Day 0) |
            💎 Holding |
            ⚠️ Volatile - Settling (Days 1-3) |
            💰 Sell Target (+20%) | 
            🛑 Stop Loss (-8%) |
            📗 Long-Term (365+ days) | 
            ⏳ Approaching Long-Term
            <br>
            <b>Watchlist Signals:</b>
            🚨 Breaking News (&gt;10% move) |
            🐳 Whale Eruption (&gt;3.5x vol) |
            🔥 Extreme Overbought (RSI &gt;85) |
            🩸 Extreme Oversold (RSI &lt;15) |
            🚀 Rally |
            ⚠️ Pressure |
            ✅ Buy Dip (RSI &lt;30) |
            💰 Take Profit (RSI &gt;70)
            <br>
            <b>Intel:</b>
            🐳 Whale in News |
            👔 Insider Buy
        </p>
        <p style="font-size:10px; color:#999;">
            <a href="https://jergrif73.github.io/whale-watcher/">View Live Dashboard</a>
        </p>
        </body></html>
        """
        
        # Export dashboard data
        self.export_dashboard_data()
        
        return html

    def generate_weekly_summary(self):
        """Generate a weekly performance summary (call on Sundays)."""
        summary = self.calculate_portfolio_summary()
        if not summary:
            return None
        
        html = f"""
        <html><body>
        <h2>📊 Weekly Performance Summary: {self.timestamp}</h2>
        <hr>
        <h3>Portfolio Overview</h3>
        <table border="1" cellpadding="10" cellspacing="0">
            <tr><td><b>Positions</b></td><td>{summary['position_count']}</td></tr>
            <tr><td><b>Total Invested</b></td><td>${summary['total_invested']}</td></tr>
            <tr><td><b>Current Value</b></td><td>${summary['total_current']}</td></tr>
            <tr><td><b>Total P/L</b></td><td style="color:{'green' if summary['total_gain_loss'] >= 0 else 'red'}">${summary['total_gain_loss']:+.2f} ({summary['total_gain_loss_pct']:+.2f}%)</td></tr>
        </table>
        <hr>
        <h3>vs Benchmarks (7-Day)</h3>
        <table border="1" cellpadding="10" cellspacing="0">
            <tr><th>Benchmark</th><th>7-Day Change</th><th>Your Portfolio</th><th>Alpha</th></tr>
        """
        
        for ticker, data in self.benchmarks.items():
            alpha = summary['total_gain_loss_pct'] - data['change_pct']
            alpha_color = "green" if alpha >= 0 else "red"
            html += f"""
            <tr>
                <td><b>{ticker}</b></td>
                <td>{data['change_pct']:+.2f}%</td>
                <td>{summary['total_gain_loss_pct']:+.2f}%</td>
                <td style="color:{alpha_color}">{alpha:+.2f}%</td>
            </tr>
            """
        
        html += """
        </table>
        <hr>
        <h3>Recent Activity</h3>
        <table border="1" cellpadding="5" cellspacing="0">
            <tr><th>Time</th><th>Ticker</th><th>Action</th><th>Price</th><th>Notes</th></tr>
        """
        
        for trade in self.journal.get_recent_trades(10):
            html += f"""
            <tr>
                <td style="font-size:11px">{trade['timestamp'][:16]}</td>
                <td><b>{trade['ticker']}</b></td>
                <td>{trade['action']}</td>
                <td>${trade['price']}</td>
                <td style="font-size:11px">{trade['notes']}</td>
            </tr>
            """
        
        html += "</table></body></html>"
        return html

    def send_email(self, html_report, subject_prefix=""):
        if not SENDER_EMAIL: return
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"{subject_prefix} {EMAIL_SUBJECT_BASE}: {self.timestamp}"
        msg.attach(MIMEText(html_report, 'html'))
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            print("📧 Email sent successfully.")
        except Exception as e:
            print(f"📧 Email failed: {e}")


if __name__ == "__main__":
    current_hour = datetime.utcnow().hour
    current_day = datetime.utcnow().weekday()  # 0=Monday, 6=Sunday
    
    is_routine_time = current_hour in [4, 16]  # 8 AM/PM EST
    is_weekly_summary_time = current_day == 6 and current_hour == 16  # Sunday 4 PM UTC
    
    agent = MarketAgent()
    report = agent.generate_report()
    
    if IS_MANUAL:
        print("🕹️ Manual Override.")
        agent.send_email(report, subject_prefix="🕹️ TEST:")
    elif is_weekly_summary_time:
        print("📊 Weekly Summary Time.")
        weekly = agent.generate_weekly_summary()
        if weekly:
            agent.send_email(weekly, subject_prefix="📊 WEEKLY:")
    elif agent.has_critical_news:
        print("🚨 CRITICAL UPDATE (Portfolio or Market).")
        agent.send_email(report, subject_prefix="🚨 ACTION REQ:")
    elif is_routine_time:
        print("⏰ Routine Schedule.")
        agent.send_email(report, subject_prefix="📊 DAILY:")
    else:
        print("💤 No news. Staying silent.")
