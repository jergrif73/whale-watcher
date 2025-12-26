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
# ACTION: Replace 0.00 with your buy price.
MY_PORTFOLIO = {
    # --- STOCKS ---
    'SMCI': 20.00,  # <--- DID YOU CHANGE THIS?
    'MARA': 50.00,  # <--- DID YOU CHANGE THIS?
    'MSTR': 0.00,
    'COIN': 0.00,
    'TSLA': 0.00,
    'PLTR': 0.00,
    'NVDA': 0.00,
    'AMD':  0.00,
    'AVGO': 0.00,
    'META': 0.00,
    'GOOGL': 0.00,
    'MSFT': 0.00,
    'SOXL': 0.00,
    'TQQQ': 0.00,
    'SPY':  0.00,
    'QQQ':  0.00,

    # --- CRYPTO ---
    'BTC':  0.00,
    'ETH':  0.00,
    'SOL':  0.00,
    'FET':  0.00,
    'RNDR': 0.00,
    'DOGE': 0.00,
    'PEPE': 0.00
}

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
            # Fetch minimal history for price check
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
            is_owned = clean_ticker in MY_PORTFOLIO and MY_PORTFOLIO[clean_ticker] > 0
            
            # --- SCENARIO A: YOU OWN THIS STOCK ---
            if is_owned:
                entry_price = MY_PORTFOLIO[clean_ticker]
                gain_loss_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Debug Print
                print(f"   [OWNED] {clean_ticker}: Entry ${entry_price} | Curr ${round(current_price,2)} | P/L {round(gain_loss_pct,1)}%")

                # Strict Profit/Loss Rules
                if gain_loss_pct >= 20.0:
                    signal = f"💰 SELL NOW (+{round(gain_loss_pct, 1)}%)"
                    color = "green"
                    self.has_critical_news = True
                elif gain_loss_pct <= -8.0:
                    signal = f"🛑 STOP LOSS ({round(gain_loss_pct, 1)}%)"
                    color = "red"
                    self.has_critical_news = True
                
                # Breaking News Exception
                elif abs(pct_change) > 10.0:
                    signal = f"🚨 NEWS ({round(pct_change,1)}%)"
                    color = "purple"
                    self.has_critical_news = True
                    
                # Otherwise JUST HOLD
                else:
                    signal = f"💎 HOLDING ({round(gain_loss_pct, 1)}%)"
                    color = "blue"

            # --- SCENARIO B: WATCHING ---
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
                "whale_intel": whale_intel
            }
        except Exception as e:
            return None

    def generate_report(self):
        print("\n--- 🔍 DIAGNOSTIC CHECK ---")
        owned_count = 0
        for k, v in MY_PORTFOLIO.items():
            if v > 0:
                print(f"✅ TRACKING: {k} at ${v}")
                owned_count += 1
        if owned_count == 0:
            print("❌ WARNING: No stocks are set to Owned (> 0.00). Check MY_PORTFOLIO values.")
        print("---------------------------\n")

        html = f"""
        <html><body>
        <h2>{EMAIL_SUBJECT_BASE}: {self.timestamp}</h2>
        <hr>
        
        <h3>💰 Your Holdings (Sell Watch)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Asset</th><th>Current Price</th><th>Action</th><th>Intel</th></tr>
        """
        
        for ticker, entry in MY_PORTFOLIO.items():
            if entry <= 0: continue 
            yf_ticker = f"{ticker}-USD" if ticker in ['BTC','ETH','SOL','FET','RNDR','DOGE','PEPE'] else ticker
            data = self.fetch_data(yf_ticker)
            if data:
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                    <td style="font-size:12px">{data['whale_intel']}</td>
                </tr>"""

        html += """
        </table>
        <hr>
        <h3>⚡ Market Opportunities</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Trend</th><th>Signal</th><th>Whale Intel</th></tr>
        """
        
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            if clean in MY_PORTFOLIO and MY_PORTFOLIO[clean] > 0: continue
            
            data = self.fetch_data(ticker)
            if data:
                trend_icon = "📈" if data['trend'] == "UP" else "📉"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{trend_icon}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                    <td style="font-size:12px">{data['whale_intel']}</td>
                </tr>"""
                
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
        except: pass

if __name__ == "__main__":
    current_hour = datetime.utcnow().hour
    is_routine_time = current_hour in [4, 16] 
    
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
