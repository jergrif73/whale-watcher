import smtplib
import yfinance as yf
import pandas as pd
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
is_manual_env = os.environ.get("IS_MANUAL_RUN", "false").lower()
IS_MANUAL = is_manual_env == "true"

EMAIL_SUBJECT_BASE = "Market Intelligence Report"

# --- 💼 YOUR PORTFOLIO DASHBOARD ---
# STATUS: 0.00 = Not Owned (Watching Only)
# ACTION: Add entry price and purchase date when you buy.
# EXAMPLE: 'SMCI': {'entry': 45.50, 'date': '2024-11-15'},
MY_PORTFOLIO = {
    # --- STOCKS ---
    'SMCI': {'entry': 20.00, 'date': '2025-12-26'},
    'MARA': {'entry': 50.00, 'date': '2025-12-26'},
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


def is_owned(ticker):
    """Check if a ticker is owned (has valid entry data)."""
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None:
        return False
    if isinstance(position, dict):
        return position.get('entry', 0) > 0
    # Legacy support: bare number
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
    # Legacy support: bare number
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


class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.has_critical_news = False 

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
            
            # Calculations
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else current_price
            trend = "UP" if current_price > sma_50 else "DOWN"
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
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
            
            # Initialize position tracking fields
            holding_days = None
            tax_note = ""
            
            # --- SCENARIO A: YOU OWN THIS STOCK (STRICT MODE) ---
            position = get_position(ticker)
            if position:
                entry_price = position['entry']
                entry_date = position['date']
                holding_days = calc_holding_days(entry_date)
                gain_loss_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Calculate annualized return if we have dates
                annualized_return = None
                if holding_days is not None and holding_days > 0:
                    annualized_return = (gain_loss_pct / holding_days) * 365
                
                # Tax status check (only after day 0)
                if holding_days is not None and holding_days > 0:
                    days_to_long_term = LONG_TERM_DAYS - holding_days
                    if days_to_long_term <= 0:
                        tax_note = "📗 LONG-TERM"
                    elif days_to_long_term <= TAX_WARNING_DAYS:
                        tax_note = f"⏳ {days_to_long_term}d to LT"
                
                # Debug Print for Logs
                duration_str = format_duration(holding_days) if holding_days is not None else "No date"
                print(f"   [OWNED] {clean_ticker}: Entry ${entry_price} | Curr ${round(current_price,2)} | P/L {round(gain_loss_pct,1)}% | Held {duration_str}")

                # --- STRICT LOGIC WITH TIME AWARENESS ---
                # Day 0: No comparison - you just bought, stay neutral
                # Days 1-3: Track P/L but suppress stop-loss panic  
                # Day 4+: Full logic applies
                
                is_day_zero = holding_days is not None and holding_days == 0
                is_settling = holding_days is not None and 0 < holding_days <= SETTLING_PERIOD_DAYS
                
                if is_day_zero:
                    # Purchase day - no sell signals, just confirmation
                    signal = "🆕 JUST BOUGHT"
                    color = "blue"
                elif gain_loss_pct >= PROFIT_TARGET_PCT:
                    signal = f"💰 SELL NOW (+{round(gain_loss_pct, 1)}%)"
                    color = "green"
                    self.has_critical_news = True
                elif gain_loss_pct <= STOP_LOSS_PCT:
                    if is_settling:
                        # Don't trigger stop loss during settling period (days 1-3)
                        signal = f"⚠️ VOLATILE ({round(gain_loss_pct, 1)}%) - Settling"
                        color = "orange"
                    else:
                        signal = f"🛑 STOP LOSS ({round(gain_loss_pct, 1)}%)"
                        color = "red"
                        self.has_critical_news = True
                else:
                    signal = f"💎 HOLDING ({round(gain_loss_pct, 1)}%)"
                    color = "blue"
                
                # Append tax note to signal if present
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
                    "is_owned": True
                }

            # --- SCENARIO B: WATCHING (FULL MARKET LOGIC) ---
            else:
                if abs(pct_change) > 10.0:
                    signal = f"🚨 BREAKING NEWS ({round(pct_change,1)}%)"
                    color = "purple"
                    self.has_critical_news = True
                elif vol_ratio > 3.5:
                    signal = f"🐳 WHALE ERUPTION ({vol_ratio}x Vol)"
                    color = "purple"
                    self.has_critical_news = True
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
                "is_owned": False
            }
        except Exception as e:
            print(f"   [ERROR] {ticker}: {e}")
            return None

    def generate_report(self):
        # DIAGNOSTIC: Print what the bot thinks you own
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

        html = f"""
        <html><body>
        <h2>{EMAIL_SUBJECT_BASE}: {self.timestamp}</h2>
        <hr>
        
        <h3>💰 Your Holdings (Position Tracker)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Asset</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Held</th>
            <th>Action</th>
            <th>Intel</th>
        </tr>
        """
        
        # PORTFOLIO LOOP (Owned Items Only)
        for ticker in MY_PORTFOLIO.keys():
            if not is_owned(ticker): continue
                
            yf_ticker = f"{ticker}-USD" if ticker in ['BTC','ETH','SOL','FET','RNDR','DOGE','PEPE'] else ticker
            data = self.fetch_data(yf_ticker)
            if data:
                entry_display = f"${data.get('entry_price', '—')}"
                duration_display = format_duration(data.get('holding_days'))
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>{entry_display}</td>
                    <td>${data['price']}</td>
                    <td>{duration_display}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                    <td style="font-size:12px">{data['whale_intel']}</td>
                </tr>"""

        html += """
        </table>
        <hr>
        <h3>⚡ Market Opportunities (Watchlist)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Trend</th><th>RSI</th><th>Signal</th><th>Whale Intel</th></tr>
        """
        
        # WATCHLIST LOOP (Skip Owned Items)
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            # Skip items we already own
            if is_owned(ticker): continue
            
            data = self.fetch_data(ticker)
            if data:
                trend_icon = "📈" if data['trend'] == "UP" else "📉"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{trend_icon}</td>
                    <td>{data['rsi']}</td>
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
        </body></html>
        """
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
    is_routine_time = current_hour in [4, 16]  # 8 AM/PM EST (UTC offset)
    
    agent = MarketAgent()
    report = agent.generate_report()
    
    if IS_MANUAL:
        print("🕹️ Manual Override.")
        agent.send_email(report, subject_prefix="🕹️ TEST:")
    elif agent.has_critical_news:
        print("🚨 CRITICAL UPDATE (Portfolio or Market).")
        agent.send_email(report, subject_prefix="🚨 ACTION REQ:")
    elif is_routine_time:
        print("⏰ Routine Schedule.")
        agent.send_email(report, subject_prefix="📊 DAILY:")
    else:
        print("💤 No news. Staying silent.")
