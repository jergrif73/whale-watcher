import smtplib
import requests
import time
import statistics
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION ---
# These specific variable names are required for GitHub Actions Secrets
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

COINGECKO_URL = "https://api.coingecko.com/api/v3"

# --- WATCHLISTS (AI, TECH, CRYPTO) ---
# Strictly limited to <10 stocks to stay under Alpha Vantage Free Tier (25 req/day)
# Running this script 2x daily = 14 requests total.
STOCKS_TO_WATCH = [
    'NVDA', # AI Hardware King
    'AMD',  # AI/Chip Competitor
    'PLTR', # AI Software/Defense
    'MSFT', # Tech/OpenAI Partner
    'GOOGL',# Tech/Gemini
    'TSLA', # Tech/Robotics
    'QQQ'   # Broad Tech ETF
]

# AI-Focused Crypto + Majors
CRYPTO_IDS = [
    'bitcoin',
    'ethereum',
    'solana',
    'fetch-ai', # AI Crypto Agent
    'render-token' # GPU Rendering (AI adj)
]

class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def fetch_stock_whale_activity(self, symbol):
        """
        Wall St Logic: Vol > 1.5x Avg = Institutional Action
        """
        if not ALPHA_VANTAGE_KEY:
            self.log("Missing Alpha Vantage Key")
            return None
            
        url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}'
        try:
            response = requests.get(url)
            data = response.json()
            
            # Handle API errors or limits
            if "Time Series (Daily)" not in data:
                self.log(f"Skipping {symbol}: API limit or error.")
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
            
            # AI/Tech stocks are volatile; we need stricter triggers
            signal = "NEUTRAL"
            if volume_ratio > 1.8: # Raised threshold for high-beta tech
                signal = "WHALE ALERT (High Vol)"
            elif volume_ratio < 0.5:
                signal = "LOW VOL (Ignore)"

            return {
                "symbol": symbol,
                "price": today_close,
                "ratio": round(volume_ratio, 2),
                "signal": signal,
                "avg_vol": f"{int(avg_vol):,}"
            }
        except Exception as e:
            self.log(f"Error {symbol}: {e}")
            return None

    def fetch_crypto_whale_activity(self, coin_id):
        """
        Crypto Logic: Price/Vol divergence
        """
        url = f"{COINGECKO_URL}/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true"
        try:
            response = requests.get(url)
            if response.status_code != 200: 
                return None
            data = response.json().get(coin_id)
            if not data: return None
            
            price = data['usd']
            change_24h = data['usd_24h_change']
            
            signal = "HOLD"
            # AI Coins (Fetch/Render) are more volatile than BTC
            threshold = 8.0 if coin_id in ['fetch-ai', 'render-token'] else 4.0
            
            if change_24h > threshold:
                signal = "PUMP WATCH"
            elif change_24h < -threshold:
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
        self.log("Generating Report...")
        html = f"""
        <html><body>
        <h2>🤖 AI & Whale Tech Tracker: {self.timestamp}</h2>
        <hr>
        <h3>🧠 Wall St: AI & Big Tech</h3>
        <table border="1" cellpadding="5" cellspacing="0">
        <tr><th>Ticker</th><th>Price</th><th>Vol Ratio</th><th>Signal</th></tr>
        """
        
        for stock in STOCKS_TO_WATCH:
            data = self.fetch_stock_whale_activity(stock)
            if data:
                color = "green" if "WHALE" in data['signal'] else "black"
                html += f"""
                <tr>
                    <td><b>{data['symbol']}</b></td>
                    <td>${data['price']}</td>
                    <td>{data['ratio']}x</td>
                    <td style="color:{color}"><b>{data['signal']}</b></td>
                </tr>"""
            time.sleep(12) # CRITICAL: Respect Alpha Vantage 5 calls/min limit
            
        html += "</table><h3>🔗 Crypto: AI & L1s</h3><ul>"
        
        for coin in CRYPTO_IDS:
            data = self.fetch_crypto_whale_activity(coin)
            if data:
                color = "red" if "DIP" in data['signal'] else "green" if "PUMP" in data['signal'] else "black"
                html += f"<li><b>{data['symbol']}</b>: ${data['price']} ({data['change']}%) - <span style='color:{color}'><b>{data['signal']}</b></span></li>"
            time.sleep(2)
            
        html += "</ul><hr><p><i>Automated Agent Report</i></p></body></html>"
        return html

    def send_email(self, html_report):
        if not SENDER_EMAIL or not SENDER_PASSWORD:
            self.log("Email credentials missing. Printing report to console instead.")
            print(html_report)
            return

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"MARKET ALERT: {self.timestamp}"
        msg.attach(MIMEText(html_report, 'html'))
        
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            self.log("Email sent!")
        except Exception as e:
            self.log(f"Email failed: {e}")

if __name__ == "__main__":
    agent = MarketAgent()
    report = agent.generate_report()
    agent.send_email(report)
