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
# Manual Override Check
is_manual_env = os.environ.get("IS_MANUAL_RUN", "false").lower()
IS_MANUAL = is_manual_env == "true"

# --- THE WHALE LIST ---
# The agent scans news headlines for these specific names
WHALE_KEYWORDS = [
    # Sovereign Wealth Funds
    "Public Investment Fund", "PIF", "Norges", "NBIM", 
    "Abu Dhabi Investment", "ADIA", "Mubadala", "Qatar Investment", "QIA",
    # Activist Investors
    "Elliott", "Pershing Square", "Ackman", "Third Point", "Loeb", 
    "Icahn", "Trian", "Peltz", "Starboard",
    # Hedge Fund Whales
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
        """Scans for Specific Whale Names and Insider Buying"""
        intel = []
        
        # 1. SCAN NEWS FOR WHALE NAMES
        try:
            news_list = ticker_obj.news
            for story in news_list:
                title = story.get('title', '').lower()
                # Check recent stories only (last 24h logic implies top of feed)
                for whale in WHALE_KEYWORDS:
                    if whale.lower() in title:
                        intel.append(f"🐳 <b>{whale}</b> mentioned in news")
        except: pass

        # 2. SCAN FOR CORPORATE INSIDERS (Stocks Only)
        if "-" not in symbol: # Skip crypto
            try:
                # Get insider transactions
                insiders = ticker_obj.insider_transactions
                if insiders is not None and not insiders.empty:
                    # Sort by date
                    insiders = insiders.sort_index(ascending=False)
                    # Look at top 3 recent transactions
                    recent = insiders.head(3)
                    for idx, row in recent.iterrows():
                        # Parse the text description for "Purchase"
                        # Note: yfinance format varies, checking Text column usually works
                        text = str(row.get('Text', '')).lower()
                        shares = row.get('Shares', 0)
                        
                        # Logic: Look for "Purchase" and verify it's recent (simulated by top of list)
                        if "purchase" in text:
                            # Clean up the output
                            intel.append(f"👔 <b>Insider Buy:</b> {shares} shares")
                            self.has_critical_news = True # Flag this as important!
            except: pass
            
        return "<br>".join(list(set(intel))) # Remove duplicates

    def fetch_data(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            if len(df) < 50: return None
            
            current_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            current_vol = df['Volume'].iloc[-1]
            
            # --- CALCULATIONS ---
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            
            sma_50 = df['Close'].rolling(window=50).mean().iloc[-1]
            trend = "UP" if current_price > sma_50 else "DOWN"
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # WHALE CHECK
            whale_intel = self.check_whale_intel(stock, ticker)
            
            # --- SIGNAL LOGIC ---
            signal = "NEUTRAL"
            color = "black"

            if abs(pct_change) > 10.0:
                signal = f"🚨 BREAKING NEWS ({round(pct_change,1)}%)"
                color = "purple"
                self.has_critical_news = True
            elif vol_ratio > 3.5:
                signal = "🐳 WHALE ERUPTION (3.5x Vol)"
                color = "purple"
                self.has_critical_news = True
            elif current_rsi > 85:
                signal = "🔥 EXTREME OVERBOUGHT"
                color = "red"
                self.has_critical_news = True
            elif current_rsi < 15:
                signal = "🩸 EXTREME OVERSOLD"
                color = "green"
                self.has_critical_news = True
            elif vol_ratio > 1.5:
                if trend == "UP":
                    signal = "🚀 RALLY"
                    color = "green"
                else:
                    signal = "⚠️ PRESSURE"
                    color = "orange"
            elif current_rsi < 30:
                signal = "✅ BUY DIP"
                color = "green"
            elif current_rsi > 70:
                signal = "💰 TAKE PROFIT"
                color = "red"

            return {
                "symbol": ticker.replace("-USD", ""),
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
        html = f"""
        <html><body>
        <h2>🐋 Whale & Insider Watcher: {self.timestamp}</h2>
        <hr>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Ticker</th>
            <th>Price</th>
            <th>Trend</th>
            <th>Signal</th>
            <th>Whale Intel 🐳</th>
        </tr>
        """
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
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
        if not SENDER_EMAIL: 
            print("❌ Error: No Sender Email found.")
            return
        
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"{subject_prefix} MARKET ALERT: {self.timestamp}"
        msg.attach(MIMEText(html_report, 'html'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            print("✅ Email Sent Successfully.")
        except Exception as e:
            print(f"❌ Email Failed: {e}")

if __name__ == "__main__":
    current_hour = datetime.utcnow().hour
    is_routine_time = current_hour in [4, 16] 
    
    print("🤖 Agent Starting...")
    agent = MarketAgent()
    report = agent.generate_report()
    
    if IS_MANUAL:
        print("🕹️ Manual Override Detected. Sending Test Email.")
        agent.send_email(report, subject_prefix="🕹️ TEST:")
    elif agent.has_critical_news:
        print("🚨 CRITICAL NEWS DETECTED. Sending Emergency Alert.")
        agent.send_email(report, subject_prefix="🚨 URGENT:")
    elif is_routine_time:
        print("⏰ Routine Schedule. Sending Report.")
        agent.send_email(report, subject_prefix="📊 DAILY:")
    else:
        print("💤 No news and not report time. Staying silent.")
