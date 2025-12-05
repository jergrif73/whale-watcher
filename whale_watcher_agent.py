import smtplib
import yfinance as yf
import pandas as pd
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

# --- UNLIMITED WATCHLIST ---
STOCKS_TO_WATCH = [
    # Volatility Kings
    'MSTR', 'SMCI', 'COIN', 'TSLA', 'MARA', 'PLTR',
    # AI Leaders
    'NVDA', 'AMD', 'AVGO', 'META', 'GOOGL', 'MSFT',
    # ETFs
    'SOXL', 'TQQQ', 'SPY', 'QQQ'
]

# --- CRYPTO ---
# Format: Ticker-USD
CRYPTO_TO_WATCH = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'FET-USD', 
    'RNDR-USD', 'DOGE-USD', 'PEPE-USD'
]

class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_data(self, ticker):
        """Fetches data using yfinance (No API Key needed)"""
        try:
            # Download 3 months of data for trend analysis
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            
            if len(df) < 50: return None
            
            current_price = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            
            # --- CALCULATIONS ---
            # 1. Volume Ratio (vs 10-day average)
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            
            # 2. Trend (50-Day SMA)
            sma_50 = df['Close'].rolling(window=50).mean().iloc[-1]
            trend = "UP" if current_price > sma_50 else "DOWN"
            
            # 3. RSI (14-Day)
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # --- SIGNAL LOGIC ---
            signal = "NEUTRAL"
            color = "black"

            if vol_ratio > 1.5:
                if trend == "UP":
                    signal = "🚀 RALLY (Vol+Trend)"
                    color = "green"
                else:
                    signal = "⚠️ SELLING PRESSURE"
                    color = "orange"
            elif current_rsi < 30:
                if trend == "UP":
                    signal = "✅ BUY THE DIP"
                    color = "green"
                else:
                    signal = "✋ CATCHING KNIFE"
                    color = "red"
            elif current_rsi > 70:
                signal = "💰 OVERBOUGHT"
                color = "red"

            return {
                "symbol": ticker.replace("-USD", ""),
                "price": round(current_price, 2),
                "vol_ratio": vol_ratio,
                "trend": trend,
                "rsi": current_rsi,
                "signal": signal,
                "color": color
            }
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
            return None

    def generate_report(self):
        html = f"""
        <html><body>
        <h2>♾️ Unlimited Market Agent: {self.timestamp}</h2>
        <p><i>Powered by Yahoo Finance (No Limits)</i></p>
        <hr>
        <h3>⚡ Stocks & Crypto Trends</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Ticker</th>
            <th>Price</th>
            <th>Trend</th>
            <th>RSI</th>
            <th>Signal</th>
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
                    <td>{trend_icon} {data['trend']}</td>
                    <td>{data['rsi']}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                </tr>"""
            
        html += "</table><hr><p><i>Automated Strategy Agent</i></p></body></html>"
        return html

    def send_email(self, html_report):
        if not SENDER_EMAIL: return
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"🚀 MARKET INTELLIGENCE: {self.timestamp}"
        msg.attach(MIMEText(html_report, 'html'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
        except Exception as e:
            print(e)

if __name__ == "__main__":
    agent = MarketAgent()
    report = agent.generate_report()
    agent.send_email(report)
