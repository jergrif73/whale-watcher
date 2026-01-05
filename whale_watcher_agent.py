import smtplib
import yfinance as yf
import pandas as pd
import numpy as np
import os
import json
import uuid
import requests
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

# --- CONFIGURATION ---
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
is_manual_env = os.environ.get("IS_MANUAL_RUN", "false").lower()
IS_MANUAL = is_manual_env == "true"

# --- AI DEEP ANALYSIS SETTINGS ---
deep_analysis_env = os.environ.get("DEEP_ANALYSIS", "false").lower()
DEEP_ANALYSIS = deep_analysis_env == "true"
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")

EMAIL_SUBJECT_BASE = "Market Intelligence Report"

# --- TRADING SETTINGS ---
# Profit Taking Tiers (scale out strategy)
PROFIT_TIER_1 = 15.0    # Consider trimming 25% of position
PROFIT_TIER_2 = 25.0    # Consider trimming another 25%
PROFIT_TIER_3 = 40.0    # Consider trimming another 25%
PROFIT_TIER_4 = 60.0    # Strong sell - take most profits

# Stop Loss Tiers
STOP_LOSS_WARN = -5.0   # Warning zone
STOP_LOSS_SOFT = -8.0   # Soft stop - evaluate
STOP_LOSS_HARD = -15.0  # Hard stop - exit

# Trailing Stop (from peak since purchase)
TRAILING_STOP_PCT = 12.0  # If drops 12% from peak, consider selling

# Buy More Conditions
ADD_ON_DIP_RSI = 35       # RSI threshold to consider adding
ADD_ON_DIP_DRAWDOWN = -10 # Drawdown from cost basis to consider adding
ADD_ON_BREAKOUT_PCT = 5   # % above recent high to consider adding (momentum)

# Timing
SETTLING_PERIOD_DAYS = 3
MIN_HOLD_FOR_ADD = 7      # Don't add to position within first week

# Technical Thresholds
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_EXTREME_OVERSOLD = 25
RSI_EXTREME_OVERBOUGHT = 80
VOLUME_SPIKE_RATIO = 2.5  # Volume > 2.5x average is notable

# --- POSITION SIZING SETTINGS ---
DEFAULT_PORTFOLIO_SIZE = 1000  # Default portfolio size for sizing calc
MAX_POSITION_PCT = 10.0        # Max % of portfolio in single position
RISK_PER_TRADE_PCT = 2.0       # Max % of portfolio to risk per trade

# --- TAX SETTINGS ---
SHORT_TERM_DAYS = 365          # Days to hold for long-term capital gains
LONG_TERM_BUFFER_DAYS = 14     # Alert X days before long-term eligibility

# --- DCA SETTINGS ---
DCA_DEFAULT_FREQUENCY = "weekly"  # weekly, biweekly, monthly

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
    """Manages trade history and calculates current positions - DOLLAR BASED"""
    
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
    
    def add_trade(self, ticker, action, amount_invested, price_at_purchase, notes=""):
        """Add a new trade to the journal - DOLLAR BASED"""
        trade = {
            "id": str(uuid.uuid4())[:8],
            "ticker": ticker.upper().replace("-USD", ""),
            "action": action.upper(),
            "amount_invested": float(amount_invested),
            "price_at_purchase": float(price_at_purchase),
            "date": datetime.now(timezone.utc).isoformat(),
            "notes": notes
        }
        self.trades.append(trade)
        self.save()
        return trade
    
    def get_positions(self):
        """Calculate current positions from trade history - PURE DOLLAR TRACKING
        
        Trade journal stores: ticker, amount, date
        System looks up historical price for that date
        
        NO price_at_purchase in trade - system fetches it automatically
        """
        positions = {}
        
        for trade in sorted(self.trades, key=lambda x: x['date']):
            ticker = trade['ticker']
            
            if ticker not in positions:
                positions[ticker] = {
                    'amount': 0,
                    'buy_date': None,
                    'first_buy_date': None,
                    'last_buy_date': None,
                    'buy_count': 0,
                    'trades': []
                }
            
            pos = positions[ticker]
            pos['trades'].append(trade)
            
            if trade['action'] == 'BUY':
                amount = trade.get('amount', trade.get('amount_invested', 0))
                pos['amount'] += amount
                pos['last_buy_date'] = trade['date']
                pos['buy_count'] += 1
                if pos['first_buy_date'] is None:
                    pos['first_buy_date'] = trade['date']
                    pos['buy_date'] = trade['date']  # Use first buy date for price lookup
                    
            elif trade['action'] == 'SELL':
                sell_amount = trade.get('amount', trade.get('amount_invested', 0))
                pos['amount'] = max(0, pos['amount'] - sell_amount)
                
                if pos['amount'] <= 0:
                    pos['amount'] = 0
                    pos['buy_date'] = None
                    pos['first_buy_date'] = None
                    pos['last_buy_date'] = None
                    pos['buy_count'] = 0
        
        # Filter to only active positions
        active = {k: v for k, v in positions.items() if v['amount'] > 0}
        return active
    
    def get_position(self, ticker):
        """Get position for a specific ticker"""
        positions = self.get_positions()
        return positions.get(ticker.upper().replace("-USD", ""))
    
    def is_owned(self, ticker):
        """Check if ticker is currently owned"""
        pos = self.get_position(ticker)
        return pos is not None and pos.get('amount', 0) > 0
    
    def get_ticker_trades(self, ticker):
        """Get all trades for a specific ticker"""
        clean = ticker.upper().replace("-USD", "")
        return [t for t in self.trades if t['ticker'] == clean]


# ============================================================================
# NEW FEATURE CLASSES
# ============================================================================

class DCATracker:
    """Track Dollar Cost Averaging schedules and performance"""
    
    def __init__(self, journal):
        self.journal = journal
        self.schedules = journal.dca_schedules if hasattr(journal, 'dca_schedules') else []
    
    def analyze_dca_performance(self, ticker, trades):
        """Analyze DCA performance for a ticker"""
        buy_trades = [t for t in trades if t['action'] == 'BUY']
        if len(buy_trades) < 2:
            return None
        
        # Calculate average cost via DCA
        total_invested = sum(t.get('amount', 0) for t in buy_trades)
        
        # Get buy dates and amounts
        buys = []
        for t in buy_trades:
            buys.append({
                'date': t['date'],
                'amount': t.get('amount', 0)
            })
        
        # Calculate time between buys
        if len(buys) >= 2:
            dates = sorted([datetime.fromisoformat(b['date'].replace('Z', '+00:00')) if 'T' in b['date'] 
                           else datetime.strptime(b['date'], '%Y-%m-%d').replace(tzinfo=timezone.utc) 
                           for b in buys])
            intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            avg_interval = sum(intervals) / len(intervals) if intervals else 0
        else:
            avg_interval = 0
        
        return {
            'ticker': ticker,
            'total_buys': len(buy_trades),
            'total_invested': total_invested,
            'avg_buy_amount': total_invested / len(buy_trades) if buy_trades else 0,
            'avg_interval_days': round(avg_interval, 1),
            'first_buy': min(t['date'] for t in buy_trades),
            'last_buy': max(t['date'] for t in buy_trades),
            'consistency': 'Regular' if 0 < avg_interval <= 35 else 'Irregular'
        }
    
    def get_dca_suggestions(self, portfolio_data, watchlist_data):
        """Suggest good DCA candidates based on volatility and trend"""
        suggestions = []
        
        all_items = portfolio_data + watchlist_data
        for item in all_items:
            # Good DCA candidates: uptrend, not overbought, reasonable volatility
            if item.get('trend') == 'UP' and item.get('rsi', 50) < 65:
                score = 0
                reasons = []
                
                if item.get('rsi', 50) < 40:
                    score += 30
                    reasons.append("RSI in buy zone")
                if item.get('trend') == 'UP':
                    score += 20
                    reasons.append("Uptrend")
                if item.get('vol_pattern') == 'ACCUMULATION':
                    score += 25
                    reasons.append("Accumulation pattern")
                
                if score >= 40:
                    suggestions.append({
                        'ticker': item['symbol'],
                        'score': score,
                        'reasons': reasons,
                        'current_price': item['price'],
                        'rsi': item.get('rsi', 0)
                    })
        
        return sorted(suggestions, key=lambda x: x['score'], reverse=True)[:5]


class PerformanceAnalyzer:
    """Analyze trading performance and attribution"""
    
    def __init__(self, journal, portfolio_data):
        self.journal = journal
        self.portfolio_data = portfolio_data
    
    def calculate_stats(self):
        """Calculate overall performance statistics"""
        all_trades = self.journal.trades
        
        if not all_trades:
            return self._empty_stats()
        
        # Group trades by ticker
        by_ticker = {}
        for trade in all_trades:
            ticker = trade['ticker']
            if ticker not in by_ticker:
                by_ticker[ticker] = []
            by_ticker[ticker].append(trade)
        
        # Calculate win/loss for closed positions and current P/L for open
        winners = 0
        losers = 0
        total_gain = 0
        total_loss = 0
        
        # Check portfolio for current P/L
        for item in self.portfolio_data:
            pnl = item.get('gain_loss_pct', 0)
            if pnl > 0:
                winners += 1
                total_gain += item.get('gain_loss_dollars', 0)
            elif pnl < 0:
                losers += 1
                total_loss += abs(item.get('gain_loss_dollars', 0))
        
        total_positions = winners + losers
        win_rate = (winners / total_positions * 100) if total_positions > 0 else 0
        
        # Calculate by category
        categories = self._categorize_performance()
        
        return {
            'total_trades': len(all_trades),
            'total_positions': total_positions,
            'winners': winners,
            'losers': losers,
            'win_rate': round(win_rate, 1),
            'total_gain': round(total_gain, 2),
            'total_loss': round(total_loss, 2),
            'net_pnl': round(total_gain - total_loss, 2),
            'avg_win': round(total_gain / winners, 2) if winners > 0 else 0,
            'avg_loss': round(total_loss / losers, 2) if losers > 0 else 0,
            'profit_factor': round(total_gain / total_loss, 2) if total_loss > 0 else 999,
            'categories': categories
        }
    
    def _categorize_performance(self):
        """Break down performance by asset category"""
        crypto = ['BTC', 'ETH', 'SOL', 'DOGE', 'PEPE', 'FET', 'RNDR']
        etfs = ['SPY', 'QQQ', 'SOXL', 'TQQQ']
        
        categories = {
            'crypto': {'count': 0, 'pnl': 0, 'invested': 0},
            'etf': {'count': 0, 'pnl': 0, 'invested': 0},
            'stock': {'count': 0, 'pnl': 0, 'invested': 0}
        }
        
        for item in self.portfolio_data:
            ticker = item['symbol']
            pnl = item.get('gain_loss_dollars', 0)
            invested = item.get('amount_invested', 0)
            
            if ticker in crypto:
                cat = 'crypto'
            elif ticker in etfs:
                cat = 'etf'
            else:
                cat = 'stock'
            
            categories[cat]['count'] += 1
            categories[cat]['pnl'] += pnl
            categories[cat]['invested'] += invested
        
        # Calculate return % for each category
        for cat in categories:
            if categories[cat]['invested'] > 0:
                categories[cat]['return_pct'] = round(
                    categories[cat]['pnl'] / categories[cat]['invested'] * 100, 1
                )
            else:
                categories[cat]['return_pct'] = 0
        
        return categories
    
    def _empty_stats(self):
        return {
            'total_trades': 0,
            'total_positions': 0,
            'winners': 0,
            'losers': 0,
            'win_rate': 0,
            'total_gain': 0,
            'total_loss': 0,
            'net_pnl': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'profit_factor': 0,
            'categories': {}
        }


class TaxLotTracker:
    """Track tax lots and alert for long-term holding opportunities"""
    
    def __init__(self, journal):
        self.journal = journal
    
    def analyze_tax_lots(self, portfolio_data):
        """Analyze tax lots for each position"""
        tax_lots = []
        
        for item in portfolio_data:
            ticker = item['symbol']
            holding_days = item.get('holding_days', 0) or 0
            
            days_to_long_term = SHORT_TERM_DAYS - holding_days
            
            if holding_days >= SHORT_TERM_DAYS:
                status = "LONG_TERM"
                alert = None
            elif days_to_long_term <= LONG_TERM_BUFFER_DAYS:
                status = "ALMOST_LONG"
                alert = f"Hold {days_to_long_term} more days for long-term rate!"
            else:
                status = "SHORT_TERM"
                alert = f"{days_to_long_term} days until long-term eligible"
            
            tax_lots.append({
                'ticker': ticker,
                'holding_days': holding_days,
                'status': status,
                'days_to_long_term': max(0, days_to_long_term),
                'alert': alert,
                'gain_loss_pct': item.get('gain_loss_pct', 0),
                'gain_loss_dollars': item.get('gain_loss_dollars', 0)
            })
        
        return tax_lots
    
    def get_tax_alerts(self, tax_lots):
        """Get important tax-related alerts"""
        alerts = []
        
        for lot in tax_lots:
            # Alert if close to long-term and in profit
            if lot['status'] == 'ALMOST_LONG' and lot['gain_loss_pct'] > 0:
                alerts.append({
                    'ticker': lot['ticker'],
                    'type': 'HOLD_FOR_LONG_TERM',
                    'message': f"⏰ {lot['ticker']}: {lot['alert']} (currently +{lot['gain_loss_pct']}%)",
                    'priority': 'high'
                })
            
            # Warning if selling short-term gain
            elif lot['status'] == 'SHORT_TERM' and lot['gain_loss_pct'] > 20:
                alerts.append({
                    'ticker': lot['ticker'],
                    'type': 'SHORT_TERM_GAIN_WARNING',
                    'message': f"💸 {lot['ticker']}: Selling now = short-term tax on +{lot['gain_loss_pct']}% gain",
                    'priority': 'medium'
                })
        
        return alerts


class DividendTracker:
    """Track dividend income and yields"""
    
    # Known dividend stocks and approximate annual yields
    DIVIDEND_STOCKS = {
        'MSFT': 0.7, 'AAPL': 0.5, 'GOOGL': 0, 'META': 0.4,
        'JPM': 2.3, 'BAC': 2.4, 'WFC': 2.5,
        'KO': 3.0, 'PEP': 2.7, 'JNJ': 2.9,
        'SPY': 1.3, 'QQQ': 0.5, 'VTI': 1.4,
        'T': 6.5, 'VZ': 6.3,
        'O': 5.5, 'SCHD': 3.5
    }
    
    def __init__(self, portfolio_data):
        self.portfolio = portfolio_data
    
    def calculate_dividend_income(self):
        """Calculate estimated annual dividend income"""
        total_div_income = 0
        dividend_positions = []
        
        for item in self.portfolio:
            ticker = item['symbol']
            current_value = item.get('current_value', 0)
            div_yield = self.DIVIDEND_STOCKS.get(ticker, 0) / 100
            
            if div_yield > 0:
                annual_income = current_value * div_yield
                dividend_positions.append({
                    'ticker': ticker,
                    'value': round(current_value, 2),
                    'yield_pct': self.DIVIDEND_STOCKS.get(ticker, 0),
                    'annual_income': round(annual_income, 2),
                    'monthly_income': round(annual_income / 12, 2)
                })
                total_div_income += annual_income
        
        return {
            'total_annual': round(total_div_income, 2),
            'total_monthly': round(total_div_income / 12, 2),
            'positions': dividend_positions,
            'yield_on_portfolio': round(
                total_div_income / sum(p['value'] for p in dividend_positions) * 100, 2
            ) if dividend_positions else 0
        }


class BenchmarkComparison:
    """Compare portfolio performance against benchmarks"""
    
    def __init__(self, portfolio_data, benchmark_data):
        self.portfolio = portfolio_data
        self.benchmarks = benchmark_data
    
    def compare(self):
        """Compare portfolio to SPY and QQQ"""
        if not self.portfolio:
            return {'vs_spy': 0, 'vs_qqq': 0, 'alpha': 0}
        
        # Calculate portfolio return
        total_invested = sum(p.get('amount_invested', 0) for p in self.portfolio)
        total_current = sum(p.get('current_value', 0) for p in self.portfolio)
        portfolio_return = ((total_current - total_invested) / total_invested * 100) if total_invested > 0 else 0
        
        spy_return = self.benchmarks.get('SPY', {}).get('change_pct', 0)
        qqq_return = self.benchmarks.get('QQQ', {}).get('change_pct', 0)
        
        return {
            'portfolio_return': round(portfolio_return, 2),
            'spy_return': spy_return,
            'qqq_return': qqq_return,
            'vs_spy': round(portfolio_return - spy_return, 2),
            'vs_qqq': round(portfolio_return - qqq_return, 2),
            'beating_spy': portfolio_return > spy_return,
            'beating_qqq': portfolio_return > qqq_return,
            'alpha': round(portfolio_return - ((spy_return + qqq_return) / 2), 2)
        }


class PriceAlertManager:
    """Manage price alerts for watchlist items"""
    
    def __init__(self, journal):
        self.alerts = journal.price_alerts if hasattr(journal, 'price_alerts') else []
    
    def check_alerts(self, watchlist_data, portfolio_data):
        """Check if any price alerts have triggered"""
        triggered = []
        all_items = {item['symbol']: item for item in watchlist_data + portfolio_data}
        
        for alert in self.alerts:
            ticker = alert['ticker']
            if ticker not in all_items:
                continue
            
            current_price = all_items[ticker]['price']
            target_price = alert.get('target_price', 0)
            direction = alert.get('direction', 'below')
            
            if direction == 'below' and current_price <= target_price:
                triggered.append({
                    'ticker': ticker,
                    'type': 'PRICE_BELOW',
                    'target': target_price,
                    'current': current_price,
                    'message': f"🎯 {ticker} dropped to ${current_price} (target: ${target_price})"
                })
            elif direction == 'above' and current_price >= target_price:
                triggered.append({
                    'ticker': ticker,
                    'type': 'PRICE_ABOVE',
                    'target': target_price,
                    'current': current_price,
                    'message': f"🚀 {ticker} reached ${current_price} (target: ${target_price})"
                })
        
        return triggered
    
    def generate_entry_alerts(self, watchlist_data):
        """Generate entry point alerts based on technicals"""
        entry_alerts = []
        
        for item in watchlist_data:
            ticker = item['symbol']
            rsi = item.get('rsi', 50)
            price = item['price']
            support = item.get('support', 0)
            
            # RSI-based entry
            if rsi <= RSI_OVERSOLD:
                entry_alerts.append({
                    'ticker': ticker,
                    'type': 'RSI_OVERSOLD',
                    'price': price,
                    'rsi': rsi,
                    'message': f"📉 {ticker} RSI at {rsi} - oversold entry zone"
                })
            
            # Support-based entry
            elif support > 0 and price <= support * 1.02:
                entry_alerts.append({
                    'ticker': ticker,
                    'type': 'NEAR_SUPPORT',
                    'price': price,
                    'support': support,
                    'message': f"🛡️ {ticker} near support ${support:.2f} - potential entry"
                })
            
            # Volume spike with dip
            elif item.get('vol_ratio', 1) > 2 and item.get('daily_change', 0) < -3:
                entry_alerts.append({
                    'ticker': ticker,
                    'type': 'VOLUME_DIP',
                    'price': price,
                    'message': f"📊 {ticker} high volume dip - watch for reversal"
                })
        
        return entry_alerts


class PositionSizer:
    """Calculate optimal position sizes based on risk"""
    
    def __init__(self, portfolio_value, risk_per_trade=RISK_PER_TRADE_PCT, max_position=MAX_POSITION_PCT):
        self.portfolio_value = portfolio_value
        self.risk_per_trade = risk_per_trade / 100
        self.max_position = max_position / 100
    
    def calculate_position_size(self, entry_price, stop_loss_price):
        """Calculate position size based on risk"""
        if entry_price <= 0 or stop_loss_price <= 0:
            return {'error': 'Invalid prices'}
        
        # Risk per share
        risk_per_share = abs(entry_price - stop_loss_price)
        risk_pct = risk_per_share / entry_price
        
        # Max $ to risk
        max_risk_dollars = self.portfolio_value * self.risk_per_trade
        
        # Position size based on risk
        risk_based_size = max_risk_dollars / risk_per_share if risk_per_share > 0 else 0
        risk_based_dollars = risk_based_size * entry_price
        
        # Cap at max position size
        max_position_dollars = self.portfolio_value * self.max_position
        
        recommended_dollars = min(risk_based_dollars, max_position_dollars)
        
        return {
            'entry_price': entry_price,
            'stop_loss': stop_loss_price,
            'risk_per_share': round(risk_per_share, 2),
            'risk_pct': round(risk_pct * 100, 1),
            'max_risk_dollars': round(max_risk_dollars, 2),
            'recommended_amount': round(recommended_dollars, 2),
            'recommended_pct': round(recommended_dollars / self.portfolio_value * 100, 1),
            'potential_loss': round(recommended_dollars * risk_pct, 2)
        }
    
    def suggest_sizes(self, watchlist_data):
        """Suggest position sizes for watchlist items"""
        suggestions = []
        
        for item in watchlist_data:
            ticker = item['symbol']
            price = item['price']
            support = item.get('support', price * 0.9)
            
            # Use support as stop loss, or -10% if no support
            stop_loss = max(support, price * 0.9)
            
            sizing = self.calculate_position_size(price, stop_loss)
            
            suggestions.append({
                'ticker': ticker,
                'current_price': price,
                'suggested_stop': round(stop_loss, 2),
                'suggested_amount': sizing['recommended_amount'],
                'risk_if_stopped': sizing['potential_loss'],
                'position_pct': sizing['recommended_pct']
            })
        
        return suggestions


class AIResearchAgent:
    """AI-powered stock research using Alpha Vantage news & sentiment API
    
    Only runs when DEEP_ANALYSIS is enabled to conserve API calls.
    Free tier: 25 calls/day
    """
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
        self.calls_made = 0
        self.max_calls = 20  # Leave buffer for free tier
    
    def can_make_call(self):
        """Check if we have API budget remaining"""
        return self.api_key and self.calls_made < self.max_calls
    
    def get_news_sentiment(self, ticker):
        """Fetch news and sentiment for a ticker from Alpha Vantage"""
        if not self.can_make_call():
            return None
        
        try:
            params = {
                'function': 'NEWS_SENTIMENT',
                'tickers': ticker,
                'limit': 10,
                'apikey': self.api_key
            }
            
            response = requests.get(self.base_url, params=params, timeout=15)
            self.calls_made += 1
            
            if response.status_code != 200:
                print(f"      ⚠️ Alpha Vantage API error: {response.status_code}")
                return None
            
            data = response.json()
            
            # Check for API limit message
            if 'Note' in data or 'Information' in data:
                print(f"      ⚠️ Alpha Vantage: {data.get('Note', data.get('Information', 'Rate limited'))}")
                return None
            
            return self._parse_sentiment_data(ticker, data)
            
        except Exception as e:
            print(f"      ⚠️ Error fetching news for {ticker}: {e}")
            return None
    
    def _parse_sentiment_data(self, ticker, data):
        """Parse Alpha Vantage sentiment response into structured data"""
        feed = data.get('feed', [])
        
        if not feed:
            return {
                'ticker': ticker,
                'news_count': 0,
                'sentiment_score': 0,
                'sentiment_label': 'NEUTRAL',
                'headlines': [],
                'ai_summary': 'No recent news found.',
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
        
        # Extract relevant news for this ticker
        headlines = []
        sentiment_scores = []
        
        for article in feed[:10]:
            # Find sentiment specific to our ticker
            ticker_sentiments = article.get('ticker_sentiment', [])
            ticker_score = 0
            
            for ts in ticker_sentiments:
                if ts.get('ticker', '').upper() == ticker.upper():
                    ticker_score = float(ts.get('ticker_sentiment_score', 0))
                    break
            
            # Use overall sentiment if ticker-specific not found
            if ticker_score == 0:
                ticker_score = float(article.get('overall_sentiment_score', 0))
            
            sentiment_scores.append(ticker_score)
            
            headlines.append({
                'title': article.get('title', '')[:100],
                'source': article.get('source', ''),
                'time': article.get('time_published', ''),
                'sentiment': ticker_score
            })
        
        # Calculate average sentiment
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
        
        # Classify sentiment
        if avg_sentiment >= 0.15:
            label = 'BULLISH'
        elif avg_sentiment <= -0.15:
            label = 'BEARISH'
        else:
            label = 'NEUTRAL'
        
        # Generate AI summary based on news
        ai_summary = self._generate_summary(ticker, headlines, avg_sentiment, label)
        
        return {
            'ticker': ticker,
            'news_count': len(headlines),
            'sentiment_score': round(avg_sentiment, 3),
            'sentiment_label': label,
            'headlines': headlines[:5],  # Top 5 headlines
            'ai_summary': ai_summary,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
    
    def _generate_summary(self, ticker, headlines, sentiment_score, sentiment_label):
        """Generate an AI-style summary based on news data"""
        if not headlines:
            return f"No recent news coverage for {ticker}."
        
        # Extract key themes from headlines
        headline_text = ' '.join([h['title'].lower() for h in headlines])
        
        # Simple keyword detection for themes
        themes = []
        if any(word in headline_text for word in ['earnings', 'revenue', 'profit', 'quarter']):
            themes.append('earnings activity')
        if any(word in headline_text for word in ['upgrade', 'downgrade', 'rating', 'analyst']):
            themes.append('analyst coverage')
        if any(word in headline_text for word in ['deal', 'acquisition', 'merger', 'partnership']):
            themes.append('M&A/partnerships')
        if any(word in headline_text for word in ['launch', 'new product', 'release', 'announce']):
            themes.append('product news')
        if any(word in headline_text for word in ['sec', 'regulation', 'lawsuit', 'investigation']):
            themes.append('regulatory concerns')
        if any(word in headline_text for word in ['ai', 'artificial intelligence', 'machine learning']):
            themes.append('AI developments')
        if any(word in headline_text for word in ['crypto', 'bitcoin', 'blockchain']):
            themes.append('crypto exposure')
        
        theme_str = ', '.join(themes) if themes else 'general market activity'
        
        # Build summary
        sentiment_desc = {
            'BULLISH': 'positive momentum with favorable coverage',
            'BEARISH': 'negative pressure with concerning headlines', 
            'NEUTRAL': 'mixed signals with balanced coverage'
        }
        
        news_recency = headlines[0]['time'][:10] if headlines else 'recently'
        
        summary = f"{ticker} showing {sentiment_desc[sentiment_label]}. "
        summary += f"Recent focus: {theme_str}. "
        summary += f"News sentiment score: {sentiment_score:.2f} ({sentiment_label}). "
        summary += f"Based on {len(headlines)} articles as of {news_recency}."
        
        return summary
    
    def analyze_portfolio(self, tickers):
        """Analyze multiple tickers and return AI insights"""
        results = {}
        
        print(f"\n--- 🤖 AI DEEP ANALYSIS ({len(tickers)} tickers) ---")
        
        if not self.api_key:
            print("   ⚠️ No Alpha Vantage API key configured")
            return results
        
        for i, ticker in enumerate(tickers):
            if not self.can_make_call():
                print(f"   ⚠️ API budget exhausted ({self.calls_made}/{self.max_calls})")
                break
            
            # Rate limiting: Alpha Vantage free tier requires 1 second between calls
            if i > 0:
                time.sleep(1.5)  # 1.5 seconds to be safe
            
            clean_ticker = ticker.upper().replace('-USD', '')
            print(f"   🔍 Analyzing {clean_ticker}...", end=' ')
            
            result = self.get_news_sentiment(clean_ticker)
            
            if result:
                results[clean_ticker] = result
                print(f"{result['sentiment_label']} ({result['news_count']} articles)")
            else:
                print("No data")
        
        print(f"   ✅ AI Analysis complete. API calls used: {self.calls_made}/{self.max_calls}")
        
        return results


class TechnicalAnalyzer:
    """Advanced technical analysis for position management"""
    
    @staticmethod
    def calculate_rsi(prices, period=14):
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        """Calculate MACD"""
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(prices, period=20, std_dev=2):
        """Calculate Bollinger Bands"""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    @staticmethod
    def detect_divergence(prices, rsi, lookback=14):
        """Detect RSI divergence (bullish or bearish)"""
        if len(prices) < lookback or len(rsi) < lookback:
            return None
        
        price_recent = prices.iloc[-lookback:]
        rsi_recent = rsi.iloc[-lookback:]
        
        # Bullish divergence: price making lower lows, RSI making higher lows
        price_trend = price_recent.iloc[-1] < price_recent.iloc[0]
        rsi_trend = rsi_recent.iloc[-1] > rsi_recent.iloc[0]
        
        if price_trend and rsi_trend:
            return "BULLISH"
        
        # Bearish divergence: price making higher highs, RSI making lower highs
        price_trend = price_recent.iloc[-1] > price_recent.iloc[0]
        rsi_trend = rsi_recent.iloc[-1] < rsi_recent.iloc[0]
        
        if price_trend and rsi_trend:
            return "BEARISH"
        
        return None
    
    @staticmethod
    def calculate_support_resistance(df, window=20):
        """Find recent support and resistance levels"""
        highs = df['High'].rolling(window=window).max()
        lows = df['Low'].rolling(window=window).min()
        
        resistance = highs.iloc[-1]
        support = lows.iloc[-1]
        
        return support, resistance
    
    @staticmethod
    def volume_analysis(df, period=10):
        """Analyze volume patterns"""
        avg_vol = df['Volume'].iloc[-period-1:-1].mean()
        recent_vol = df['Volume'].iloc[-1]
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
        
        # Check if volume is increasing on up days (accumulation) or down days (distribution)
        recent_days = df.tail(5)
        up_volume = recent_days[recent_days['Close'] > recent_days['Open']]['Volume'].sum()
        down_volume = recent_days[recent_days['Close'] < recent_days['Open']]['Volume'].sum()
        
        if up_volume > down_volume * 1.5:
            pattern = "ACCUMULATION"
        elif down_volume > up_volume * 1.5:
            pattern = "DISTRIBUTION"
        else:
            pattern = "NEUTRAL"
        
        return vol_ratio, pattern


class PositionAnalyzer:
    """Analyzes owned positions - PURE DOLLAR TRACKING
    
    Model: 
    - You invest $X on a specific date
    - System looks up stock price on that date
    - Current value = $X × (current_price / price_on_buy_date)
    
    PURE DOLLARS - no shares, no manual price entry
    """
    
    def __init__(self, ticker, position, df):
        self.ticker = ticker
        self.position = position
        self.df = df
        self.ta = TechnicalAnalyzer()
        
        # Current market price
        self.current_price = df['Close'].iloc[-1]
        
        # Amount invested (dollars)
        self.amount = position.get('amount', 0)
        
        # Get historical price from purchase date
        self.price_at_purchase = self._get_price_on_date(position.get('buy_date') or position.get('first_buy_date'))
        
        # Current value = amount × (current_price / price_at_purchase)
        if self.price_at_purchase > 0:
            self.current_value = self.amount * (self.current_price / self.price_at_purchase)
        else:
            self.current_value = self.amount
        
        self.holding_days = self._calc_holding_days()
        
        # P/L calculations - PURE DOLLAR
        self.gain_loss_dollars = self.current_value - self.amount
        self.gain_loss_pct = (self.gain_loss_dollars / self.amount) * 100 if self.amount > 0 else 0
        
        # Peak tracking (for trailing stop)
        self.peak_since_buy = self._get_peak_since_buy()
        self.drawdown_from_peak = ((self.current_price - self.peak_since_buy) / self.peak_since_buy) * 100 if self.peak_since_buy > 0 else 0
        
        # Technical indicators
        self.rsi = self.ta.calculate_rsi(df['Close']).iloc[-1]
        self.macd, self.macd_signal, self.macd_hist = self.ta.calculate_macd(df['Close'])
        self.vol_ratio, self.vol_pattern = self.ta.volume_analysis(df)
        self.support, self.resistance = self.ta.calculate_support_resistance(df)
        self.divergence = self.ta.detect_divergence(df['Close'], self.ta.calculate_rsi(df['Close']))
        
        # Trend
        sma_20 = df['Close'].rolling(window=20).mean().iloc[-1]
        sma_50 = df['Close'].rolling(window=50).mean().iloc[-1] if len(df) > 50 else sma_20
        self.trend = "UP" if self.current_price > sma_20 > sma_50 else "DOWN" if self.current_price < sma_20 < sma_50 else "SIDEWAYS"
        
        # Daily/Weekly changes
        self.daily_change = ((self.current_price - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
        if len(df) >= 7:
            self.weekly_change = ((self.current_price - df['Close'].iloc[-7]) / df['Close'].iloc[-7]) * 100
        else:
            self.weekly_change = 0
    
    def _get_price_on_date(self, date_str):
        """Get the stock price on a specific date from historical data"""
        if not date_str:
            return self.current_price
        
        try:
            # Parse date - handle multiple formats
            if 'T' in str(date_str):
                # ISO format: 2025-12-26T10:00:00Z
                buy_date = datetime.fromisoformat(str(date_str).replace('Z', '+00:00')).date()
            else:
                # Simple date: 2025-12-26
                buy_date = datetime.strptime(str(date_str)[:10], '%Y-%m-%d').date()
            
            # Look for price on or near that date in our historical data
            for idx in self.df.index:
                idx_date = idx.date() if hasattr(idx, 'date') else idx
                if idx_date >= buy_date:
                    return self.df.loc[idx, 'Close']
            
            # If date is before our data range, use earliest available
            if len(self.df) > 0:
                return self.df['Close'].iloc[0]
            
            return self.current_price
        except Exception as e:
            print(f"      Warning: Could not get historical price for {date_str}: {e}")
            return self.current_price
    
    def _calc_holding_days(self):
        """Calculate days since first purchase"""
        if not self.position.get('first_buy_date'):
            return None
        try:
            buy_date = datetime.fromisoformat(self.position['first_buy_date'].replace('Z', '+00:00'))
            return (datetime.now(timezone.utc) - buy_date).days
        except:
            return None
    
    def _get_peak_since_buy(self):
        """Get the highest price since purchase"""
        if not self.position.get('first_buy_date'):
            return self.current_price
        try:
            buy_date = datetime.fromisoformat(self.position['first_buy_date'].replace('Z', '+00:00'))
            df_since_buy = self.df[self.df.index >= buy_date.strftime('%Y-%m-%d')]
            if len(df_since_buy) > 0:
                return df_since_buy['High'].max()
            return self.current_price
        except:
            return self.current_price
    
    def calculate_risk_score(self):
        """Calculate overall risk score (0-100, higher = more risky)"""
        score = 50  # Base score
        
        # P/L impact (-20 to +20)
        if self.gain_loss_pct < -10:
            score += 15
        elif self.gain_loss_pct < -5:
            score += 8
        elif self.gain_loss_pct > 20:
            score -= 10
        elif self.gain_loss_pct > 10:
            score -= 5
        
        # RSI impact
        if self.rsi > 80:
            score += 15  # Overbought = risky to hold
        elif self.rsi > 70:
            score += 8
        elif self.rsi < 30:
            score -= 5  # Oversold = less risky
        
        # Trend impact
        if self.trend == "DOWN":
            score += 10
        elif self.trend == "UP":
            score -= 10
        
        # Volume pattern
        if self.vol_pattern == "DISTRIBUTION":
            score += 12
        elif self.vol_pattern == "ACCUMULATION":
            score -= 8
        
        # Drawdown from peak
        if self.drawdown_from_peak < -15:
            score += 15
        elif self.drawdown_from_peak < -10:
            score += 8
        
        # Divergence
        if self.divergence == "BEARISH":
            score += 10
        elif self.divergence == "BULLISH":
            score -= 10
        
        return max(0, min(100, score))
    
    def generate_signal(self):
        """Generate comprehensive trading signal for owned position"""
        is_settling = self.holding_days is not None and self.holding_days <= SETTLING_PERIOD_DAYS
        is_crypto = self.ticker.replace("-USD", "") in CRYPTO_SYMBOLS
        is_weekend = datetime.now(timezone.utc).weekday() >= 5
        risk_score = self.calculate_risk_score()
        
        signal = "HOLD"
        color = "blue"
        action = None
        priority = 0  # Higher = more urgent
        reasoning = []
        
        # Weekend check for stocks
        if is_weekend and not is_crypto:
            return {
                "signal": "⏸️ WEEKEND",
                "color": "gray",
                "action": None,
                "priority": 0,
                "reasoning": ["Market closed"],
                "risk_score": risk_score
            }
        
        # === SETTLING PERIOD ===
        if is_settling:
            if self.gain_loss_pct >= PROFIT_TIER_1:
                signal = f"🆕 NEW +{self.gain_loss_pct:.1f}% (Wait)"
                color = "green"
                reasoning.append(f"Profit {self.gain_loss_pct:.1f}% but settling")
            elif self.gain_loss_pct <= STOP_LOSS_HARD:
                signal = f"🆕 NEW {self.gain_loss_pct:.1f}% (Caution)"
                color = "red"
                reasoning.append("Significant loss during settling")
            else:
                signal = f"🆕 NEW ({self.holding_days}d)"
                color = "blue"
                reasoning.append(f"Settling period - {SETTLING_PERIOD_DAYS - self.holding_days}d remaining")
            
            return {
                "signal": signal,
                "color": color,
                "action": None,
                "priority": 0,
                "reasoning": reasoning,
                "risk_score": risk_score
            }
        
        # === SELL SIGNALS (Priority Order) ===
        
        # 1. HARD STOP LOSS - Highest priority
        if self.gain_loss_pct <= STOP_LOSS_HARD:
            signal = f"🛑 STOP LOSS {self.gain_loss_pct:.1f}%"
            color = "red"
            action = "SELL_ALL"
            priority = 100
            reasoning.append(f"Hard stop loss triggered at {STOP_LOSS_HARD}%")
            reasoning.append(f"Cut losses to preserve capital")
        
        # 2. TRAILING STOP - Protect profits
        elif self.gain_loss_pct > 0 and self.drawdown_from_peak <= -TRAILING_STOP_PCT:
            signal = f"📉 TRAILING STOP {self.gain_loss_pct:.1f}%"
            color = "orange"
            action = "SELL_HALF"
            priority = 90
            reasoning.append(f"Dropped {abs(self.drawdown_from_peak):.1f}% from peak ${self.peak_since_buy:.2f}")
            reasoning.append("Consider selling to protect remaining profits")
        
        # 3. EXTREME PROFIT - Strong sell
        elif self.gain_loss_pct >= PROFIT_TIER_4:
            signal = f"🚀 TAKE PROFIT +{self.gain_loss_pct:.1f}%"
            color = "green"
            action = "SELL_MOST"
            priority = 85
            reasoning.append(f"Exceptional gain of {self.gain_loss_pct:.1f}%")
            reasoning.append("Consider selling 75% to lock in profits")
        
        # 4. OVERBOUGHT + HIGH PROFIT - Trim
        elif self.rsi > RSI_EXTREME_OVERBOUGHT and self.gain_loss_pct >= PROFIT_TIER_2:
            signal = f"⚡ SELL RSI {self.rsi:.0f} +{self.gain_loss_pct:.1f}%"
            color = "green"
            action = "SELL_HALF"
            priority = 80
            reasoning.append(f"RSI extremely overbought at {self.rsi:.1f}")
            reasoning.append(f"Good profit of {self.gain_loss_pct:.1f}% - trim position")
        
        # 5. PROFIT TIER 3
        elif self.gain_loss_pct >= PROFIT_TIER_3:
            signal = f"💰 TRIM +{self.gain_loss_pct:.1f}%"
            color = "green"
            action = "SELL_QUARTER"
            priority = 70
            reasoning.append(f"Strong gain of {self.gain_loss_pct:.1f}%")
            reasoning.append("Consider trimming 25% of position")
        
        # 6. PROFIT TIER 2
        elif self.gain_loss_pct >= PROFIT_TIER_2:
            signal = f"💰 PROFIT +{self.gain_loss_pct:.1f}%"
            color = "green"
            action = "SELL_QUARTER"
            priority = 60
            reasoning.append(f"Solid gain of {self.gain_loss_pct:.1f}%")
            if self.rsi > RSI_OVERBOUGHT:
                reasoning.append(f"RSI overbought at {self.rsi:.1f} - good time to trim")
        
        # 7. PROFIT TIER 1 + OVERBOUGHT
        elif self.gain_loss_pct >= PROFIT_TIER_1 and self.rsi > RSI_OVERBOUGHT:
            signal = f"📊 OVERBOUGHT +{self.gain_loss_pct:.1f}%"
            color = "orange"
            action = "CONSIDER_TRIM"
            priority = 50
            reasoning.append(f"Profit {self.gain_loss_pct:.1f}% with RSI {self.rsi:.1f}")
            reasoning.append("Consider taking partial profits")
        
        # 8. BEARISH DIVERGENCE warning
        elif self.divergence == "BEARISH" and self.gain_loss_pct > 5:
            signal = f"⚠️ DIVERGENCE +{self.gain_loss_pct:.1f}%"
            color = "orange"
            action = "WATCH_CLOSELY"
            priority = 45
            reasoning.append("Bearish RSI divergence detected")
            reasoning.append("Price rising but momentum weakening")
        
        # 9. DISTRIBUTION (high volume selling)
        elif self.vol_pattern == "DISTRIBUTION" and self.gain_loss_pct > 0:
            signal = f"📊 DISTRIBUTION +{self.gain_loss_pct:.1f}%"
            color = "orange"
            action = "WATCH_CLOSELY"
            priority = 40
            reasoning.append("Volume pattern suggests selling pressure")
            reasoning.append("Watch for breakdown")
        
        # 10. SOFT STOP LOSS
        elif self.gain_loss_pct <= STOP_LOSS_SOFT:
            signal = f"⚠️ LOSS {self.gain_loss_pct:.1f}%"
            color = "red"
            action = "EVALUATE"
            priority = 75
            reasoning.append(f"Approaching stop loss at {STOP_LOSS_HARD}%")
            if self.trend == "DOWN":
                reasoning.append("Downtrend - consider cutting losses")
            elif self.rsi < RSI_OVERSOLD:
                reasoning.append(f"RSI oversold at {self.rsi:.1f} - potential bounce")
        
        # 11. WARNING LOSS
        elif self.gain_loss_pct <= STOP_LOSS_WARN:
            signal = f"👀 WATCH {self.gain_loss_pct:.1f}%"
            color = "orange"
            action = "MONITOR"
            priority = 30
            reasoning.append("Position in warning zone")
            if self.support > 0 and self.current_price < self.support * 1.02:
                reasoning.append(f"Near support at ${self.support:.2f}")
        
        # === BUY MORE SIGNALS ===
        
        # 12. ADD ON DIP - Averaging down in uptrend
        elif (self.holding_days and self.holding_days >= MIN_HOLD_FOR_ADD and
              self.gain_loss_pct <= ADD_ON_DIP_DRAWDOWN and
              self.rsi < ADD_ON_DIP_RSI and
              self.trend != "DOWN" and
              self.vol_pattern != "DISTRIBUTION"):
            signal = f"🔥 ADD ON DIP {self.gain_loss_pct:.1f}%"
            color = "green"
            action = "BUY_MORE"
            priority = 55
            reasoning.append(f"RSI oversold at {self.rsi:.1f}")
            reasoning.append(f"Consider averaging down (careful!)")
            reasoning.append(f"Only if thesis intact")
        
        # 13. BULLISH DIVERGENCE - Potential reversal
        elif self.divergence == "BULLISH" and self.gain_loss_pct < 0:
            signal = f"📈 BULLISH DIV {self.gain_loss_pct:.1f}%"
            color = "blue"
            action = "HOLD_STRONG"
            priority = 35
            reasoning.append("Bullish RSI divergence detected")
            reasoning.append("Price falling but momentum improving")
        
        # 14. ADD ON BREAKOUT - Momentum play
        elif (self.holding_days and self.holding_days >= MIN_HOLD_FOR_ADD and
              self.gain_loss_pct >= ADD_ON_BREAKOUT_PCT and
              self.current_price >= self.resistance * 0.98 and
              self.vol_ratio > VOLUME_SPIKE_RATIO and
              self.rsi < RSI_OVERBOUGHT):
            signal = f"🚀 BREAKOUT +{self.gain_loss_pct:.1f}%"
            color = "purple"
            action = "BUY_MORE"
            priority = 50
            reasoning.append("Breaking resistance with volume")
            reasoning.append("Consider adding to winner")
        
        # === HOLD SIGNALS ===
        
        # 15. ACCUMULATION - Healthy buying
        elif self.vol_pattern == "ACCUMULATION" and self.gain_loss_pct >= 0:
            signal = f"💎 STRONG +{self.gain_loss_pct:.1f}%"
            color = "blue"
            action = "HOLD"
            priority = 20
            reasoning.append("Healthy accumulation pattern")
            reasoning.append("Institutional buying detected")
        
        # 16. PROFIT TIER 1 - Hold and watch
        elif self.gain_loss_pct >= PROFIT_TIER_1:
            signal = f"💎 HOLD +{self.gain_loss_pct:.1f}%"
            color = "blue"
            action = "HOLD"
            priority = 15
            reasoning.append(f"Approaching first profit target at {PROFIT_TIER_2}%")
            reasoning.append("Let winner run")
        
        # 17. Default profitable hold
        elif self.gain_loss_pct > 0:
            signal = f"💎 HOLD +{self.gain_loss_pct:.1f}%"
            color = "blue"
            action = "HOLD"
            priority = 10
            reasoning.append("Position profitable")
            if self.trend == "UP":
                reasoning.append("Trend supportive")
        
        # 18. Default loss hold
        else:
            signal = f"💎 HOLD {self.gain_loss_pct:.1f}%"
            color = "blue"
            action = "HOLD"
            priority = 10
            reasoning.append("Minor loss - within tolerance")
            if self.rsi < RSI_OVERSOLD:
                reasoning.append(f"RSI oversold at {self.rsi:.1f} - potential bounce")
        
        return {
            "signal": signal,
            "color": color,
            "action": action,
            "priority": priority,
            "reasoning": reasoning,
            "risk_score": risk_score
        }


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
            
            # RSI
            ta = TechnicalAnalyzer()
            rsi_series = ta.calculate_rsi(df['Close'])
            current_rsi = round(rsi_series.iloc[-1], 2)
            
            # Volume analysis
            vol_ratio, vol_pattern = ta.volume_analysis(df)
            
            # Support/Resistance
            support, resistance = ta.calculate_support_resistance(df)
            
            # Price history
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
                
                # Whale activity
                elif vol_ratio > 3.5:
                    signal = "🐳 WHALE ACTIVITY"
                    color = "purple"
                    self.has_critical_news = True
                    self.log_signal(clean_ticker, "WHALE_ACTIVITY", current_price, notes=f"Volume {vol_ratio}x avg")
                
                # Strong buy - extreme oversold in uptrend
                elif current_rsi < RSI_EXTREME_OVERSOLD and trend == "UP":
                    signal = "🔥 STRONG BUY"
                    color = "green"
                    self.log_signal(clean_ticker, "STRONG_BUY", current_price, notes=f"RSI {current_rsi} in uptrend")
                
                # Buy dip - oversold
                elif current_rsi < RSI_OVERSOLD:
                    signal = "✅ BUY DIP"
                    color = "green"
                    self.log_signal(clean_ticker, "BUY_SIGNAL", current_price, notes=f"RSI oversold: {current_rsi}")
                
                # Near support with accumulation
                elif current_price <= support * 1.02 and vol_pattern == "ACCUMULATION":
                    signal = "👀 SUPPORT BUY"
                    color = "green"
                    self.log_signal(clean_ticker, "SUPPORT_BUY", current_price, notes=f"Near support ${support:.2f}")
                
                # Avoid - extreme overbought
                elif current_rsi > RSI_EXTREME_OVERBOUGHT:
                    signal = "⚠️ AVOID"
                    color = "red"
                
                # Caution - overbought
                elif current_rsi > RSI_OVERBOUGHT:
                    signal = "📊 OVERBOUGHT"
                    color = "orange"
                
                # Distribution warning
                elif vol_pattern == "DISTRIBUTION":
                    signal = "📉 DISTRIBUTION"
                    color = "orange"
                
                # Uptrend dip
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
                "vol_pattern": vol_pattern,
                "support": round(support, 2),
                "resistance": round(resistance, 2),
                "price_history": price_history,
                "is_owned": False
            }
        except Exception as e:
            print(f"   [ERROR] {ticker}: {e}")
            return None

    def fetch_data_for_position(self, ticker, position):
        """Fetch data for an owned position - PURE DOLLAR TRACKING
        
        Uses purchase date to look up historical price automatically
        """
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="3mo")
            if len(df) < 2: return None
            
            # Use PositionAnalyzer - it will look up historical price from date
            analyzer = PositionAnalyzer(ticker, position, df)
            signal_data = analyzer.generate_signal()
            
            # Check for critical signals
            if signal_data['priority'] >= 70:
                self.has_critical_news = True
                self.log_signal(
                    ticker.replace("-USD", ""),
                    signal_data['action'] or "ALERT",
                    analyzer.current_price,
                    analyzer.price_at_purchase,
                    analyzer.gain_loss_pct,
                    analyzer.holding_days,
                    "; ".join(signal_data['reasoning'][:2])
                )
            
            # Price history
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
            
            print(f"   [OWNED] {clean_ticker}: ${analyzer.amount:.2f} → ${analyzer.current_value:.2f} | "
                  f"P/L: {analyzer.gain_loss_pct:.1f}% (${analyzer.gain_loss_dollars:+.2f}) | "
                  f"{analyzer.holding_days}d | Risk: {signal_data['risk_score']}")

            return {
                "symbol": clean_ticker,
                "yf_symbol": ticker,
                "price": round(analyzer.current_price, 2),
                "amount_invested": round(analyzer.amount, 2),
                "current_value": round(analyzer.current_value, 2),
                "trend": analyzer.trend,
                "rsi": round(analyzer.rsi, 1),
                "signal": signal_data['signal'],
                "color": signal_data['color'],
                "action": signal_data['action'],
                "priority": signal_data['priority'],
                "reasoning": signal_data['reasoning'],
                "risk_score": signal_data['risk_score'],
                "whale_intel": whale_intel,
                "holding_days": analyzer.holding_days,
                "gain_loss_pct": round(analyzer.gain_loss_pct, 1),
                "gain_loss_dollars": round(analyzer.gain_loss_dollars, 2),
                "daily_change": round(analyzer.daily_change, 1),
                "weekly_change": round(analyzer.weekly_change, 2),
                "vol_ratio": round(analyzer.vol_ratio, 2),
                "vol_pattern": analyzer.vol_pattern,
                "peak_since_buy": round(analyzer.peak_since_buy, 2),
                "drawdown_from_peak": round(analyzer.drawdown_from_peak, 1),
                "support": round(analyzer.support, 2),
                "resistance": round(analyzer.resistance, 2),
                "price_history": price_history,
                "is_owned": True,
                "first_buy_date": position['first_buy_date'],
                "last_buy_date": position['last_buy_date'],
                "buy_count": position.get('buy_count', 1)
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
        
        positions = self.journal.get_positions()
        print(f"\n--- 💼 PORTFOLIO ({len(positions)} positions) ---")
        
        for ticker, position in positions.items():
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data_for_position(yf_ticker, position)
            if data:
                portfolio_data.append(data)
        
        # Sort portfolio by priority (most urgent first)
        portfolio_data.sort(key=lambda x: x.get('priority', 0), reverse=True)
        
        print(f"\n--- 👀 WATCHLIST ({len(self.journal.watchlist)} items) ---")
        
        for ticker in self.journal.watchlist:
            clean = ticker.upper().replace("-USD", "")
            if self.journal.is_owned(clean):
                continue
            yf_ticker = f"{ticker}-USD" if ticker in CRYPTO_SYMBOLS else ticker
            data = self.fetch_data_for_watchlist(yf_ticker)
            if data:
                watchlist_data.append(data)
        
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
        
        # Portfolio summary - DOLLAR BASED
        total_invested = sum(item.get('amount_invested', 0) for item in portfolio_data)
        total_current = sum(item.get('current_value', 0) for item in portfolio_data)
        total_gain_loss = total_current - total_invested
        total_gain_loss_pct = (total_gain_loss / total_invested * 100) if total_invested > 0 else 0
        avg_risk_score = sum(item.get('risk_score', 50) for item in portfolio_data) / len(portfolio_data) if portfolio_data else 0
        
        summary = {
            "total_invested": round(total_invested, 2),
            "total_current": round(total_current, 2),
            "total_gain_loss": round(total_gain_loss, 2),
            "total_gain_loss_pct": round(total_gain_loss_pct, 2),
            "position_count": len(portfolio_data),
            "avg_risk_score": round(avg_risk_score, 0)
        }
        
        # =============================================
        # NEW ANALYTICS
        # =============================================
        print("\n--- 📊 RUNNING ANALYTICS ---")
        
        # 1. DCA Analysis
        dca_tracker = DCATracker(self.journal)
        dca_analysis = {}
        for ticker in positions.keys():
            trades = self.journal.get_ticker_trades(ticker)
            dca_data = dca_tracker.analyze_dca_performance(ticker, trades)
            if dca_data:
                dca_analysis[ticker] = dca_data
        dca_suggestions = dca_tracker.get_dca_suggestions(portfolio_data, watchlist_data)
        print(f"   DCA: Analyzed {len(dca_analysis)} positions, {len(dca_suggestions)} suggestions")
        
        # 5. Performance Attribution
        perf_analyzer = PerformanceAnalyzer(self.journal, portfolio_data)
        performance_stats = perf_analyzer.calculate_stats()
        print(f"   Performance: {performance_stats['win_rate']}% win rate, ${performance_stats['net_pnl']} net P/L")
        
        # 6. Tax Lot Tracking
        tax_tracker = TaxLotTracker(self.journal)
        tax_lots = tax_tracker.analyze_tax_lots(portfolio_data)
        tax_alerts = tax_tracker.get_tax_alerts(tax_lots)
        print(f"   Tax: {len(tax_lots)} lots tracked, {len(tax_alerts)} alerts")
        
        # 7. Dividend Tracking
        div_tracker = DividendTracker(portfolio_data)
        dividend_data = div_tracker.calculate_dividend_income()
        print(f"   Dividends: ${dividend_data['total_annual']}/yr estimated")
        
        # 8. Benchmark Comparison
        benchmark_comp = BenchmarkComparison(portfolio_data, benchmarks)
        benchmark_analysis = benchmark_comp.compare()
        print(f"   Benchmark: {benchmark_analysis['portfolio_return']}% vs SPY {benchmark_analysis['spy_return']}%")
        
        # 4 & 9. Entry Point Optimizer & Price Alerts
        alert_manager = PriceAlertManager(self.journal)
        entry_alerts = alert_manager.generate_entry_alerts(watchlist_data)
        print(f"   Entry Alerts: {len(entry_alerts)} opportunities")
        
        # 10. Position Sizing
        portfolio_value = total_current if total_current > 0 else DEFAULT_PORTFOLIO_SIZE
        sizer = PositionSizer(portfolio_value)
        sizing_suggestions = sizer.suggest_sizes(watchlist_data[:10])  # Top 10 watchlist
        print(f"   Position Sizing: {len(sizing_suggestions)} suggestions")
        
        # AI DEEP ANALYSIS (only when manually triggered)
        ai_insights = {}
        if DEEP_ANALYSIS and ALPHA_VANTAGE_KEY:
            print("\n--- 🤖 AI DEEP ANALYSIS ENABLED ---")
            ai_agent = AIResearchAgent(ALPHA_VANTAGE_KEY)
            
            # Analyze portfolio positions first (priority)
            portfolio_tickers = [item['symbol'] for item in portfolio_data]
            
            # Then top watchlist items (up to API budget)
            watchlist_tickers = [item['symbol'] for item in watchlist_data[:10]]
            
            # Combine, portfolio first
            all_tickers = portfolio_tickers + [t for t in watchlist_tickers if t not in portfolio_tickers]
            
            ai_insights = ai_agent.analyze_portfolio(all_tickers)
            print(f"   🤖 AI insights generated for {len(ai_insights)} tickers")
        elif DEEP_ANALYSIS:
            print("\n--- ⚠️ DEEP ANALYSIS requested but no ALPHA_VANTAGE_KEY ---")
        
        # Signals
        existing_signals = []
        signals_file = "docs/data/signals.json"
        if os.path.exists(signals_file):
            try:
                with open(signals_file, "r") as f:
                    existing_signals = json.load(f)
            except: pass
        
        all_signals = self.recent_signals + existing_signals
        all_signals = all_signals[:20]
        
        # Combine all alerts
        all_alerts = tax_alerts + entry_alerts
        
        return {
            "generated_at": self.timestamp,
            "deep_analysis_enabled": DEEP_ANALYSIS,
            "portfolio": portfolio_data,
            "watchlist": watchlist_data,
            "benchmarks": benchmarks,
            "summary": summary,
            "recent_signals": all_signals,
            "trade_history": self.journal.trades[-10:],
            
            # AI INSIGHTS (only populated when deep analysis runs)
            "ai_insights": ai_insights,
            
            # NEW ANALYTICS DATA
            "analytics": {
                "dca": {
                    "positions": dca_analysis,
                    "suggestions": dca_suggestions
                },
                "performance": performance_stats,
                "tax_lots": tax_lots,
                "tax_alerts": tax_alerts,
                "dividends": dividend_data,
                "benchmark_comparison": benchmark_analysis,
                "entry_alerts": entry_alerts,
                "position_sizing": sizing_suggestions,
                "all_alerts": all_alerts
            },
            
            "settings": {
                "profit_tiers": [PROFIT_TIER_1, PROFIT_TIER_2, PROFIT_TIER_3, PROFIT_TIER_4],
                "stop_loss_soft": STOP_LOSS_SOFT,
                "stop_loss_hard": STOP_LOSS_HARD,
                "trailing_stop": TRAILING_STOP_PCT,
                "settling_days": SETTLING_PERIOD_DAYS,
                "max_position_pct": MAX_POSITION_PCT,
                "risk_per_trade_pct": RISK_PER_TRADE_PCT
            }
        }

    def generate_dashboard_html(self, data):
        """Generate static HTML report (email-compatible)"""
        
        current_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        def build_portfolio_rows(items):
            html_rows = ""
            
            color_map = {
                "black": "#8b949e",
                "gray": "#8b949e",  
                "green": "#3fb950",
                "red": "#f85149",
                "orange": "#d29922",
                "blue": "#58a6ff",
                "purple": "#a371f7",
            }
            
            for item in items:
                badge_color = color_map.get(item['color'], "#8b949e")
                pl_color = "#3fb950" if item.get('gain_loss_pct', 0) >= 0 else "#f85149"
                
                cell_style = "padding: 12px; border-bottom: 1px solid #30363d; color: #e6edf3; font-family: sans-serif; font-size: 14px;"
                link_style = "color: #388bfd; text-decoration: none; font-weight: bold;"
                badge_style = f"color: {badge_color}; border: 1px solid {badge_color}; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block; white-space: nowrap; font-size: 12px;"

                # Dollar-based values
                amount_invested = item.get('amount_invested', 0)
                current_value = item.get('current_value', 0)
                gain_loss_dollars = item.get('gain_loss_dollars', current_value - amount_invested)

                row = "<tr>"
                row += f'<td style="{cell_style}"><a href="https://finance.yahoo.com/quote/{item["yf_symbol"]}" style="{link_style}" target="_blank">{item["symbol"]}</a></td>'
                row += f'<td style="{cell_style}">${amount_invested:.2f}</td>'
                row += f'<td style="{cell_style}">${current_value:.2f}</td>'
                row += f'<td style="{cell_style} color: {pl_color};">{item["gain_loss_pct"]:+.1f}% (${gain_loss_dollars:+.2f})</td>'
                row += f'<td style="{cell_style}"><span style="{badge_style}">{item["signal"]}</span></td>'
                
                # Action/Reasoning
                reasoning = item.get('reasoning', [])
                action_text = reasoning[0] if reasoning else ""
                row += f'<td style="{cell_style} font-size: 12px; color: #8b949e;">{action_text}</td>'
                row += "</tr>"
                html_rows += row
            return html_rows

        def build_watchlist_rows(items):
            html_rows = ""
            
            color_map = {
                "black": "#8b949e",
                "gray": "#8b949e",  
                "green": "#3fb950",
                "red": "#f85149",
                "orange": "#d29922",
                "blue": "#58a6ff",
                "purple": "#a371f7",
            }
            
            for item in items:
                badge_color = color_map.get(item['color'], "#8b949e")
                trend_color = "#3fb950" if item['trend'] == 'UP' else "#f85149"
                
                cell_style = "padding: 12px; border-bottom: 1px solid #30363d; color: #e6edf3; font-family: sans-serif; font-size: 14px;"
                link_style = "color: #388bfd; text-decoration: none; font-weight: bold;"
                badge_style = f"color: {badge_color}; border: 1px solid {badge_color}; padding: 2px 6px; border-radius: 4px; font-weight: bold; display: inline-block; white-space: nowrap;"

                row = "<tr>"
                row += f'<td style="{cell_style}"><a href="https://finance.yahoo.com/quote/{item["yf_symbol"]}" style="{link_style}" target="_blank">{item["symbol"]}</a></td>'
                row += f'<td style="{cell_style}">${item["price"]}</td>'
                row += f'<td style="{cell_style} color: {trend_color};">{item["trend"]}</td>'
                row += f'<td style="{cell_style}">{item["rsi"]}</td>'
                row += f'<td style="{cell_style}"><span style="{badge_style}">{item["signal"]}</span></td>'
                row += f'<td style="{cell_style} font-size: 12px; color: #8b949e;">{item["whale_intel"]}</td>'
                row += "</tr>"
                html_rows += row
            return html_rows

        portfolio_html = build_portfolio_rows(data['portfolio'])
        watchlist_html = build_watchlist_rows(data['watchlist'])
        
        summary = data.get('summary', {})
        summary_color = "#3fb950" if summary.get('total_gain_loss', 0) >= 0 else "#f85149"
        
        # Risk indicator
        risk = summary.get('avg_risk_score', 50)
        risk_color = "#3fb950" if risk < 40 else "#d29922" if risk < 60 else "#f85149"
        risk_label = "LOW" if risk < 40 else "MEDIUM" if risk < 60 else "HIGH"

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
                                            <td style="color: #8b949e; font-size: 12px;">CURRENT</td>
                                            <td style="color: #8b949e; font-size: 12px;">P/L</td>
                                            <td style="color: #8b949e; font-size: 12px;">RISK</td>
                                        </tr>
                                        <tr>
                                            <td style="color: #e6edf3; font-size: 18px; font-weight: bold;">${summary.get('total_invested', 0):.2f}</td>
                                            <td style="color: #e6edf3; font-size: 18px; font-weight: bold;">${summary.get('total_current', 0):.2f}</td>
                                            <td style="color: {summary_color}; font-size: 18px; font-weight: bold;">{summary.get('total_gain_loss_pct', 0):+.1f}%</td>
                                            <td style="color: {risk_color}; font-size: 18px; font-weight: bold;">{risk_label}</td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            
                            <tr>
                                <td style="padding-top: 30px;">
                                    <h3 style="margin: 0 0 15px 0; color: #e6edf3; border-bottom: 1px solid #30363d; padding-bottom: 5px;">💼 Positions (sorted by urgency)</h3>
                                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                                        <thead>
                                            <tr>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Asset</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Invested</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Current</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">P/L</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Signal</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Action</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {portfolio_html if portfolio_html else '<tr><td colspan="6" style="padding: 20px; color: #8b949e; text-align: center;">No positions</td></tr>'}
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
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Ticker</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Price</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Trend</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">RSI</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Signal</th>
                                                <th style="text-align: left; padding: 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px;">Intel</th>
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
                                    <p>Generated by Whale Watcher Agent v2.0</p>
                                    <p>📈 Tiered profit taking | 📉 Trailing stops | 🎯 Risk scoring</p>
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
    
    os.makedirs("docs/data", exist_ok=True)
    
    data = agent.generate_json_data()
    
    json_path = "docs/data/dashboard.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"✅ JSON saved to {json_path}")
    except Exception as e:
        print(f"❌ Error writing JSON: {e}")
    
    if agent.recent_signals:
        signals_path = "docs/data/signals.json"
        try:
            with open(signals_path, "w", encoding="utf-8") as f:
                json.dump(data['recent_signals'], f, indent=2, default=str)
            print(f"✅ Signals saved to {signals_path}")
        except Exception as e:
            print(f"❌ Error writing signals: {e}")
    
    dashboard_html = agent.generate_dashboard_html(data)
    
    file_path = "index.html"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dashboard_html)
        print(f"✅ Static HTML generated at {file_path}")
    except Exception as e:
        print(f"❌ Error writing HTML: {e}")

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
