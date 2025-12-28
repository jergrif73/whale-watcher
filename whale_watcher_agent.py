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

CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'FET', 'RNDR', 'DOGE', 'PEPE']

def is_owned(ticker):
    """Check if a ticker is owned (has valid entry data)."""
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None: return False
    if isinstance(position, dict): return position.get('entry', 0) > 0
    return position > 0

def get_position(ticker):
    """Get position details for an owned ticker."""
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None: return None
    if isinstance(position, dict):
        entry = position.get('entry', 0)
        date_str = position.get('date')
        if entry <= 0: return None
        entry_date = None
        if date_str:
            try:
                entry_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError: pass
        return {'entry': entry, 'date': entry_date}
    if position > 0: return {'entry': position, 'date': None}
    return None

def calc_holding_days(entry_date):
    if entry_date is None: return None
    return (datetime.now() - entry_date).days

def format_duration(days):
    if days is None: return "—"
    if days < 7: return f"{days}d"
    elif days < 30: return f"{days // 7}w {days % 7}d"
    elif days < 365: return f"{days // 30}mo"
    else: return f"{days // 365}y"

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
            
            holding_days = None
            tax_note = ""
            
            is_weekend_now = datetime.utcnow().weekday() >= 5 # 5=Sat, 6=Sun
            is_crypto_asset = clean_ticker in CRYPTO_SYMBOLS
            
            # --- SCENARIO A: YOU OWN THIS STOCK (STRICT MODE) ---
            position = get_position(ticker)
            if position:
                entry_price = position['entry']
                entry_date = position['date']
                holding_days = calc_holding_days(entry_date)
                gain_loss_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Tax check
                if holding_days is not None:
                    days_to_long_term = LONG_TERM_DAYS - holding_days
                    if days_to_long_term <= 0: tax_note = "📗 LONG-TERM"
                    elif days_to_long_term <= TAX_WARNING_DAYS: tax_note = f"⏳ {days_to_long_term}d to LT"
                
                # Debug Print
                duration_str = format_duration(holding_days) if holding_days is not None else "No date"
                print(f"   [OWNED] {clean_ticker}: Entry ${entry_price} | Curr ${round(current_price,2)} | P/L {round(gain_loss_pct,1)}% | Held {duration_str}")

                # --- WEEKEND SHIELD ---
                if is_weekend_now and not is_crypto_asset:
                    signal = f"⏸️ WEEKEND ({round(gain_loss_pct, 1)}%)"
                    color = "gray"
                else:
                    # --- OPERATING LOGIC ---
                    is_settling = holding_days is not None and holding_days <= SETTLING_PERIOD_DAYS
                    
                    if gain_loss_pct >= PROFIT_TARGET_PCT:
                        if is_settling:
                            signal = f"💰 FAST PROFIT (+{round(gain_loss_pct, 1)}%)"
                            color = "green"
                            self.has_critical_news = True
                        else:
                            signal = f"💰 SELL NOW (+{round(gain_loss_pct, 1)}%)"
                            color = "green"
                            self.has_critical_news = True
                            
                    elif gain_loss_pct <= STOP_LOSS_PCT:
                        if is_settling:
                            signal = f"⚠️ SETTLING ({round(gain_loss_pct, 1)}%)"
                            color = "orange"
                        else:
                            signal = f"🛑 STOP LOSS ({round(gain_loss_pct, 1)}%)"
                            color = "red"
                            self.has_critical_news = True
                    else:
                        status_label = "SETTLING" if is_settling else "HOLDING"
                        signal = f"💎 {status_label} ({round(gain_loss_pct, 1)}%)"
                        color = "blue"
                
                if tax_note: signal = f"{signal} {tax_note}"

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

            # --- SCENARIO B: WATCHING ---
            else:
                if is_weekend_now and not is_crypto_asset:
                    signal = "⏸️ WEEKEND"
                    color = "gray"
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
        print("\n--- 🔍 PORTFOLIO CHECK ---")
        owned_count = 0
        for ticker, position in MY_PORTFOLIO.items():
            if is_owned(ticker):
                details = get_position(ticker)
                entry = details['entry']
                print(f"✅ TRACKING: {ticker} @ ${entry}")
                owned_count += 1
        print("---------------------------\n")

        # HTML Header with Meta Tags for Mobile Responsiveness
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{EMAIL_SUBJECT_BASE}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #333; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ padding: 8px; border: 1px solid #ddd; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .green {{ color: green; font-weight: bold; }}
                .red {{ color: red; font-weight: bold; }}
                .blue {{ color: blue; font-weight: bold; }}
                .orange {{ color: orange; font-weight: bold; }}
                .purple {{ color: purple; font-weight: bold; }}
                .gray {{ color: gray; }}
            </style>
        </head>
        <body>
        <h2>{EMAIL_SUBJECT_BASE}: {self.timestamp}</h2>
        <hr>
        
        <h3>💰 Your Holdings (Position Tracker)</h3>
        <table>
        <tr>
            <th>Asset</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Held</th>
            <th>Action</th>
            <th>Intel</th>
        </tr>
        """
        
        for ticker in MY_PORTFOLIO.keys():
            if not is_owned(ticker): continue
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data(yf_ticker)
            if data:
                link = f"https://finance.yahoo.com/quote/{yf_ticker}"
                entry_display = f"${data.get('entry_price', '—')}"
                duration_display = format_duration(data.get('holding_days'))
                html += f"""
                <tr>
                    <td><b><a href="{link}" target="_blank" style="text-decoration:none; color:#0044CC;">{data['symbol']}</a></b></td>
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
        <table>
        <tr><th>Ticker</th><th>Price</th><th>Trend</th><th>RSI</th><th>Signal</th><th>Whale Intel</th></tr>
        """
        
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            if is_owned(ticker): continue
            
            data = self.fetch_data(ticker)
            if data:
                link = f"https://finance.yahoo.com/quote/{ticker}"
                trend_icon = "📈" if data['trend'] == "UP" else "📉"
                html += f"""
                <tr>
                    <td><b><a href="{link}" target="_blank" style="text-decoration:none; color:#0044CC;">{data['symbol']}</a></b></td>
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
            <b>Legend:</b> 
            💰 Sell Target (+20%) | 
            🛑 Stop Loss (-8%) | 
            💎 Holding | 
            ⚠️ Settling (First 3 Days) |
            ⏸️ Weekend (Market Closed)
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
    is_routine_time = current_hour in [4, 16] 
    
    agent = MarketAgent()
    report = agent.generate_report()
    
    # --- SAVE TO GITHUB PAGES ---
    try:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(report)
        print("✅ Report saved to index.html for Website")
    except Exception as e:
        print(f"❌ Failed to save report: {e}")

    # --- EMAIL LOGIC ---
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
