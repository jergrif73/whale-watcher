import smtplib
import yfinance as yf
import pandas as pd
import os
import json
import uuid
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

# --- SETTINGS ---
PROFIT_TARGET_PCT = 20.0
STOP_LOSS_PCT = -8.0
SETTLING_PERIOD_DAYS = 3

WHALE_KEYWORDS = [
    "Public Investment Fund", "PIF", "Norges", "NBIM", "Abu Dhabi Investment", "ADIA", 
    "Mubadala", "Qatar Investment", "QIA", "Elliott", "Pershing Square", "Ackman", 
    "Third Point", "Loeb", "Icahn", "Trian", "Peltz", "Starboard", "Citadel", 
    "Bridgewater", "Millennium", "Point72", "D. E. Shaw", "Berkshire", "Buffett", 
    "BlackRock", "Vanguard"
]

CRYPTO_SYMBOLS = ['BTC', 'ETH', 'SOL', 'FET', 'RNDR', 'DOGE', 'PEPE']

TRADE_JOURNAL_PATH = "docs/data/trade_journal.json"


class TradeJournal:
    """Manages trade history and calculates current positions"""
    
    def __init__(self, path=TRADE_JOURNAL_PATH):
        self.path = path
        self.trades = []
        self.watchlist = []
        self.load()
    
    def load(self):
        """Load trade journal from file"""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    self.trades = data.get("trades", [])
                    self.watchlist = data.get("watchlist", [])
                print(f"📒 Loaded {len(self.trades)} trades, {len(self.watchlist)} watchlist items")
            except Exception as e:
                print(f"⚠️ Error loading trade journal: {e}")
                self.trades = []
                self.watchlist = []
        else:
            print(f"📒 No trade journal found, starting fresh")
            self.trades = []
            self.watchlist = []
    
    def save(self):
        """Save trade journal to file"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({
                "trades": self.trades,
                "watchlist": self.watchlist
            }, f, indent=2)
        print(f"📒 Saved trade journal")
    
    def add_trade(self, ticker, action, price, shares, notes=""):
        """Add a new trade to the journal"""
        trade = {
            "id": str(uuid.uuid4())[:8],
            "ticker": ticker.upper().replace("-USD", ""),
            "action": action.upper(),  # BUY or SELL
            "price": float(price),
            "shares": float(shares),
            "date": datetime.now(timezone.utc).isoformat(),
            "notes": notes
        }
        self.trades.append(trade)
        self.save()
        return trade
    
    def get_positions(self):
        """Calculate current positions from trade history"""
        positions = {}
        
        for trade in sorted(self.trades, key=lambda x: x['date']):
            ticker = trade['ticker']
            
            if ticker not in positions:
                positions[ticker] = {
                    'shares': 0,
                    'cost_basis': 0,
                    'total_invested': 0,
                    'first_buy_date': None,
                    'last_buy_date': None,
                    'last_buy_price': 0,
                    'trades': []
                }
            
            pos = positions[ticker]
            pos['trades'].append(trade)
            
            if trade['action'] == 'BUY':
                # Add to position
                cost = trade['price'] * trade['shares']
                pos['total_invested'] += cost
                pos['shares'] += trade['shares']
                pos['cost_basis'] = pos['total_invested'] / pos['shares'] if pos['shares'] > 0 else 0
                pos['last_buy_date'] = trade['date']
                pos['last_buy_price'] = trade['price']
                if pos['first_buy_date'] is None:
                    pos['first_buy_date'] = trade['date']
                    
            elif trade['action'] == 'SELL':
                # Remove from position
                shares_to_sell = min(trade['shares'], pos['shares'])
                if pos['shares'] > 0:
                    # Reduce cost basis proportionally
                    sell_ratio = shares_to_sell / pos['shares']
                    pos['total_invested'] -= pos['total_invested'] * sell_ratio
                pos['shares'] -= shares_to_sell
                
                # If fully sold, reset dates
                if pos['shares'] <= 0:
                    pos['shares'] = 0
                    pos['cost_basis'] = 0
                    pos['total_invested'] = 0
                    pos['first_buy_date'] = None
                    pos['last_buy_date'] = None
                else:
                    pos['cost_basis'] = pos['total_invested'] / pos['shares']
        
        # Filter to only active positions
        active = {k: v for k, v in positions.items() if v['shares'] > 0}
        return active
    
    def get_position(self, ticker):
        """Get position for a specific ticker"""
        positions = self.get_positions()
        return positions.get(ticker.upper().replace("-USD", ""))
    
    def is_owned(self, ticker):
        """Check if ticker is currently owned"""
        pos = self.get_position(ticker)
        return pos is not None and pos['shares'] > 0
    
    def get_ticker_trades(self, ticker):
        """Get all trades for a specific ticker"""
        clean = ticker.upper().replace("-USD", "")
        return [t for t in self.trades if t['ticker'] == clean]


class MarketAgent:
    def __init__(self):
        self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.has_critical_news = False
        self.recent_signals = []
        self.journal = TradeJournal()

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
        """Check for whale activity and insider trading"""
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

    def calc_holding_days(self, buy_date_str):
        """Calculate days since purchase"""
        if not buy_date_str:
            return None
        try:
            buy_date = datetime.fromisoformat(buy_date_str.replace('Z', '+00:00'))
            return (datetime.now(timezone.utc) - buy_date).days
        except:
            return None

    def fetch_data_for_watchlist(self, ticker):
        """Fetch data for a watchlist item (not owned) - focus on BUY signals"""
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
            
            # Weekly change
            weekly_change = 0.0
            if len(df) >= 7:
                week_ago_price = df['Close'].iloc[-7]
                weekly_change = ((current_price - week_ago_price) / week_ago_price) * 100
            
            # RSI calculation
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # Price history for charts
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
            is_crypto = clean_ticker in CRYPTO_SYMBOLS
            is_weekend = datetime.now(timezone.utc).weekday() >= 5
            
            # --- WATCHLIST SIGNAL LOGIC (Focus on BUY opportunities) ---
            signal = "NEUTRAL"
            color = "black"
            
            if is_weekend and not is_crypto:
                signal = "⏸️ WEEKEND"
                color = "gray"
            else:
                # Major news/movement
                if abs(pct_change) > 10.0:
                    direction = "📈" if pct_change > 0 else "📉"
                    signal = f"{direction} BIG MOVE ({round(pct_change,1)}%)"
                    color = "purple"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "ALERT", current_price, notes=f"Major move: {round(pct_change,1)}%")
                
                # Whale/volume activity
                elif vol_ratio > 3.5:
                    signal = "🐳 WHALE ACTIVITY"
                    color = "purple"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "WHALE_ACTIVITY", current_price, notes=f"Volume {vol_ratio}x avg")
                
                # RSI signals - focus on BUY opportunities for watchlist
                elif current_rsi < 25:
                    signal = "🔥 OVERSOLD - STRONG BUY"
                    color = "green"
                    self.log_signal(clean_ticker, "STRONG_BUY", current_price, notes=f"RSI extremely oversold: {current_rsi}")
                elif current_rsi < 30:
                    signal = "✅ OVERSOLD - BUY DIP"
                    color = "green"
                    self.log_signal(clean_ticker, "BUY_SIGNAL", current_price, notes=f"RSI oversold: {current_rsi}")
                elif current_rsi > 85:
                    signal = "⚠️ OVERBOUGHT - AVOID"
                    color = "red"
                elif current_rsi > 70:
                    signal = "📊 OVERBOUGHT"
                    color = "orange"
                # Trend-based
                elif trend == "UP" and current_rsi < 50:
                    signal = "👀 UPTREND DIP"
                    color = "blue"

            return {
                "symbol": clean_ticker,
                "yf_symbol": ticker,
                "price": round(current_price, 2),
                "entry_price": 0,
                "cost_basis": 0,
                "shares": 0,
                "trend": trend,
                "rsi": current_rsi,
                "signal": signal,
                "color": color,
                "whale_intel": whale_intel,
                "holding_days": None,
                "gain_loss_pct": 0,
                "daily_change": round(pct_change, 1),
                "weekly_change": round(weekly_change, 2),
                "vol_ratio": vol_ratio,
                "price_history": price_history,
                "is_owned": False
            }
        except Exception as e:
            print(f"   [ERROR] {ticker}: {e}")
            return None

    def fetch_data_for_position(self, ticker, position):
        """Fetch data for an owned position - focus on SELL signals and P/L"""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            if len(df) < 2: return None
            
            current_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            current_vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].iloc[-11:-1].mean()
            vol_ratio = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            
            # For owned positions, calculate trend from purchase date
            buy_date_str = position['last_buy_date']
            holding_days = self.calc_holding_days(buy_date_str)
            
            # Filter price history to only after purchase for trend analysis
            if buy_date_str:
                try:
                    buy_date = datetime.fromisoformat(buy_date_str.replace('Z', '+00:00'))
                    df_since_buy = df[df.index >= buy_date.strftime('%Y-%m-%d')]
                    if len(df_since_buy) >= 2:
                        # Use post-purchase data for trend
                        sma_period = min(len(df_since_buy), 10)  # Shorter SMA for recent buys
                        sma = df_since_buy['Close'].rolling(window=sma_period).mean().iloc[-1]
                        trend = "UP" if current_price > sma else "DOWN"
                    else:
                        trend = "NEW"  # Just bought, not enough data
                except:
                    sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else current_price
                    trend = "UP" if current_price > sma_50 else "DOWN"
            else:
                sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else current_price
                trend = "UP" if current_price > sma_50 else "DOWN"
            
            pct_change = ((current_price - prev_close) / prev_close) * 100
            
            # Weekly change
            weekly_change = 0.0
            if len(df) >= 7:
                week_ago_price = df['Close'].iloc[-7]
                weekly_change = ((current_price - week_ago_price) / week_ago_price) * 100
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = round(rsi.iloc[-1], 2)
            
            # Price history (full for charting, but signal logic uses post-purchase)
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
            is_crypto = clean_ticker in CRYPTO_SYMBOLS
            is_weekend = datetime.now(timezone.utc).weekday() >= 5
            
            # Position details
            cost_basis = position['cost_basis']
            shares = position['shares']
            gain_loss_pct = ((current_price - cost_basis) / cost_basis) * 100 if cost_basis > 0 else 0
            
            print(f"   [OWNED] {clean_ticker}: {shares} shares @ ${cost_basis:.2f} | Now ${current_price:.2f} | P/L: {gain_loss_pct:.1f}% | {holding_days} days")
            
            # --- PORTFOLIO SIGNAL LOGIC (Focus on SELL signals and position management) ---
            signal = "NEUTRAL"
            color = "black"
            is_settling = holding_days is not None and holding_days <= SETTLING_PERIOD_DAYS
            
            if is_weekend and not is_crypto:
                signal = "⏸️ WEEKEND"
                color = "gray"
            elif is_settling:
                # In settling period - be cautious
                if gain_loss_pct >= PROFIT_TARGET_PCT:
                    signal = f"💰 PROFIT +{round(gain_loss_pct,1)}% (Settling)"
                    color = "green"
                    self.log_signal(clean_ticker, "PROFIT_SETTLING", current_price, cost_basis, gain_loss_pct, holding_days, "Profit target hit but settling")
                elif gain_loss_pct <= STOP_LOSS_PCT:
                    signal = f"⚠️ LOSS {round(gain_loss_pct,1)}% (Settling)"
                    color = "orange"
                else:
                    signal = f"🆕 NEW POSITION ({holding_days}d)"
                    color = "blue"
            else:
                # Full trading - evaluate sell signals
                if gain_loss_pct >= PROFIT_TARGET_PCT * 1.5:
                    signal = f"🚀 STRONG SELL +{round(gain_loss_pct,1)}%"
                    color = "green"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "STRONG_SELL", current_price, cost_basis, gain_loss_pct, holding_days, "Well above profit target")
                elif gain_loss_pct >= PROFIT_TARGET_PCT:
                    signal = f"💰 SELL TARGET +{round(gain_loss_pct,1)}%"
                    color = "green"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "SELL_SIGNAL", current_price, cost_basis, gain_loss_pct, holding_days, "Profit target reached")
                elif gain_loss_pct <= STOP_LOSS_PCT:
                    signal = f"🛑 STOP LOSS {round(gain_loss_pct,1)}%"
                    color = "red"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "STOP_LOSS", current_price, cost_basis, gain_loss_pct, holding_days, "Stop loss triggered")
                elif gain_loss_pct <= STOP_LOSS_PCT / 2:
                    signal = f"⚠️ WATCH LOSS {round(gain_loss_pct,1)}%"
                    color = "orange"
                elif current_rsi > 80:
                    signal = f"📊 OVERBOUGHT +{round(gain_loss_pct,1)}%"
                    color = "orange"
                    self.log_signal(clean_ticker, "OVERBOUGHT", current_price, cost_basis, gain_loss_pct, holding_days, f"RSI high: {current_rsi}")
                elif gain_loss_pct > 0:
                    signal = f"💎 HOLD +{round(gain_loss_pct,1)}%"
                    color = "blue"
                else:
                    signal = f"💎 HOLD {round(gain_loss_pct,1)}%"
                    color = "blue"

            return {
                "symbol": clean_ticker,
                "yf_symbol": ticker,
                "price": round(current_price, 2),
                "entry_price": round(position['last_buy_price'], 2),
                "cost_basis": round(cost_basis, 2),
                "shares": round(shares, 4),
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
                "is_owned": True,
                "first_buy_date": position['first_buy_date'],
                "last_buy_date": position['last_buy_date'],
                "total_invested": round(position['total_invested'], 2)
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
        
        # Get current positions from trade journal
        positions = self.journal.get_positions()
        print(f"\n--- 💼 PORTFOLIO ({len(positions)} positions) ---")
        
        for ticker, position in positions.items():
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data_for_position(yf_ticker, position)
            if data:
                portfolio_data.append(data)
        
        # Get watchlist items (not owned)
        print(f"\n--- 👀 WATCHLIST ({len(self.journal.watchlist)} items) ---")
        
        for ticker in self.journal.watchlist:
            clean = ticker.upper().replace("-USD", "")
            if self.journal.is_owned(clean):
                continue  # Skip if we own it
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data_for_watchlist(yf_ticker)
            if data:
                watchlist_data.append(data)
        
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
        total_invested = sum(item.get('total_invested', 0) for item in portfolio_data)
        total_current = sum(item['price'] * item.get('shares', 0) for item in portfolio_data)
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
        all_signals = all_signals[:20]
            
        return {
            "generated_at": self.timestamp,
            "portfolio": portfolio_data,
            "watchlist": watchlist_data,
            "benchmarks": benchmarks,
            "summary": summary,
            "recent_signals": all_signals,
            "trade_history": self.journal.trades[-10:],  # Last 10 trades
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
            
            # Color mapping for dark background visibility
            color_map = {
                "black": "#8b949e",   # NEUTRAL - muted gray
                "gray": "#8b949e",    # WEEKEND - muted gray  
                "green": "#3fb950",   # SELL NOW, BUY DIP - bright green
                "red": "#f85149",     # STOP LOSS, DANGER - bright red
                "orange": "#d29922",  # SETTLING - amber/orange
                "blue": "#58a6ff",    # HOLDING - bright blue
                "purple": "#a371f7",  # NEWS, WHALE - purple
            }
            
            for item in items:
                badge_color = color_map.get(item['color'], "#8b949e")
                pl_color = "#3fb950" if item.get('gain_loss_pct', 0) >= 0 else "#f85149"
                trend_color = "#3fb950" if item['trend'] == 'UP' else "#f85149"
                
                cell_style = "padding: 12px; border-bottom: 1px solid #30363d; color: #e6edf3; font-family: sans-serif; font-size: 14px;"
                link_style = "color: #388bfd; text-decoration: none; font-weight: bold;"
                badge_style = f"color: {badge_color}; border: 1px solid {badge_color}; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block; white-space: nowrap;"

                row = "<tr>"
                row += f'<td style="{cell_style}"><a href="https://finance.yahoo.com/quote/{item["yf_symbol"]}" style="{link_style}" target="_blank">{item["symbol"]}</a></td>'
                
                if is_portfolio:
                    shares = item.get('shares', 0)
                    row += f'<td style="{cell_style}">{shares:.2f} @ ${item["cost_basis"]}</td>'
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
        
        # Summary section
        summary = data.get('summary', {})
        summary_color = "#3fb950" if summary.get('total_gain_loss', 0) >= 0 else "#f85149"

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
                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 900px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color: #e6edf3;">
                            <tr>
                                <td align="center" style="padding-bottom: 20px; border-bottom: 2px solid #30363d;">
                                    <h1 style="margin: 0; font-size: 24px; color: #e6edf3;">🐳 Whale Watcher</h1>
                                    <p style="margin: 5px 0 0 0; font-size: 14px; color: #8b949e;">Generated: {current_time_utc}</p>
                                </td>
                            </tr>
                            
                            <!-- Portfolio Summary -->
                            <tr>
                                <td style="padding-top: 20px;">
                                    <table width="100%" cellpadding="10" style="background-color: #161b22; border-radius: 8px;">
                                        <tr>
                                            <td style="color: #8b949e; font-size: 12px;">INVESTED</td>
                                            <td style="color: #8b949e; font-size: 12px;">CURRENT VALUE</td>
                                            <td style="color: #8b949e; font-size: 12px;">TOTAL P/L</td>
                                            <td style="color: #8b949e; font-size: 12px;">POSITIONS</td>
                                        </tr>
                                        <tr>
                                            <td style="color: #e6edf3; font-size: 18px; font-weight: bold;">${summary.get('total_invested', 0):.2f}</td>
                                            <td style="color: #e6edf3; font-size: 18px; font-weight: bold;">${summary.get('total_current', 0):.2f}</td>
                                            <td style="color: {summary_color}; font-size: 18px; font-weight: bold;">${summary.get('total_gain_loss', 0):.2f} ({summary.get('total_gain_loss_pct', 0):.1f}%)</td>
                                            <td style="color: #e6edf3; font-size: 18px; font-weight: bold;">{summary.get('position_count', 0)}</td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <tr>
                                <td style="padding-top: 30px;">
                                    <h3 style="margin: 0 0 15px 0; color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 5px;">💼 Your Positions</h3>
                                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                                        <thead>
                                            <tr>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Asset</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Position</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Price</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">P/L</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Signal</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase;">Intel</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {portfolio_html if portfolio_html else '<tr><td colspan="6" style="padding: 20px; color: #8b949e; text-align: center;">No active positions - check watchlist for opportunities</td></tr>'}
                                        </tbody>
                                    </table>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding-top: 30px;">
                                    <h3 style="margin: 0 0 15px 0; color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 5px;">👀 Watchlist</h3>
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
                                            {watchlist_html if watchlist_html else '<tr><td colspan="6" style="padding: 20px; color: #8b949e; text-align: center;">No watchlist items</td></tr>'}
                                        </tbody>
                                    </table>
                                </td>
                            </tr>
                            <tr>
                                <td align="center" style="padding-top: 40px; padding-bottom: 20px; color: #8b949e; font-size: 12px;">
                                    <p>Generated by Whale Watcher Agent</p>
                                    <p>📗 Watchlist = BUY signals | 💼 Portfolio = SELL signals</p>
                                    <p style="font-size: 10px; color: #30363d;">Markets are volatile. DYOR.</p>
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
    
    # 5. Generate Dashboard HTML (for email)
    dashboard_html = agent.generate_dashboard_html(data)
    
    # 6. Save static HTML to root
    file_path = "index.html"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dashboard_html)
        print(f"✅ Static HTML generated at {file_path}")
    except Exception as e:
        print(f"❌ Error writing HTML: {e}")

    # 7. Email Logic
    if IS_MANUAL:
        print("🕹️ Manual Override - sending email")
        agent.send_email(dashboard_html, subject_prefix="🕹️ TEST:")
    elif agent.has_critical_news:
        print("🚨 CRITICAL UPDATE - sending email")
        agent.send_email(dashboard_html, subject_prefix="🚨 ACTION:")
    elif is_routine_time:
        print("⏰ Routine Schedule - sending email")
        agent.send_email(dashboard_html, subject_prefix="📊 DAILY:")
    else:
        print("💤 No critical news. Dashboard updated silently.")
