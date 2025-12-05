import smtplib
import yfinance as yf
import pandas as pd
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

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
        self.has_critical_news = False # The "Red Alert" flag

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
            
            # Calculate % Change for "Breaking News" detection
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # --- SIGNAL LOGIC ---
            signal = "NEUTRAL"
            color = "black"

            # 🚨 EMERGENCY LOGIC (Overrides everything)
            # Triggers if: Move > 10% OR Volume > 3.5x OR Extreme RSI
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
            
            # Normal Logic (Routine Only)
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
                "color": color
            }
        except Exception as e:
            return None

    def generate_report(self):
        html = f"""
        <html><body>
        <h2>⚡ Market Watcher: {self.timestamp}</h2>
        <hr>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Trend</th><th>RSI</th><th>Signal</th></tr>
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
                    <td>{data['rsi']}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                </tr>"""
        html += "</table></body></html>"
        return html

    def send_email(self, html_report, subject_prefix=""):
        if not SENDER_EMAIL: return
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
            print("Email Sent.")
        except Exception as e:
            print(e)

if __name__ == "__main__":
    # Check time (UTC). 16:00 UTC = 8 AM PST. 04:00 UTC = 8 PM PST.
    current_hour = datetime.utcnow().hour
    is_routine_time = current_hour in [4, 16] 
    
    agent = MarketAgent()
    report = agent.generate_report()
    
    # LOGIC GATE:
    # 1. If it's routine time -> Send Email
    # 2. If it's NOT routine, but Critical News exists -> Send Emergency Email
    # 3. Otherwise -> Stay Silent
    
    if agent.has_critical_news:
        print("🚨 CRITICAL NEWS DETECTED. Sending Emergency Alert.")
        agent.send_email(report, subject_prefix="🚨 URGENT:")
    elif is_routine_time:
        print("⏰ Routine Schedule. Sending Report.")
        agent.send_email(report, subject_prefix="📊 DAILY:")
    else:
        print("💤 No news and not report time. Staying silent.")
