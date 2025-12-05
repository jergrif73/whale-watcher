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
# We track 12 stocks. Run 2x daily = 24 calls (Limit 25).
STOCKS_TO_WATCH = [
    # --- The "High Octane" Volatility Kings ---
    'MSTR',  # Bitcoin Proxy (Extremely Volatile)
    'SMCI',  # AI Servers (Wild Swings)
    'COIN',  # Crypto Exchange
    'TSLA',  # Retail Favorite
    'MARA',  # Bitcoin Miner
    'PLTR',  # AI Defense / Meme Strength
    
    # --- The AI Leaders (Must Watch) ---
    'NVDA',  # The Market Mover
    'AMD',   # Chip Volatility
    'AVGO',  # AI Networking
    'META',  # Big Tech High Beta
    
    # --- Leveraged ETFs (3x Moves) ---
    'SOXL',  # 3x Bull Semiconductor
    'TQQQ'   # 3x Bull Tech
]

# --- CRYPTO (Unlimited Free Checks) ---
CRYPTO_IDS = [
    'bitcoin',
    'ethereum',
    'solana',
    'fetch-ai',
    'render-token',
    'bittensor',
    'pepe',        # Meme Coin Volatility
    'dogecoin'     # Meme Coin Volatility
]

class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def fetch_stock_whale_activity(self, symbol):
        if not ALPHA_VANTAGE_KEY:
            return None
            
        url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}'
        try:
            response = requests.get(url)
            data = response.json()
            
            if "Time Series (Daily)" not in data:
                return None

            dates = list(data["Time Series (Daily)"].keys())
            today = dates[0]
            
            today_data = data["Time Series (Daily)"][today]
            today_vol = int(today_data['5. volume'])
            today_close = float(today_data['4. close'])
            
            # Calculate 10-day average volume
            past_vols = [int(data["Time Series (Daily)"][d]['5. volume']) for d in dates[1:11]]
            avg_vol = statistics.mean(past_vols)
            
            volume_ratio = today_vol / avg_vol
            
            # Dynamic Signals for Volatile Stocks
            signal = "NEUTRAL"
            if volume_ratio > 2.0:
                signal = "🚀 WHALE ERUPTION"
            elif volume_ratio > 1.5:
                signal = "WHALE ACTIVE"
            elif volume_ratio < 0.6:
                signal = "LOW VOL (Ignore)"

            return {
                "symbol": symbol,
                "price": today_close,
                "ratio": round(volume_ratio, 2),
                "signal": signal
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
            change_24h = data['usd_24h_change']
            
            signal = "HOLD"
            # Volatility Thresholds
            if change_24h > 10.0:
                signal = "🚀 MOONSHOT ALERT"
            elif change_24h > 5.0:
                signal = "PUMP WATCH"
            elif change_24h < -10.0:
                signal = "🩸 CRASH DIP BUY"
            elif change_24h < -5.0:
                signal = "DIP BUY WATCH"

            return {
                "symbol": coin_id.upper(),
                "price": price,
                "change": round(change_24h, 2),
                "signal": signal
            }
        except Exception as e:
            self.log(f"Error {coin_id}: {e}")
            return None

    def generate_report(self):
        html = f"""
        <html><body>
        <h2>🔥 High Voltage Market Report: {self.timestamp}</h2>
        <p><i>Tracking the most explosive assets in Tech & Crypto.</i></p>
        <hr>
        <h3>⚡ Volatility Kings (Stocks)</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Vol Ratio</th><th>Signal</th></tr>
        """
        
        for stock in STOCKS_TO_WATCH:
            data = self.fetch_stock_whale_activity(stock)
            if data:
                color = "red" if "ERUPTION" in data['signal'] else "green" if "ACTIVE" in data['signal'] else "black"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{data['ratio']}x</td>
                    <td style="color:{color}"><b>{data['signal']}</b></td>
                </tr>"""
            time.sleep(12) 
            
        html += "</table><h3>🪙 Crypto & Memes</h3><ul>"
        
        for coin in CRYPTO_IDS:
            data = self.fetch_crypto_whale_activity(coin)
            if data:
                color = "green" if "MOONSHOT" in data['signal'] else "red" if "CRASH" in data['signal'] else "black"
                html += f"<li><b>{data['symbol']}</b>: ${data['price']} ({data['change']}%) - <span style='color:{color}'><b>{data['signal']}</b></span></li>"
            time.sleep(2)
            
        html += "</ul><hr><p><i>Automated Strategy Agent</i></p></body></html>"
        return html

    def send_email(self, html_report):
        if not SENDER_EMAIL: return
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"⚡ VOLATILITY ALERT: {self.timestamp}"
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
