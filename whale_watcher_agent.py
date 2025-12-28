import smtplib
import yfinance as yf
import pandas as pd
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
is_manual_env = os.environ.get("IS_MANUAL_RUN", "false").lower()
IS_MANUAL = is_manual_env == "true"

EMAIL_SUBJECT_BASE = "Market Intelligence Report"

# --- 💼 YOUR PORTFOLIO ---
MY_PORTFOLIO = {
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
        self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.has_critical_news = False
        self.recent_signals = []

    def log_signal(self, ticker, action, price, entry_price=None, gain_loss_pct=None, holding_days=None, notes=""):
        """Log a trading signal for the activity feed"""
        signal = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "action": action,
            "price": str(round(price, 2)),
            "notes": notes
        }
        if entry_price is not None:
            signal["entry_price"] = str(round(entry_price, 2))
        if gain_loss_pct is not None:
            signal["gain_loss_pct"] = str(round(gain_loss_pct, 1))
        if holding_days is not None:
            signal["holding_days"] = str(holding_days)
        self.recent_signals.append(signal)

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
            
            # Weekly change (7 days ago)
            weekly_change = 0.0
            if len(df) >= 7:
                week_ago_price = df['Close'].iloc[-7]
                weekly_change = ((current_price - week_ago_price) / week_ago_price) * 100
            
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # Build price history for charts (last 30 data points)
            price_history = []
            history_df = df.tail(30)
            for idx, row in history_df.iterrows():
                price_history.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": round(row['Close'], 2),
                    "volume": int(row['Volume'])
                })
            
            whale_intel = self.check_whale_intel(stock, ticker)
            clean_ticker = ticker.replace("-USD", "")
            
            holding_days = None
            gain_loss_pct = 0.0
            entry_price = 0.0
            is_weekend_now = datetime.now(timezone.utc).weekday() >= 5
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
                        signal = f"💰 SELL NOW (+{round(gain_loss_pct,1)}%)" if not is_settling else f"💰 FAST PROFIT (+{round(gain_loss_pct,1)}%)"
                        color = "green"
                        self.has_critical_news = True
                        self.log_signal(clean_ticker, "SELL_SIGNAL", current_price, entry_price, gain_loss_pct, holding_days, "Profit target reached")
                    elif gain_loss_pct <= STOP_LOSS_PCT:
                        signal = f"⚠️ VOLATILE ({round(gain_loss_pct,1)}%) - Settling" if is_settling else f"🛑 STOP LOSS ({round(gain_loss_pct,1)}%)"
                        color = "orange" if is_settling else "red"
                        if not is_settling:
                            self.has_critical_news = True
                            self.log_signal(clean_ticker, "STOP_LOSS", current_price, entry_price, gain_loss_pct, holding_days, "Stop loss triggered")
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
                        self.log_signal(clean_ticker, "ALERT", current_price, notes=f"Major move: {round(pct_change,1)}%")
                    elif vol_ratio > 3.5:
                        signal = f"🐳 WHALE"
                        color = "purple"
                        self.has_critical_news = True
                        self.log_signal(clean_ticker, "WHALE_ACTIVITY", current_price, notes=f"Volume {vol_ratio}x avg")
                    elif current_rsi > 85:
                        signal = "🔥 DANGER"
                        color = "red"
                    elif current_rsi < 30:
                        signal = "✅ BUY DIP"
                        color = "green"
                        self.log_signal(clean_ticker, "BUY_SIGNAL", current_price, notes=f"RSI oversold: {current_rsi}")
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
                "daily_change": round(pct_change, 1),
                "weekly_change": round(weekly_change, 2),
                "vol_ratio": vol_ratio,
                "price_history": price_history,
                "is_owned": is_owned_asset
            }
        except Exception as e:
            print(f"   [ERROR] {ticker}: {e}")
            return None

    def fetch_benchmark(self, ticker):
        """Fetch benchmark data for SPY/QQQ"""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1mo")
            if len(df) < 7: return None
            
            current_price = df['Close'].iloc[-1]
            week_ago_price = df['Close'].iloc[-7]
            weekly_change = ((current_price - week_ago_price) / week_ago_price) * 100
            
            return {
                "current": round(current_price, 2),
                "change_pct": round(weekly_change, 2),
                "period_days": 7
            }
        except:
            return None

    def generate_json_data(self):
        """Generate comprehensive JSON data for the dashboard"""
        portfolio_data = []
        watchlist_data = []
        
        print("\n--- 📊 GENERATING DATA ---")
        
        # Portfolio - assets we own
        for ticker in MY_PORTFOLIO.keys():
            if not is_owned(ticker): continue
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data(yf_ticker)
            if data: portfolio_data.append(data)

        # Watchlist - assets we're watching but don't own
        all_assets = STOCKS_TO_WATCH + CRYPTO_TO_WATCH
        for ticker in all_assets:
            clean = ticker.replace("-USD", "")
            if is_owned(clean): continue
            data = self.fetch_data(ticker)
            if data: watchlist_data.append(data)
        
        # Fetch benchmarks
        print("\n--- 📈 FETCHING BENCHMARKS ---")
        benchmarks = {}
        spy_data = self.fetch_benchmark("SPY")
        if spy_data:
            benchmarks["SPY"] = spy_data
            print(f"   SPY: ${spy_data['current']} ({spy_data['change_pct']}% weekly)")
        qqq_data = self.fetch_benchmark("QQQ")
        if qqq_data:
            benchmarks["QQQ"] = qqq_data
            print(f"   QQQ: ${qqq_data['current']} ({qqq_data['change_pct']}% weekly)")
        
        # Calculate portfolio summary
        total_invested = 0.0
        total_current = 0.0
        for item in portfolio_data:
            if item['entry_price'] > 0:
                total_invested += item['entry_price']
                total_current += item['price']
        
        total_gain_loss = total_current - total_invested
        total_gain_loss_pct = (total_gain_loss / total_invested * 100) if total_invested > 0 else 0
        
        summary = {
            "total_invested": round(total_invested, 2),
            "total_current": round(total_current, 2),
            "total_gain_loss": round(total_gain_loss, 2),
            "total_gain_loss_pct": round(total_gain_loss_pct, 2),
            "position_count": len(portfolio_data)
        }
        
        # Load existing signals and merge (keep last 20)
        existing_signals = []
        signals_file = "docs/data/signals.json"
        if os.path.exists(signals_file):
            try:
                with open(signals_file, "r") as f:
                    existing_signals = json.load(f)
            except: pass
        
        all_signals = self.recent_signals + existing_signals
        all_signals = all_signals[:20]  # Keep only last 20
            
        return {
            "generated_at": self.timestamp,
            "portfolio": portfolio_data,
            "watchlist": watchlist_data,
            "benchmarks": benchmarks,
            "summary": summary,
            "recent_signals": all_signals,
            "settings": {
                "profit_target": PROFIT_TARGET_PCT,
                "stop_loss": STOP_LOSS_PCT,
                "settling_days": SETTLING_PERIOD_DAYS
            }
        }

    def generate_dashboard_html(self, data):
        """Generate static HTML report (email-compatible)"""
        
        current_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        def build_rows(items, is_portfolio):
            html_rows = ""
            for item in items:
                badge_bg = "#21262d"
                badge_text = item['color']
                pl_color = "#3fb950" if item['gain_loss_pct'] >= 0 else "#f85149"
                trend_color = "#3fb950" if item['trend'] == 'UP' else "#f85149"
                
                cell_style = "padding: 12px; border-bottom: 1px solid #30363d; color: #e6edf3; font-family: sans-serif; font-size: 14px;"
                link_style = "color: #388bfd; text-decoration: none; font-weight: bold;"
                badge_style = f"color: {badge_text}; border: 1px solid {badge_text}; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block; white-space: nowrap;"

                row = "<tr>"
                row += f'<td style="{cell_style}"><a href="https://finance.yahoo.com/quote/{item["yf_symbol"]}" style="{link_style}" target="_blank">{item["symbol"]}</a></td>'
                
                if is_portfolio:
                    row += f'<td style="{cell_style}">${item["entry_price"]}</td>'
                    row += f'<td style="{cell_style}">${item["price"]}</td>'
                    row += f'<td style="{cell_style} color: {pl_color};">{item["gain_loss_pct"]}%</td>'
                else:
                    row += f'<td style="{cell_style}">${item["price"]}</td>'
                    row += f'<td style="{cell_style} color: {trend_color};">{item["trend"]}</td>'
                    row += f'<td style="{cell_style}">{item["rsi"]}</td>'
                
                row += f'<td style="{cell_style}"><span style="{badge_style}">{item["signal"]}</span></td>'
                row += f'<td style="{cell_style} font-size: 12px; color: #8b949e;">{item["whale_intel"]}</td>'
                row += "</tr>"
                html_rows += row
            return html_rows

        portfolio_html = build_rows(data['portfolio'], True)
        watchlist_html = build_rows(data['watchlist'], False)

        html = f"""
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml">
        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
            <title>Whale Watcher Report</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #0d1117;">
            <table border="0" cellpadding="0" cellspacing="0" width="100%" bgcolor="#0d1117" style="background-color: #0d1117; color: #e6edf3;">
                <tr>
                    <td align="center" style="padding: 20px 10px;">
                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 800px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color: #e6edf3;">
                            <tr>
                                <td align="center" style="padding-bottom: 20px; border-bottom: 2px solid #30363d;">
                                    <h1 style="margin: 0; font-size: 24px; color: #e6edf3;">🐳 Whale Watcher</h1>
                                    <p style="margin: 5px 0 0 0; font-size: 14px; color: #8b949e;">Data: {data['generated_at']} | Generated: {current_time_utc}</p>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding-top: 30px;">
                                    <h3 style="margin: 0 0 15px 0; color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 5px;">💰 Your Holdings</h3>
                                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                                        <thead>
                                            <tr>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Asset</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Entry</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Price</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">P/L</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Signal</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Intel</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {portfolio_html if portfolio_html else '<tr><td colspan="6" style="padding: 20px; color: #8b949e; text-align: center;">No active positions</td></tr>'}
                                        </tbody>
                                    </table>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding-top: 30px;">
                                    <h3 style="margin: 0 0 15px 0; color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 5px;">⚡ Watchlist</h3>
                                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                                        <thead>
                                            <tr>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Ticker</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Price</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Trend</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">RSI</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Signal</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Intel</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {watchlist_html if watchlist_html else '<tr><td colspan="6" style="padding: 20px; color: #8b949e; text-align: center;">No watchlist data</td></tr>'}
                                        </tbody>
                                    </table>
                                </td>
                            </tr>
                            <tr>
                                <td align="center" style="padding-top: 40px; padding-bottom: 20px; color: #8b949e; font-size: 12px;">
                                    <p>Generated by Whale Watcher Agent.</p>
                                    <p>Markets are volatile. DYOR.</p>
                                    <p style="font-size: 10px; color: #30363d;">File ID: {current_time_utc}</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
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
        except Exception as e:
            print(f"📧 Email failed: {e}")

if __name__ == "__main__":
    current_hour = datetime.now(timezone.utc).hour
    is_routine_time = current_hour in [4, 16] 
    
    agent = MarketAgent()
    
    # 1. Ensure docs/data directory exists
    os.makedirs("docs/data", exist_ok=True)
    
    # 2. Generate Data
    data = agent.generate_json_data()
    
    # 3. Save JSON for the interactive dashboard
    json_path = "docs/data/dashboard.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"✅ JSON saved to {json_path}")
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")
    
    # 4. Save signals separately for persistence
    if agent.recent_signals:
        signals_path = "docs/data/signals.json"
        try:
            with open(signals_path, "w", encoding="utf-8") as f:
                json.dump(data['recent_signals'], f, indent=2, default=str)
            print(f"✅ Signals saved to {signals_path}")
        except Exception as e:
            print(f"❌ Error writing signals: {e}")
    
    # 5. Generate Dashboard HTML (for email and root index)
    dashboard_html = agent.generate_dashboard_html(data)
    
    # 6. Save static HTML to root (for email-style view)
    file_path = "index.html"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dashboard_html)
        print(f"✅ Static HTML generated at {file_path}. Size: {len(dashboard_html)} bytes.")
    except Exception as e:
        print(f"❌ Error writing HTML: {e}")

    # 7. Email Logic
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
        print("💤 No critical news. Dashboard updated silently.")
