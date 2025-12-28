import smtplib
import yfinance as yf
import pandas as pd
import os
import json
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

# --- 💼 YOUR PORTFOLIO ---
MY_PORTFOLIO = {
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
    'BTC':  {'entry': 0.00, 'date': '2025-12-26'},
    'ETH':  {'entry': 0.00, 'date': '2025-12-26'},
    'SOL':  {'entry': 0.00, 'date': '2025-12-26'},
    'FET':  {'entry': 0.00, 'date': '2025-12-26'},
    'RNDR': {'entry': 0.00, 'date': '2025-12-26'},
    'DOGE': {'entry': 0.00, 'date': '2025-12-26'},
    'PEPE': {'entry': 0.00, 'date': '2025-12-26'}
}

# --- SETTINGS ---
PROFIT_TARGET_PCT = 20.0
STOP_LOSS_PCT = -8.0
LONG_TERM_DAYS = 365
TAX_WARNING_DAYS = 30
SETTLING_PERIOD_DAYS = 3

WHALE_KEYWORDS = [
    "Public Investment Fund", "PIF", "Norges", "NBIM", "Abu Dhabi Investment", "ADIA", 
    "Mubadala", "Qatar Investment", "QIA", "Elliott", "Pershing Square", "Ackman", 
    "Third Point", "Loeb", "Icahn", "Trian", "Peltz", "Starboard", "Citadel", 
    "Bridgewater", "Millennium", "Point72", "D. E. Shaw", "Berkshire", "Buffett", 
    "BlackRock", "Vanguard"
]

STOCKS_TO_WATCH = ['MSTR', 'SMCI', 'COIN', 'TSLA', 'MARA', 'PLTR', 'NVDA', 'AMD', 'AVGO', 'META', 'GOOGL', 'MSFT', 'SOXL', 'TQQQ', 'SPY', 'QQQ']
CRYPTO_TO_WATCH = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'FET-USD', 'RNDR-USD', 'DOGE-USD', 'PEPE-USD']
CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'FET', 'RNDR', 'DOGE', 'PEPE']

def is_owned(ticker):
    clean = ticker.replace("-USD", "")
    position = MY_PORTFOLIO.get(clean)
    if position is None: return False
    if isinstance(position, dict): return position.get('entry', 0) > 0
    return position > 0

def get_position(ticker):
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
                        intel.append(f"🐳 {whale}")
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
                            intel.append(f"👔 Insider Buy: {shares}")
                            self.has_critical_news = True 
            except: pass
        return " | ".join(list(set(intel))) 

    def fetch_data(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            if len(df) < 2: return None
            
            current_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            current_vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else current_price
            trend = "UP" if current_price > sma_50 else "DOWN"
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            whale_intel = self.check_whale_intel(stock, ticker)
            clean_ticker = ticker.replace("-USD", "")
            
            holding_days = None
            gain_loss_pct = 0.0
            entry_price = 0.0
            is_weekend_now = datetime.utcnow().weekday() >= 5
            is_crypto_asset = clean_ticker in CRYPTO_SYMBOLS
            
            signal = "NEUTRAL"
            color = "black"

            position = get_position(ticker)
            is_owned_asset = position is not None

            if is_owned_asset:
                entry_price = position['entry']
                entry_date = position['date']
                holding_days = calc_holding_days(entry_date)
                gain_loss_pct = ((current_price - entry_price) / entry_price) * 100
                print(f"   [OWNED] {clean_ticker}: P/L {round(gain_loss_pct,1)}%")

                if is_weekend_now and not is_crypto_asset:
                    signal = "⏸️ WEEKEND"
                    color = "gray"
                else:
                    is_settling = holding_days is not None and holding_days <= SETTLING_PERIOD_DAYS
                    if gain_loss_pct >= PROFIT_TARGET_PCT:
                        signal = "💰 FAST PROFIT" if is_settling else "💰 SELL NOW"
                        color = "green"
                        self.has_critical_news = True
                    elif gain_loss_pct <= STOP_LOSS_PCT:
                        signal = "⚠️ SETTLING" if is_settling else "🛑 STOP LOSS"
                        color = "orange" if is_settling else "red"
                        if not is_settling: self.has_critical_news = True
                    else:
                        signal = "💎 HOLDING"
                        color = "blue"
            else:
                if is_weekend_now and not is_crypto_asset:
                    signal = "⏸️ WEEKEND"
                    color = "gray"
                else:
                    if abs(pct_change) > 10.0:
                        signal = f"🚨 NEWS ({round(pct_change,1)}%)"
                        color = "purple"
                        self.has_critical_news = True
                    elif vol_ratio > 3.5:
                        signal = f"🐳 WHALE"
                        color = "purple"
                        self.has_critical_news = True
                    elif current_rsi > 85:
                        signal = "🔥 DANGER"
                        color = "red"
                    elif current_rsi < 30:
                        signal = "✅ BUY DIP"
                        color = "green"
                    elif current_rsi > 70:
                        signal = "💰 TAKE PROFIT"
                        color = "red"

            return {
                "symbol": clean_ticker,
                "yf_symbol": ticker,
                "price": round(current_price, 2),
                "entry_price": entry_price,
                "trend": trend,
                "rsi": current_rsi,
                "signal": signal,
                "color": color,
                "whale_intel": whale_intel,
                "holding_days": holding_days,
                "gain_loss_pct": round(gain_loss_pct, 1),
                "daily_change": round(pct_change, 1)
            }
        except Exception as e:
            return None

    def generate_json_data(self):
        # Generate clean JSON data for the dashboard
        portfolio_data = []
        watchlist_data = []
        
        print("\n--- 📊 GENERATING DATA ---")
        
        # Portfolio
        for ticker in MY_PORTFOLIO.keys():
            if not is_owned(ticker): continue
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data(yf_ticker)
            if data: portfolio_data.append(data)

        # Watchlist
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            if is_owned(ticker): continue
            data = self.fetch_data(ticker)
            if data: watchlist_data.append(data)
            
        return {
            "generated_at": self.timestamp,
            "portfolio": portfolio_data,
            "watchlist": watchlist_data,
            "settings": {
                "profit_target": PROFIT_TARGET_PCT,
                "stop_loss": STOP_LOSS_PCT
            }
        }

    def generate_dashboard_html(self, data):
        # --- SERVER SIDE RENDERING FOR EMAIL SUPPORT ---
        
        def build_rows(items, is_portfolio):
            html_rows = ""
            for item in items:
                # Styles for Email Compatibility (Inline styles are safest)
                color_style = f"color: {item['color']}; border: 1px solid {item['color']}; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block;"
                
                # Determine colors for metrics
                pl_color = "#3fb950" if item['gain_loss_pct'] >= 0 else "#f85149" # green / red
                trend_color = "#3fb950" if item['trend'] == 'UP' else "#f85149"
                
                link_style = "color: #388bfd; text-decoration: none; font-weight: bold;"
                
                row = "<tr>"
                # Ticker & Link
                row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;"><a href="https://finance.yahoo.com/quote/{item["yf_symbol"]}" style="{link_style}" target="_blank">{item["symbol"]}</a></td>'
                
                if is_portfolio:
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;">${item["entry_price"]}</td>'
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;">${item["price"]}</td>'
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d; color: {pl_color};">{item["gain_loss_pct"]}%</td>'
                else:
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;">${item["price"]}</td>'
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d; color: {trend_color};">{item["trend"]}</td>'
                    row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;">{item["rsi"]}</td>'
                
                # Signal
                row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d;"><span style="{color_style}">{item["signal"]}</span></td>'
                # Intel
                row += f'<td style="padding: 12px; border-bottom: 1px solid #30363d; font-size: 12px; color: #8b949e;">{item["whale_intel"]}</td>'
                row += "</tr>"
                html_rows += row
            return html_rows

        portfolio_html = build_rows(data['portfolio'], True)
        watchlist_html = build_rows(data['watchlist'], False)

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>🐳 Whale Watcher Dashboard</title>
            <style>
                /* Base Styles for Browser View */
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; background-color: #0d1117; color: #e6edf3; padding: 20px; margin: 0; }}
                .container {{ max-width: 1200px; margin: 0 auto; background-color: #0d1117; }}
                h1 {{ color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
                h3 {{ color: #e6edf3; margin-top: 30px; border-bottom: 1px solid #30363d; padding-bottom: 5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; color: #e6edf3; }}
                th {{ text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase; }}
                td {{ padding: 12px; border-bottom: 1px solid #30363d; }}
                a {{ color: #388bfd; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body style="background-color: #0d1117; color: #e6edf3; font-family: sans-serif;">
            <div class="container">
                <header>
                    <h1 style="color: #e6edf3;">🐳 Whale Watcher</h1>
                    <div style="color: #8b949e; font-size: 14px;">Last Updated: {data['generated_at']}</div>
                </header>

                <h3 style="color: #e6edf3; border-bottom: 1px solid #30363d;">💰 Your Holdings</h3>
                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; color: #e6edf3;">
                    <thead>
                        <tr>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Asset</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Entry</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Current</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">P/L</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Signal</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Intel</th>
                        </tr>
                    </thead>
                    <tbody>
                        {portfolio_html}
                    </tbody>
                </table>

                <h3 style="color: #e6edf3; border-bottom: 1px solid #30363d; margin-top: 30px;">⚡ Watchlist</h3>
                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; color: #e6edf3;">
                    <thead>
                        <tr>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Ticker</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Price</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Trend</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">RSI</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Signal</th>
                            <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e;">Intel</th>
                        </tr>
                    </thead>
                    <tbody>
                        {watchlist_html}
                    </tbody>
                </table>
                
                <p style="margin-top: 40px; color: #8b949e; font-size: 12px;">
                    Generated by Whale Watcher Agent. <br>
                    Markets are volatile. DYOR.
                </p>
            </div>
        </body>
        </html>
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
            print("📧 Email sent.")
        except Exception as e: pass

if __name__ == "__main__":
    current_hour = datetime.utcnow().hour
    is_routine_time = current_hour in [4, 16] 
    
    agent = MarketAgent()
    
    # 1. Generate Data
    data = agent.generate_json_data()
    
    # 2. Generate Dashboard HTML (Now using Python Server-Side Rendering)
    dashboard_html = agent.generate_dashboard_html(data)
    
    # 3. Save to Website
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    print("✅ Dashboard generated.")

    # 4. Email Logic
    if IS_MANUAL:
        print("🕹️ Manual Override.")
        agent.send_email(dashboard_html, subject_prefix="🕹️ TEST:")
    elif agent.has_critical_news:
        print("🚨 CRITICAL UPDATE.")
        agent.send_email(dashboard_html, subject_prefix="🚨 ACTION REQ:")
    elif is_routine_time:
        print("⏰ Routine Schedule.")
        agent.send_email(dashboard_html, subject_prefix="📊 DAILY:")
    else:
        print("💤 No news. Staying silent.")
