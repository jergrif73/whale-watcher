import smtplib
import requests
import time
import statistics
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION ---
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

COINGECKO_URL = "https://api.coingecko.com/api/v3"

# --- HIGH VOLATILITY WATCHLIST (12 Stocks) ---
STOCKS_TO_WATCH = [
    'MSTR', 'SMCI', 'COIN', 'TSLA', 'MARA', 'PLTR', 
    'NVDA', 'AMD', 'AVGO', 'META', 'SOXL', 'TQQQ'
]

# --- CRYPTO ---
CRYPTO_IDS = [
    'bitcoin', 'ethereum', 'solana', 'fetch-ai', 
    'render-token', 'bittensor', 'pepe', 'dogecoin'
]

class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def calculate_rsi(self, prices, period=14):
        """Calculates the Relative Strength Index (RSI)"""
        if len(prices) < period + 1:
            return 50 # Not enough data
        
        deltas = [prices[i] - prices[i+1] for i in range(len(prices)-1)]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [abs(d) if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0: return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)

    def fetch_stock_whale_activity(self, symbol):
        if not ALPHA_VANTAGE_KEY: return None
        # Get 100 days of data for Trend Analysis
        url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}'
        
        try:
            response = requests.get(url)
            data = response.json()
            if "Time Series (Daily)" not in data: return None

            dates = list(data["Time Series (Daily)"].keys())
            if len(dates) < 50: return None # Need 50 days for trend

            # Parse Data
            today_data = data["Time Series (Daily)"][dates[0]]
            price = float(today_data['4. close'])
            vol = int(today_data['5. volume'])
            
            # History for calcs
            past_closes = [float(data["Time Series (Daily)"][d]['4. close']) for d in dates]
            past_vols = [int(data["Time Series (Daily)"][d]['5. volume']) for d in dates[1:11]]
            
            # --- CALCULATIONS ---
            # 1. Volume Ratio
            avg_vol = statistics.mean(past_vols)
            vol_ratio = round(vol / avg_vol, 2)
            
            # 2. Trend (50-Day SMA)
            sma_50 = statistics.mean(past_closes[:50])
            trend = "UP" if price > sma_50 else "DOWN"
            
            # 3. RSI (14-Day Momentum)
            rsi = self.calculate_rsi(past_closes)
            
            # --- SIGNAL LOGIC ---
            signal = "NEUTRAL"
            color = "black"

            # Context-Aware Signals
            if vol_ratio > 1.5:
                if trend == "UP":
                    signal = "🚀 RALLY (Vol+Trend)"
                    color = "green"
                else:
                    signal = "⚠️ SELLING PRESSURE"
                    color = "orange"
            
            elif rsi < 30:
                if trend == "UP":
                    signal = "✅ BUY THE DIP (Oversold)"
                    color = "green"
                else:
                    signal = "✋ CATCHING KNIFE (Be Careful)"
                    color = "red"
            
            elif rsi > 70:
                signal = "💰 OVERBOUGHT (Take Profit)"
                color = "red"

            return {
                "symbol": symbol,
                "price": price,
                "vol_ratio": vol_ratio,
                "trend": trend,
                "rsi": rsi,
                "signal": signal,
                "color": color
            }
        except Exception as e:
            self.log(f"Error {symbol}: {e}")
            return None

    def fetch_crypto_whale_activity(self, coin_id):
        url = f"{COINGECKO_URL}/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true"
        try:
            response = requests.get(url)
            if response.status_code != 200: return None
            data = response.json().get(coin_id)
            if not data: return None
            
            price = data['usd']
            change = data['usd_24h_change']
            
            # Basic Trend Logic for Crypto (since no history)
            signal = "HOLD"
            color = "black"
            
            if change > 10: 
                signal = "🚀 MOONSHOT"
                color = "green"
            elif change < -8: 
                signal = "🩸 DIP ALERT"
                color = "red"

            return {
                "symbol": coin_id.upper(),
                "price": price,
                "change": round(change, 2),
                "signal": signal,
                "color": color
            }
        except Exception as e: return None

    def generate_report(self):
        html = f"""
        <html><body>
        <h2>🧠 Smart-Trend Market Report: {self.timestamp}</h2>
        <p><i>Analysis: Volume + 50-Day Trend + RSI Momentum</i></p>
        <hr>
        <h3>📊 Stock Trends</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr>
            <th>Ticker</th>
            <th>Price</th>
            <th>Trend</th>
            <th>RSI</th>
            <th>Signal</th>
        </tr>
        """
        
        for stock in STOCKS_TO_WATCH:
            data = self.fetch_stock_whale_activity(stock)
            if data:
                # Add arrow to trend
                trend_icon = "📈" if data['trend'] == "UP" else "📉"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{trend_icon} {data['trend']}</td>
                    <td>{data['rsi']}</td>
                    <td style="color:{data['color']}"><b>{data['signal']}</b></td>
                </tr>"""
            time.sleep(12) 
            
        html += "</table><h3>🪙 Crypto Quick-Scan</h3><ul>"
        
        for coin in CRYPTO_IDS:
            data = self.fetch_crypto_whale_activity(coin)
            if data:
                html += f"<li><b>{data['symbol']}</b>: ${data['price']} ({data['change']}%) - <span style='color:{data['color']}'><b>{data['signal']}</b></span></li>"
            time.sleep(2)
            
        html += "</ul><hr><p><i>Trend is your friend.</i></p></body></html>"
        return html

    def send_email(self, html_report):
        if not SENDER_EMAIL: return
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"📈 TREND ALERT: {self.timestamp}"
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
