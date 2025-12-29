import smtplib
import yfinance as yf
import pandas as pd
import numpy as np
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
        return pos is not None and pos['amount_invested'] > 0
    
    def get_ticker_trades(self, ticker):
        """Get all trades for a specific ticker"""
        clean = ticker.upper().replace("-USD", "")
        return [t for t in self.trades if t['ticker'] == clean]


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
            
        return {
            "generated_at": self.timestamp,
            "portfolio": portfolio_data,
            "watchlist": watchlist_data,
            "benchmarks": benchmarks,
            "summary": summary,
            "recent_signals": all_signals,
            "trade_history": self.journal.trades[-10:],
            "settings": {
                "profit_tiers": [PROFIT_TIER_1, PROFIT_TIER_2, PROFIT_TIER_3, PROFIT_TIER_4],
                "stop_loss_soft": STOP_LOSS_SOFT,
                "stop_loss_hard": STOP_LOSS_HARD,
                "trailing_stop": TRAILING_STOP_PCT,
                "settling_days": SETTLING_PERIOD_DAYS
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
