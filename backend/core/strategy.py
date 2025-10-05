# backend/core/strategy.py
import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta, time
from typing import TYPE_CHECKING, Optional
import math
import numpy as np

# V47.14 Enhanced Dependencies with graceful fallbacks
try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    print("Warning: pandas_ta not found. Using basic supertrend calculation.")
    PANDAS_TA_AVAILABLE = False
    ta = None

try:
    from scipy.stats import linregress
    from scipy.signal import find_peaks
    SCIPY_AVAILABLE = True
except ImportError:
    print("Warning: scipy not found. Volatility analysis features disabled.")
    SCIPY_AVAILABLE = False
    linregress = None
    find_peaks = None

from .kite import kite
from .websocket_manager import ConnectionManager
from .data_manager import DataManager
from .risk_manager import RiskManager
from .trade_logger import TradeLogger
from .order_manager import OrderManager, _round_to_tick
from .database import today_engine, sql_text
# V47.14 PURE: No additional strategy imports needed

if TYPE_CHECKING:
    from .kite_ticker_manager import KiteTickerManager

def _play_sound(manager, sound): asyncio.create_task(manager.broadcast({"type": "play_sound", "payload": sound}))

INDEX_CONFIG = {
    "NIFTY": {"name": "NIFTY", "token": 256265, "symbol": "NSE:NIFTY 50", "strike_step": 50, "exchange": "NFO"},
    "SENSEX": {"name": "SENSEX", "token": 265, "symbol": "BSE:SENSEX", "strike_step": 100, "exchange": "BFO"},
}

MARKET_STANDARD_PARAMS = {
    "strategy_priority": [],  # V47.14 PURE: No strategy priority list needed
    'wma_period': 9, 'sma_period': 9, 'rsi_period': 9, 'rsi_signal_period': 3,
    'rsi_angle_lookback': 2, 'rsi_angle_threshold': 12.5, 'atr_period': 14,
    'atr_multiplier': 2.0, # ATR multiplier for stop loss calculation
    'min_atr_value': 2.5, 'ma_gap_threshold_pct': 0.5,
    'supertrend_period': 5, 'supertrend_multiplier': 0.7,
    'quantity': 25, # Default quantity for trades
    'exit_logic_mode': 'Sustained Momentum', # V47.14 exit logic mode
    'sustained_momentum_threshold_pct': 0.4, # For body expansion detection
    'rsi_momentum_window': 3, # For RSI momentum
    'entry_proximity_percent': 1.5, # V47.14 entry validation
    'breakeven_trigger_pct': 15.0, # Move to breakeven trigger
    'partial_profit_trigger_pct': 20.0, # Partial exit trigger
    'partial_exit_pct': 50.0, # Partial exit percentage
    
    # V47.14 PURE: No VPA configuration needed
}

# =================================================================
# V47.14 ENHANCED TECHNICAL INDICATORS
# =================================================================

def calculate_wma(series, length=9):
    """Weighted Moving Average calculation"""
    if len(series) < length: 
        return pd.Series(index=series.index, dtype=float)
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def calculate_rsi(series, length=9):
    """Relative Strength Index calculation"""
    if len(series) < length: 
        return pd.Series(index=series.index, dtype=float)
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    loss = loss.replace(0, 1e-10)
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(high, low, close, length=14):
    """Average True Range calculation"""
    if len(close) < length: 
        return pd.Series(index=close.index, dtype=float)
    tr = pd.concat([high - low, np.abs(high - close.shift()), np.abs(low - close.shift())], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def calculate_supertrend(df, period=5, multiplier=0.7):
    """Enhanced Supertrend calculation using pandas_ta if available"""
    if len(df) < period:
        df['supertrend'] = np.nan
        df['supertrend_uptrend'] = np.nan
        return df

    if PANDAS_TA_AVAILABLE:
        # Use pandas_ta for reliable Supertrend calculation
        st = df.ta.supertrend(length=period, multiplier=multiplier)
        df['supertrend'] = st[f'SUPERT_{period}_{multiplier}']
        # Direction is -1 for downtrend, 1 for uptrend. Convert to boolean.
        df['supertrend_uptrend'] = st[f'SUPERTd_{period}_{multiplier}'] == 1
    else:
        # Fallback to basic calculation
        hl2 = (df['high'] + df['low']) / 2
        atr = calculate_atr(df['high'], df['low'], df['close'], period)
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        # Basic supertrend logic
        supertrend = []
        uptrend = []
        
        for i in range(len(df)):
            if i == 0:
                supertrend.append(lower_band.iloc[i])
                uptrend.append(True)
            else:
                if df['close'].iloc[i] <= supertrend[i-1]:
                    supertrend.append(upper_band.iloc[i])
                    uptrend.append(False)
                else:
                    supertrend.append(lower_band.iloc[i])
                    uptrend.append(True)
        
        df['supertrend'] = supertrend
        df['supertrend_uptrend'] = uptrend
    
    return df

# =================================================================
# V47.14 ENHANCED CROSSOVER TRACKER
# =================================================================

class EnhancedCrossoverTracker:
    def __init__(self, strategy):
        self.strategy = strategy
        self.active_signals = []
        self.signal_timeout = 300  # 5 minutes tracking window

    def detect_all_crossovers(self, df):
        """Detects Supertrend flips instead of MA crossovers"""
        crossovers = []
        if len(df) < 2 or 'supertrend_uptrend' not in df.columns:
            return crossovers

        last = df.iloc[-1]
        prev = df.iloc[-2]

        curr_uptrend = last['supertrend_uptrend']
        prev_uptrend = prev['supertrend_uptrend']

        if pd.isna(curr_uptrend) or pd.isna(prev_uptrend):
            return crossovers

        strength = abs(last['close'] - last['supertrend']) if pd.notna(last['supertrend']) else 1

        # Trend flipped from Bearish to Bullish
        if prev_uptrend is False and curr_uptrend is True:
            crossovers.extend([
                {'type': 'BULLISH', 'primary_side': 'CE', 'strength': strength},
                {'type': 'BULLISH', 'alternative_side': 'PE', 'strength': strength * 0.7}
            ])
        # Trend flipped from Bullish to Bearish
        elif prev_uptrend is True and curr_uptrend is False:
            crossovers.extend([
                {'type': 'BEARISH', 'primary_side': 'PE', 'strength': strength},
                {'type': 'BEARISH', 'alternative_side': 'CE', 'strength': strength * 0.7}
            ])
        return crossovers

    def create_tracking_signals(self, crossovers):
        """Create 5-minute tracking signals"""
        current_time = datetime.now()
        for crossover in crossovers:
            for side_key in ['primary_side', 'alternative_side']:
                if side_key in crossover:
                    signal = {
                        'id': f"{crossover['type']}_{crossover[side_key]}_{current_time.strftime('%H%M%S')}",
                        'type': crossover['type'], 'side': crossover[side_key],
                        'created_at': current_time, 'expires_at': current_time + timedelta(seconds=self.signal_timeout),
                        'strength': crossover['strength'], 'priority': 'primary' if side_key == 'primary_side' else 'alternative',
                        'option_tracking': {'initial_price': None, 'price_history': [], 'momentum_confirmed': False, 'ma_position_confirmed': False}
                    }
                    self.active_signals.append(signal)
                    # Log signal creation (async call wrapped for safety)
                    try:
                        import asyncio
                        asyncio.create_task(self.strategy._log_debug("Signal Created", f"🎯 Tracking {signal['id']} for 5 minutes"))
                    except RuntimeError:
                        pass  # No event loop running

    async def enhanced_signal_monitoring(self):
        """Monitor active signals for trading opportunities"""
        current_time = datetime.now()
        for signal in self.active_signals[:]:
            if current_time > signal['expires_at']:
                self.active_signals.remove(signal)
                continue

            opt = self.strategy.get_entry_option(signal['side'])
            if not opt:
                continue

            current_price = self.strategy.data_manager.prices.get(opt['tradingsymbol'])
            if current_price:
                signal['option_tracking']['price_history'].append({'time': current_time, 'price': current_price})
                if signal['option_tracking']['initial_price'] is None:
                    signal['option_tracking']['initial_price'] = current_price

                trade_is_valid = False
                if signal['priority'] == 'primary':
                    trade_is_valid = await self.check_enhanced_option_momentum(signal, opt)
                elif signal['priority'] == 'alternative':
                    trade_is_valid = await self.check_enhanced_reversal_momentum(signal, opt)

                if trade_is_valid:
                    await self.execute_enhanced_trade(signal, opt)
                    self.active_signals.remove(signal)

    async def check_enhanced_option_momentum(self, signal, opt):
        """Check enhanced option momentum for primary signals"""
        tracking = signal['option_tracking']
        if len(tracking['price_history']) < 3:
            return False

        recent_prices = [p['price'] for p in tracking['price_history'][-5:]]
        rising_count = sum(1 for i in range(1, len(recent_prices)) if recent_prices[i] > recent_prices[i-1])
        price_momentum = rising_count >= len(recent_prices) * 0.6

        # Check acceleration
        acceleration_ok = False
        if len(recent_prices) >= 4:
            early_avg = sum(recent_prices[:2]) / 2
            late_avg = sum(recent_prices[-2:]) / 2
            acceleration = (late_avg - early_avg) / early_avg if early_avg > 0 else 0
            acceleration_ok = acceleration > 0.02

        signal_age = (datetime.now() - signal['created_at']).total_seconds()
        time_window_ok = 30 <= signal_age <= 300
        conditions = [price_momentum, acceleration_ok]

        return sum(conditions) >= 1 and time_window_ok

    async def check_enhanced_reversal_momentum(self, signal, opt):
        """Check enhanced reversal momentum for alternative signals"""
        momentum_gauntlet_passed = await self.check_enhanced_option_momentum(signal, opt)
        if not momentum_gauntlet_passed:
            return False

        # Additional reversal checks can be added here
        return True

    async def execute_enhanced_trade(self, signal, opt):
        """Execute trade from enhanced signal"""
        if not await self.strategy._is_atm_confirming(signal['side']):
            await self.strategy._log_debug("ATM Filter", f"Tracker trade for {signal['side']} blocked by ATM confirmation.")
            return

        current_price = self.strategy.data_manager.prices.get(opt['tradingsymbol'])
        if not current_price:
            return
        reason = f"Enhanced_{signal['type']}_{signal['side']}_HighConf_ST"
        await self.strategy.take_trade(reason, opt, custom_entry_price=current_price)

# =================================================================
# V47.14 PERSISTENT TREND TRACKER
# =================================================================

class PersistentTrendTracker:
    def __init__(self, strategy):
        self.strategy = strategy
        self.trend_signals = []
        self.continuation_window = 180  # 3 minutes

    async def check_extended_trend_continuation(self):
        """Check for extended trend continuation opportunities"""
        if not hasattr(self.strategy, 'trend_state') or not self.strategy.trend_state or len(self.strategy.data_manager.data_df) < 5:
            return
        current_price = self.strategy.data_manager.prices.get(self.strategy.index_symbol)
        if not current_price:
            return

        for _, candle in self.strategy.data_manager.data_df.tail(10).iterrows():
            if (self.strategy.trend_state == 'BULLISH' and current_price > candle['high']):
                await self.create_trend_continuation_signal('CE')
            elif (self.strategy.trend_state == 'BEARISH' and current_price < candle['low']):
                await self.create_trend_continuation_signal('PE')

    async def create_trend_continuation_signal(self, side):
        """Create trend continuation signal"""
        timestamp = datetime.now()
        signal_id = f"TREND_CONT_{side}_{timestamp.strftime('%H%M%S')}"
        if any(s['id'] == signal_id for s in self.trend_signals):
            return
        self.trend_signals.append({
            'id': signal_id, 'side': side, 'created_at': timestamp,
            'expires_at': timestamp + timedelta(seconds=self.continuation_window),
            'option_momentum_history': []
        })

    async def monitor_trend_signals(self):
        """Monitor trend continuation signals"""
        for signal in self.trend_signals[:]:
            if datetime.now() > signal['expires_at']:
                self.trend_signals.remove(signal)
                continue

            if not await self.strategy._is_atm_confirming(signal['side']):
                continue

            opt = self.strategy.get_entry_option(signal['side'])
            if opt and await self.check_trend_momentum(signal, opt):
                await self.strategy.take_trade(f"Enhanced_Trend_Continuation_{signal['side']}", opt)
                self.trend_signals.remove(signal)

    async def check_trend_momentum(self, signal, opt):
        """Check trend momentum for continuation signals"""
        current_price = self.strategy.data_manager.prices.get(opt['tradingsymbol'])
        if not current_price:
            return False
        signal['option_momentum_history'].append({'price': current_price})
        if len(signal['option_momentum_history']) < 3:
            return False
        recent_prices = [p['price'] for p in signal['option_momentum_history'][-3:]]
        return recent_prices[-1] > recent_prices[0]

# =================================================================
# V47.14 PURE IMPLEMENTATION (ENHANCED WITH ABOVE FEATURES)
# =================================================================


class Strategy:
    def __init__(self, params, manager: ConnectionManager, selected_index="SENSEX"):
        self.params = self._sanitize_params(params)
        self.manager = manager
        self.ticker_manager: Optional["KiteTickerManager"] = None
        self.selected_index = selected_index  # Store the selected index
        self.config = INDEX_CONFIG[selected_index]
        self.ui_update_task: Optional[asyncio.Task] = None
        self.position_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        
        self.is_backtest = False
        self.is_paused = False  # NEW: Pause state - bot runs but no new trades
        
        self.index_name, self.index_token, self.index_symbol, self.strike_step, self.exchange = \
            self.config["name"], self.config["token"], self.config["symbol"], self.config["strike_step"], self.config["exchange"]

        self.trend_candle_count = 0
        
        # CRITICAL FIX: Initialize state variables
        self._reset_state()

        # CRITICAL FIX: Initialize option instruments
        self.option_instruments = self.load_instruments()
        
        self.data_manager = DataManager(self.index_token, self.index_symbol, self.STRATEGY_PARAMS, self._log_debug, self.on_trend_update)
        self.risk_manager = RiskManager(self.params, self._log_debug)
        self.trade_logger = TradeLogger(self.db_lock)
        self.order_manager = OrderManager(self._log_debug)

        # V47.14 FULL SYSTEM: Initialize strategy coordinator
        from .entry_strategies import V47StrategyCoordinator
        self.v47_coordinator = V47StrategyCoordinator(self)
        
        self._reset_state()
        # Load instruments with retry mechanism
        self.option_instruments = self.load_instruments()
        self.last_used_expiry = self.get_weekly_expiry()
        
        # CRITICAL FIX: If expiry is None, try reloading instruments
        if self.last_used_expiry is None:
            import time
            time.sleep(1)  # Brief delay
            self.option_instruments = self.load_instruments()
            self.last_used_expiry = self.get_weekly_expiry()
            
        # V47.14 ENHANCED FEATURES
        # Volatility Breakout System
        self.atr_squeeze_detected = False
        self.squeeze_range = {'high': 0, 'low': 0}
        
        # Enhanced Tracking Systems
        self.crossover_tracker = EnhancedCrossoverTracker(self)
        self.trend_tracker = PersistentTrendTracker(self)
        
        # Additional V47.14 tracking
        self.pending_steep_signal = None
        self.trend_state = None
        self.last_analysis_time = datetime.now()
        self.analysis_frequency = 0.5  # Run enhanced analysis every 0.5 seconds

    async def _calculate_trade_charges(self, tradingsymbol, exchange, entry_price, exit_price, quantity):
        BROKERAGE_PER_ORDER = 20.0; STT_RATE = 0.001; GST_RATE = 0.18; SEBI_RATE = 10 / 1_00_00_000; STAMP_DUTY_RATE = 0.00003
        if exchange == "NFO": EXCHANGE_TXN_CHARGE_RATE = 0.00053
        elif exchange == "BFO": EXCHANGE_TXN_CHARGE_RATE = 0.000325
        else: EXCHANGE_TXN_CHARGE_RATE = 0.00053
        buy_value = entry_price * quantity; sell_value = exit_price * quantity; total_turnover = buy_value + sell_value
        brokerage = BROKERAGE_PER_ORDER * 2; stt = sell_value * STT_RATE
        exchange_charges = total_turnover * EXCHANGE_TXN_CHARGE_RATE; sebi_charges = total_turnover * SEBI_RATE
        gst = (brokerage + exchange_charges + sebi_charges) * GST_RATE; stamp_duty = buy_value * STAMP_DUTY_RATE
        return brokerage + stt + exchange_charges + gst + sebi_charges + stamp_duty

    def _reset_state(self):
        self.position = None; self.daily_gross_pnl = 0; self.daily_net_pnl = 0; self.total_charges = 0
        self.daily_profit = 0; self.daily_loss = 0; self.daily_trade_limit_hit = False
        
        # V47.14 State Variables (pure - minimal state needed)
        self.trades_this_minute = 0; self.initial_subscription_done = False
        self.token_to_symbol = {self.index_token: self.index_symbol}
        self.performance_stats = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0}
        self.exit_cooldown_until: Optional[datetime] = None; self.disconnected_since: Optional[datetime] = None
        self.next_partial_profit_level = 1; self.trend_candle_count = 0
        self.exit_mode = "Normal" # For V47.14 exit logic
        self.last_used_expiry = None  # Will be set after option_instruments are loaded
        
        # Break-even tracking state
        self.break_even_triggered = False
        
        # V47.14 FULL SYSTEM: State variables for all engines
        self.uoa_watchlist = {}
        self.atr_squeeze_detected = False
        self.squeeze_range = {'high': 0, 'low': 0}
        self.pending_steep_signal = None

    # V47.14 PURE: No VPA exit logic needed - using standard risk manager only

    async def _restore_daily_performance(self):
        # ... (This function is unchanged)
        await self._log_debug("Persistence", "Restoring daily performance from database...")
        def db_call():
            try:
                with today_engine.connect() as conn:
                    query = sql_text("SELECT SUM(pnl), SUM(charges), SUM(net_pnl), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) FROM trades")
                    return conn.execute(query).fetchone()
            except Exception as e:
                print(f"Error restoring performance: {e}"); return None
        data = await asyncio.to_thread(db_call)
        if data and data[0] is not None:
            gross_pnl, charges, net_pnl, wins, losses = data
            self.daily_gross_pnl = gross_pnl or 0; self.total_charges = charges or 0
            self.daily_net_pnl = net_pnl or 0; self.performance_stats["winning_trades"] = wins or 0
            self.performance_stats["losing_trades"] = losses or 0
            if self.performance_stats["winning_trades"] > 0:
                 self.daily_profit = self.daily_gross_pnl + abs(self.daily_loss) if self.daily_gross_pnl < 0 else self.daily_gross_pnl
            await self._log_debug("Persistence", f"Restored state: Net P&L: ₹{self.daily_net_pnl:.2f}, Trades: {(wins or 0)+(losses or 0)}")
            await self._update_ui_performance()
        else:
            await self._log_debug("Persistence", "No prior trades found for today. Starting fresh.")
    
    def _is_bullish_engulfing(self, prev, last):
        if prev is None or last is None or pd.isna(prev['open']) or pd.isna(last['open']): return False
        prev_body = abs(prev['close'] - prev['open']); last_body = abs(last['close'] - last['open'])
        return (prev['close'] < prev['open'] and last['close'] > last['open'] and
                last['close'] > prev['open'] and last['open'] < prev['close'] and
                last_body > prev_body * 0.8)

    def _is_bearish_engulfing(self, prev, last):
        if prev is None or last is None or pd.isna(prev['open']) or pd.isna(last['open']): return False
        prev_body = abs(prev['close'] - prev['open']); last_body = abs(last['close'] - last['open'])
        return (prev['close'] > prev['open'] and last['close'] < last['open'] and
                last['close'] < prev['open'] and last['open'] > prev['close'] and
                last_body > prev_body * 0.8)



    # V47.14 PURE: No ATR squeeze detection needed

    def is_price_rising(self, symbol):
        """Checks if price is rising over last 3 ticks."""
        history = self.data_manager.price_history.get(symbol, [])
        if len(history) < 3:
            return False
            
        def safe_get_price(history_item):
            """Safely extract price from history item (tuple or dict)"""
            try:
                if isinstance(history_item, tuple) and len(history_item) >= 2:
                    return history_item[1]
                elif isinstance(history_item, dict):
                    return history_item.get('price', 0)
                return 0
            except (TypeError, IndexError):
                return 0
                
        p1, p2, p3 = safe_get_price(history[-1]), safe_get_price(history[-2]), safe_get_price(history[-3])
        return p1 > p2 and p1 > p3

    def _is_price_actively_rising(self, symbol, ticks=2):
        """Checks if the price is strictly increasing over the last few ticks."""
        history = self.data_manager.price_history.get(symbol, [])
        if len(history) < ticks:
            return False

        recent_prices = [p[1] for p in history[-ticks:]]
        for i in range(1, len(recent_prices)):
            if recent_prices[i] <= recent_prices[i-1]:
                return False
        return True

    def _get_price_from_history(self, symbol, lookback_minutes):
        """Gets price from history at specified lookback time."""
        history = self.data_manager.price_history.get(symbol, [])
        if not history:
            return None

        lookback_time = datetime.now() - timedelta(minutes=lookback_minutes)

        # Iterate backwards to find the first tick at or before the lookback time
        for tick_time, price in reversed(history):
            if tick_time <= lookback_time:
                return price

        # If no tick is old enough, return the oldest available tick
        return history[0][1]

    def _is_accelerating(self, symbol, lookback_ticks=4, acceleration_factor=1.5):
        """Checks if price momentum is accelerating."""
        history = self.data_manager.price_history.get(symbol, [])
        if len(history) < lookback_ticks:
            return False

        prices = [p[1] for p in history[-lookback_ticks:]]

        recent_delta = prices[-1] - prices[-2]
        previous_delta = prices[-2] - prices[-3]

        if recent_delta <= 0 or previous_delta <= 0:
            return False

        return recent_delta > previous_delta * acceleration_factor

    def _momentum_ok(self, side, opt_sym, look=3):
        """Checks if both index and option have momentum in the right direction."""
        idx_history = self.data_manager.price_history.get(self.index_symbol, [])
        opt_history = self.data_manager.price_history.get(opt_sym, [])
        if len(idx_history) < look or len(opt_history) < look:
            return False

        def safe_get_price(history_item):
            """Safely extract price from history item (tuple or dict)"""
            try:
                if isinstance(history_item, tuple) and len(history_item) >= 2:
                    return history_item[1]
                elif isinstance(history_item, dict):
                    return history_item.get('price', 0)
                return 0
            except (TypeError, IndexError):
                return 0
            
        idx_up = sum(1 for i in range(1, look) if safe_get_price(idx_history[-i]) > safe_get_price(idx_history[-i-1]))
        opt_up = sum(1 for i in range(1, look) if safe_get_price(opt_history[-i]) > safe_get_price(opt_history[-i-1]))

        required_up_ticks = math.ceil((look - 1) / 2)

        if side == 'CE':
            return idx_up >= required_up_ticks and opt_up >= required_up_ticks
        else:
            return ((look - 1) - idx_up) >= required_up_ticks and opt_up >= required_up_ticks









    # =================================================================
    # V47.14 VALIDATION HELPER METHODS (EXACT IMPLEMENTATION)
    # =================================================================





    # =================================================================
    # V47.14 UNIVERSAL VALIDATION GAUNTLET - 3 LAYER SYSTEM
    # =================================================================
    
    async def _enhanced_validate_entry_conditions_with_candle_color(self, side, opt, is_reversal=False, is_counter_trend=False):
        """
        V47.14 Universal Validation Gauntlet - 3 Layer Validation System
        
        Layer 1: Enhanced ATM Confirmation
        Layer 2: Option Candle & Price Structure  
        Layer 3: Micro-Momentum Checks
        """
        symbol = opt['tradingsymbol']
        
        # LAYER 1: Enhanced ATM Confirmation
        if not await self._enhanced_atm_confirmation(side, is_reversal):
            await self._log_debug("Validation Layer 1", f"ATM confirmation failed for {side}")
            return False
        
        # LAYER 2: Option Candle & Price Structure
        if not await self._validate_option_candle_structure(side, symbol, opt):
            await self._log_debug("Validation Layer 2", f"Option candle structure failed for {symbol}")
            return False
            
        # LAYER 3: Micro-Momentum Checks
        momentum_requirement = 0.8 if is_counter_trend else 0.6  # Stricter for counter-trend
        if not await self._validate_micro_momentum(side, symbol, momentum_requirement):
            await self._log_debug("Validation Layer 3", f"Micro-momentum failed for {symbol}")
            return False
        
        await self._log_debug("Validation Complete", f"All 3 layers passed for {symbol}")
        return True
    
    async def _enhanced_atm_confirmation(self, side, is_reversal=False):
        """Layer 1: Enhanced ATM Confirmation with adaptive parameters"""
        lookback_minutes = 1 if is_reversal else 3
        performance_spread = 1.0 if is_reversal else 2.0

        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot:
            return False

        atm_strike = self.strike_step * round(spot / self.strike_step)
        atm_ce_opt = self.get_entry_option('CE', atm_strike)
        atm_pe_opt = self.get_entry_option('PE', atm_strike)

        if not (atm_ce_opt and atm_pe_opt):
            return False

        atm_ce_symbol = atm_ce_opt['tradingsymbol']
        atm_pe_symbol = atm_pe_opt['tradingsymbol']

        ce_current_price = self.data_manager.prices.get(atm_ce_symbol)
        pe_current_price = self.data_manager.prices.get(atm_pe_symbol)
        ce_past_price = self._get_price_from_history(atm_ce_symbol, lookback_minutes)
        pe_past_price = self._get_price_from_history(atm_pe_symbol, lookback_minutes)

        if not all([ce_current_price, pe_current_price, ce_past_price, pe_past_price]):
            return False

        ce_pct_change = ((ce_current_price - ce_past_price) / ce_past_price) * 100 if ce_past_price > 0 else 0
        pe_pct_change = ((pe_current_price - pe_past_price) / pe_past_price) * 100 if pe_past_price > 0 else 0

        spread = ce_pct_change - pe_pct_change

        if side == 'CE':
            return spread >= performance_spread
        elif side == 'PE':
            return spread <= -performance_spread

        return False
    
    async def _validate_option_candle_structure(self, side, symbol, opt):
        """Layer 2: Option Candle & Price Structure Validation"""
        current_price = self.data_manager.prices.get(symbol)
        if not current_price:
            return False
        
        # Get option candle data
        option_candle = self.data_manager.option_candles.get(symbol, {})
        if not option_candle or 'open' not in option_candle:
            return False
            
        open_price = option_candle.get('open')
        prev_close = option_candle.get('prev_close')
        
        if not open_price or not prev_close:
            return False
        
        # Check 1: Price > Previous Close
        if current_price <= prev_close:
            return False
            
        # Check 2: Green Candle Confirmation (current_price > open_price)
        if current_price <= open_price:
            return False
        
        # Check 3: Proximity Check (not chasing too far)
        entry_proximity_percent = self.params.get('entry_proximity_percent', 1.5)
        max_entry_price = prev_close * (1 + entry_proximity_percent / 100)
        if current_price > max_entry_price:
            return False
        
        # Check 4: Breakout Confirmation
        prev_high = option_candle.get('prev_high', 0)
        prev_low = option_candle.get('prev_low', 0)
        
        # High breakout OR higher low structure
        high_breakout_confirmed = current_price > prev_high
        higher_low_momentum_confirmed = (current_price > prev_low and 
                                       current_price > open_price * 1.005)  # 0.5% above open
        
        if not (high_breakout_confirmed or higher_low_momentum_confirmed):
            return False
        
        return True
    
    async def _validate_micro_momentum(self, side, symbol, momentum_requirement=0.6):
        """Layer 3: Micro-Momentum Validation with acceleration and sync checks"""
        
        # Check 1: Active Price Rise (last 3 ticks rising)
        if not self.is_price_rising(symbol):
            return False
        
        # Check 2: Acceleration Check
        if not self._is_accelerating(symbol):
            return False
            
        # Check 3: Index & Option Momentum Sync
        if not self._momentum_ok(side, symbol):
            return False
        
        # Check 4: Momentum Strength (percentage of rising ticks)
        recent_prices = self.data_manager.price_history.get(symbol, [])
        if len(recent_prices) < 5:
            return False
            
        rising_count = sum(1 for i in range(1, len(recent_prices)) 
                          if recent_prices[i] > recent_prices[i-1])
        
        momentum_ratio = rising_count / (len(recent_prices) - 1)
        
        return momentum_ratio >= momentum_requirement
    
    def is_price_rising(self, symbol, lookback=3):
        """Check if last N price ticks are consistently rising"""
        recent_prices = self.data_manager.price_history.get(symbol, [])
        if len(recent_prices) < lookback + 1:
            return False
        
        for i in range(-lookback, 0):
            if recent_prices[i] <= recent_prices[i-1]:
                return False
        return True
    
    def _is_accelerating(self, symbol):
        """Check if rate of price increase is speeding up"""
        recent_prices = self.data_manager.price_history.get(symbol, [])
        if len(recent_prices) < 4:
            return False
        
        # Calculate rate of change for last 2 intervals
        rate1 = recent_prices[-2] - recent_prices[-3]
        rate2 = recent_prices[-1] - recent_prices[-2]
        
        # Acceleration = rate is increasing
        return rate2 > rate1
    
    def _momentum_ok(self, side, option_symbol):
        """Verify index and option momentum are aligned"""
        index_prices = self.data_manager.price_history.get(self.index_symbol, [])
        option_prices = self.data_manager.price_history.get(option_symbol, [])
        
        if len(index_prices) < 3 or len(option_prices) < 3:
            return False
        
        # Check last 2 moves
        index_rising = index_prices[-1] > index_prices[-2] and index_prices[-2] > index_prices[-3]
        option_rising = option_prices[-1] > option_prices[-2] and option_prices[-2] > option_prices[-3]
        
        # For CE: both should be rising, For PE: index falling, option rising
        if side == 'CE':
            return index_rising and option_rising
        else:  # PE
            index_falling = not index_rising
            return index_falling and option_rising

    # Legacy method for backward compatibility
    async def _is_atm_confirming(self, side, is_reversal=False):
        """Legacy ATM confirmation - redirects to enhanced version"""
        return await self._enhanced_atm_confirmation(side, is_reversal)



    # =================================================================
    # V47.14 CORE STRATEGY METHODS (EXACT IMPLEMENTATION)
    # =================================================================
    
    # =================================================================
    # V47.14 VOLATILITY BREAKOUT SYSTEM
    # =================================================================
    
    async def _check_atr_squeeze(self, lookback_period=30, squeeze_range_candles=5):
        """V47.14 Enhanced: ATR Squeeze Detection Logic"""
        if len(self.data_manager.data_df) < lookback_period or 'atr' not in self.data_manager.data_df.columns:
            return False

        # Look at the last N periods of ATR
        recent_atr = self.data_manager.data_df['atr'].tail(lookback_period)

        # Check if the latest ATR value is the minimum in the recent period
        current_atr = recent_atr.iloc[-1]
        if current_atr <= recent_atr.min():
            if not self.atr_squeeze_detected:
                await self._log_debug("Volatility", f"ATR Squeeze Detected. Volatility at {lookback_period}-min low. Watching for breakout.")
                self.atr_squeeze_detected = True

                # Define the breakout range from the last few candles
                squeeze_candles = self.data_manager.data_df.tail(squeeze_range_candles)
                self.squeeze_range['high'] = squeeze_candles['high'].max()
                self.squeeze_range['low'] = squeeze_candles['low'].min()
                
            return True
        else:
            # If ATR is no longer at its low, reset the flag
            if self.atr_squeeze_detected:
                self.atr_squeeze_detected = False
                await self._log_debug("Volatility", "ATR squeeze condition ended")
            return False

    async def check_volatility_breakout_trade(self, log=False):
        """V47.14 Enhanced: Volatility Breakout Entry Logic"""
        if not self.atr_squeeze_detected:
            return False

        current_price = self.data_manager.prices.get(self.index_symbol)
        if not current_price:
            return False

        breakout_side = None
        if current_price > self.squeeze_range['high']:
            breakout_side = 'CE'
        elif current_price < self.squeeze_range['low']:
            breakout_side = 'PE'

        if breakout_side:
            trigger = f"Volatility_Breakout_{breakout_side}"
            await self._log_debug("Signal", f"{trigger} signal generated from squeeze range {self.squeeze_range}.")

            # Use relaxed rules for a breakout, similar to a reversal
            if not await self._is_atm_confirming(breakout_side):
                if log: 
                    await self._log_debug("ATM Filter", f"{trigger} blocked by ATM confirmation.")
                return False

            opt = self.get_entry_option(breakout_side)
            if opt:
                await self.take_trade(trigger, opt)
                self.atr_squeeze_detected = False # Reset after taking trade
                return True
        return False

    async def check_enhanced_supertrend_flip_trade(self, log=False):
        """V47.14 Enhanced: Checks for Supertrend flips"""
        if len(self.data_manager.data_df) < 2 or 'supertrend_uptrend' not in self.data_manager.data_df.columns:
            return False

        last = self.data_manager.data_df.iloc[-1]
        prev = self.data_manager.data_df.iloc[-2]

        curr_uptrend = last['supertrend_uptrend']
        prev_uptrend = prev['supertrend_uptrend']

        if pd.isna(curr_uptrend) or pd.isna(prev_uptrend):
            return False

        flip_signals = []
        # Flipped to Bullish
        if prev_uptrend is False and curr_uptrend is True and last['close'] > last['open']:
            flip_signals.extend([('CE', "Enhanced_Supertrend_Flip_CE"), ('PE', "Enhanced_Supertrend_Flip_PE_Alt")])
        # Flipped to Bearish
        elif prev_uptrend is True and curr_uptrend is False and last['close'] < last['open']:
            flip_signals.extend([('PE', "Enhanced_Supertrend_Flip_PE"), ('CE', "Enhanced_Supertrend_Flip_CE_Alt")])

        for side, trigger in flip_signals:
            if not await self._is_atm_confirming(side):
                if log: 
                    await self._log_debug("ATM Filter", f"Supertrend Flip signal for {side} blocked by ATM confirmation.")
                continue

            opt = self.get_entry_option(side)
            if opt:
                await self.take_trade(trigger, opt)
                return True
        return False

    async def check_enhanced_trend_continuation(self, log=False):
        """V47.14 Enhanced: Check trend continuation with enhanced logic"""
        if not self.trend_state or len(self.data_manager.data_df) < 2 or not self.trend_candle_count >= 1:
            return False
        current_price = self.data_manager.prices.get(self.index_symbol)
        if not current_price:
            return False

        for _, candle in self.data_manager.data_df.tail(5).iterrows():
            if (self.trend_state == 'BULLISH' and current_price > candle['high']) or (self.trend_state == 'BEARISH' and current_price < candle['low']):
                if self.trend_state == 'BULLISH':
                    sides = [('CE', 'Primary'), ('PE', 'Alt')]
                else:
                    sides = [('PE', 'Primary'), ('CE', 'Alt')]

                for side, priority in sides:
                    if not await self._is_atm_confirming(side):
                        if log: 
                            await self._log_debug("ATM Filter", f"Trend Continuation for {side} blocked by ATM confirmation.")
                        continue

                    opt = self.get_entry_option(side)
                    if opt:
                        await self.take_trade(f'Trend_Continuation_{side}', opt)
                        return True
        return False

    async def check_steep_reentry(self):
        """V47.14 Enhanced: Check steep reentry based on Supertrend trend state"""
        if len(self.data_manager.data_df) < 1 or not self.trend_state:
            return
        last = self.data_manager.data_df.iloc[-1]
        is_bullish_candle = last['close'] > last['open']

        # If trend is Bullish but we get a red candle, look for a PE (reversal)
        if self.trend_state == 'BULLISH' and not is_bullish_candle:
            self.pending_steep_signal = {'side': 'PE', 'reason': 'Reversal_PE_ST'}
        # If trend is Bearish but we get a green candle, look for a CE (reversal)
        elif self.trend_state == 'BEARISH' and is_bullish_candle:
            self.pending_steep_signal = {'side': 'CE', 'reason': 'Reversal_CE_ST'}

    async def check_pending_steep_signal(self):
        """V47.14 Enhanced: Check pending steep signals"""
        if not self.pending_steep_signal or len(self.data_manager.data_df) == 0:
            return
        signal = self.pending_steep_signal
        self.pending_steep_signal = None

        if not await self._is_atm_confirming(signal['side']):
            await self._log_debug("ATM Filter", f"Steep Re-entry for {signal['side']} blocked by ATM confirmation.")
            return

        opt = self.get_entry_option(signal['side'])
        if opt:
            await self.take_trade(signal['reason'], opt)

    # =================================================================
    # V47.14 ENHANCED ANALYSIS SYSTEM
    # =================================================================

    async def run_enhanced_intra_candle_analysis(self):
        """V47.14 Enhanced: Run enhanced intra-candle analysis"""
        if not await self.is_trade_allowed():
            return

        if self.trades_this_minute >= 4 or len(self.data_manager.data_df) < 3:
            return
            
        # Enhanced crossover detection and tracking
        crossovers = self.crossover_tracker.detect_all_crossovers(self.data_manager.data_df)
        if crossovers:
            await self.crossover_tracker.create_tracking_signals(crossovers)
        await self.crossover_tracker.enhanced_signal_monitoring()
        
        # Persistent trend tracking
        await self.trend_tracker.check_extended_trend_continuation()
        await self.trend_tracker.monitor_trend_signals()

    async def run_analysis_and_checks(self):
        """V47.14 Enhanced: Run analysis and checks with enhanced features"""
        if self.pending_steep_signal:
            await self.check_pending_steep_signal()
        await self.check_trade_entry()

    async def is_trade_allowed(self):
        """V47.14: Check if trading is allowed based on various conditions"""
        # Check if we already have a position
        if self.position is not None:
            return False
            
        # Check if daily trade limit hit
        if self.daily_trade_limit_hit:
            return False
            
        # Check if bot is paused
        if self.is_paused:
            return False
            
        # Check exit cooldown
        if self.exit_cooldown_until and datetime.now() < self.exit_cooldown_until:
            return False
            
        # Check trades per minute limit
        max_trades_per_min = self.params.get("max_trades_per_minute", 2)
        if self.trades_this_minute >= max_trades_per_min:
            return False
        
        # Check daily SL/PT limits
        daily_sl = self.params.get("daily_sl", 0)
        daily_pt = self.params.get("daily_pt", 0)
        
        if (daily_sl < 0 and self.daily_net_pnl <= daily_sl) or (daily_pt > 0 and self.daily_net_pnl >= daily_pt):
            if not self.daily_trade_limit_hit:
                self.daily_trade_limit_hit = True
                await self._log_debug("Risk Mgmt", f"Daily SL/PT Limit Hit. PnL: {self.daily_net_pnl:.2f}. Halting trades.")
            return False
        
        # Check if we have enough data
        if len(self.data_manager.data_df) < 20:
            return False
            
        return True

    async def check_trade_entry(self):
        """V47.14 FULL SYSTEM: Entry logic via coordinator"""
        # All entry logic now handled by V47StrategyCoordinator
        # This method kept for compatibility - coordinator handles all entries in tick handler
        pass
            
    async def run_basic_analysis(self):
        """V47.14 FULL SYSTEM: Analysis handled by coordinator"""
        # Check ATR squeeze conditions for volatility breakout engine
        await self._check_atr_squeeze()
        
    async def reload_params(self):
        await self._log_debug("System", "Live reloading of strategy parameters requested...")
        new_params = self.STRATEGY_PARAMS; self.data_manager.strategy_params = new_params
        await self._log_debug("System", "Strategy parameters have been reloaded successfully."); return new_params

    async def run(self):
        await self._log_debug("System", "Strategy instance created.")
        await self.data_manager.bootstrap_data()
        await self._restore_daily_performance()
        self.exit_cooldown_until = datetime.now() + timedelta(seconds=5)
        await self._log_debug("System", "Initial 5-second startup wait initiated. No trades will be taken.")
        if not self.ui_update_task or self.ui_update_task.done():
            self.ui_update_task = asyncio.create_task(self.periodic_ui_updater())
    
    async def periodic_ui_updater(self):
        while True:
            try:
                if self.position and (not self.ticker_manager or not self.ticker_manager.is_connected):
                    if self.disconnected_since is None:
                        self.disconnected_since = datetime.now()
                        await self._log_debug("CRITICAL", "Ticker disconnected in trade! Starting 15s failsafe timer.")
                    if datetime.now() - self.disconnected_since > timedelta(seconds=15):
                        await self._log_debug("CRITICAL", "Failsafe triggered! Exiting position due to prolonged disconnection.")
                        await self.exit_position("Failsafe: Ticker Disconnected"); continue
                elif self.ticker_manager and self.ticker_manager.is_connected:
                    if self.disconnected_since is not None:
                        await self._log_debug("INFO", "Ticker reconnected, failsafe timer cancelled.")
                        self.disconnected_since = None
                    if self.position and datetime.now().time() >= time(15, 15):
                        await self._log_debug("RISK", f"EOD square-off time reached. Exiting position.")
                        await self.exit_position("End of Day Auto-Square Off"); continue
                    await self._update_ui_status()
                    await self._update_ui_option_chain()
                    await self._update_ui_chart_data()
                    await self._update_ui_straddle_monitor()
                    await self._update_ui_entry_signals()
                await asyncio.sleep(1)
            except asyncio.CancelledError: await self._log_debug("UI Updater", "Task cancelled."); break
            except Exception as e: await self._log_debug("UI Updater Error", f"An error occurred: {e}"); await asyncio.sleep(5)

    async def take_trade(self, trigger, opt):
        async with self.position_lock:
            if self.position or not opt: return
        
        instrument_token = opt.get("instrument_token")
        symbol, side, price, lot_size = opt["tradingsymbol"], opt["instrument_type"], self.data_manager.prices.get(opt["tradingsymbol"]), opt.get("lot_size")
        
        # V47.14 PURE: Simple ATM confirmation check
        if not await self._is_atm_confirming(side):
            await self._log_debug("Final Check", f"ABORTED {trigger}: ATM confirmation failed for {symbol}.")
            return
        
        qty, initial_sl_price = self.risk_manager.calculate_trade_details(price, lot_size)
        
        if qty is None or instrument_token is None: 
            await self._log_debug("Trade Rejected", "Could not calculate quantity or find instrument token.")
            return
            
        try:
            if self.params.get("trading_mode") == "Live Trading":
                # v47.14: Use order chasing for better fills
                freeze_limit = 900 if self.exchange == "NFO" else 1000  # NFO default, BFO different
                
                order_result = await self.order_manager.execute_order_with_chasing(
                    tradingsymbol=symbol,
                    total_qty=qty,
                    product=kite.PRODUCT_MIS,
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    exchange=self.exchange,
                    freeze_limit=freeze_limit
                )
                
                if order_result.get('status') == 'COMPLETE':
                    price = order_result['avg_price']  # Use actual fill price
                    await self._log_debug("LIVE TRADE", f"✅ Confirmed BUY for {symbol}. Qty: {qty} @ Avg Price: {price:.2f}. Reason: {trigger}")
                else:
                    await self._log_debug("LIVE TRADE", f"Order FAILED for {symbol}. Reason: {order_result.get('reason')}")
                    return  # Abort trade entry
            else:
                await self._log_debug("PAPER TRADE", f"Simulating BUY order for {symbol}. Qty: {qty} @ Price: {price:.2f}.Reason: {trigger}")
            
            self.position = {"symbol": symbol, "entry_price": price, "direction": side, "qty": qty, "trail_sl": round(initial_sl_price, 2), "max_price": price, "trigger_reason": trigger, "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lot_size": lot_size}
            
            # Reset break-even state for new trade
            self.break_even_triggered = False
            
            if self.ticker_manager:
                await self._log_debug("WebSocket", f"Subscribing to active trade token: {instrument_token}")
                self.ticker_manager.subscribe([instrument_token])
                
            self.trades_this_minute += 1
            self.performance_stats["total_trades"] += 1
            self.next_partial_profit_level = 1
            _play_sound(self.manager, "entry")
            await self._update_ui_trade_status()
            
        except Exception as e:
            await self._log_debug("CRITICAL-ENTRY-FAIL", f"Failed to execute entry for {symbol}: {e}")
            _play_sound(self.manager, "loss")

    async def exit_position(self, reason):
        # ... (This function is unchanged, it correctly does not use recovery logic anymore)
        if not self.position: return
        p = self.position; exit_price = self.data_manager.prices.get(p["symbol"], p["max_price"])
        try:
            if self.params.get("trading_mode") == "Live Trading":
                await self._log_debug("LIVE TRADE", f"Executing SELL order for {p['symbol']}. Reason: {reason}")
                
                # v47.14: Use order chasing for exits too
                freeze_limit = 900 if self.exchange == "NFO" else 1000
                
                exit_result = await self.order_manager.execute_order_with_chasing(
                    tradingsymbol=p["symbol"],
                    total_qty=p["qty"],
                    product=kite.PRODUCT_MIS,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    exchange=self.exchange,
                    freeze_limit=freeze_limit
                )
                
                if exit_result.get('status') == 'COMPLETE':
                    exit_price = exit_result['avg_price']  # Use actual exit price
                    await self._log_debug("LIVE TRADE", f"✅ Confirmed SELL for {p['symbol']}. Qty: {p['qty']} @ Avg Price: {exit_price:.2f}")
                else:
                    await self._log_debug("LIVE TRADE", f"EXIT FAILED for {p['symbol']}. Reason: {exit_result.get('reason')}")
                    # Continue with exit logic even if order failed - we need to update internal state
            else:
                await self._log_debug("PAPER TRADE", f"Simulating SELL order for {p['symbol']}. Reason: {reason}")
            gross_pnl = (exit_price - p["entry_price"]) * p["qty"]
            charges = await self._calculate_trade_charges(tradingsymbol=p["symbol"], exchange=self.exchange, entry_price=p["entry_price"], exit_price=exit_price, quantity=p["qty"])
            net_pnl = gross_pnl - charges
            self.daily_gross_pnl += gross_pnl; self.total_charges += charges; self.daily_net_pnl += net_pnl
            if gross_pnl > 0: self.performance_stats["winning_trades"] += 1; self.daily_profit += gross_pnl; _play_sound(self.manager, "profit")
            else: self.performance_stats["losing_trades"] += 1; self.daily_loss += gross_pnl; _play_sound(self.manager, "loss")
            final_pnl = round(gross_pnl, 2); final_charges = round(charges, 2); final_net_pnl = round(net_pnl, 2)
            if not all(isinstance(v, (int, float)) for v in [p["entry_price"], exit_price, final_pnl, final_charges, final_net_pnl]):
                await self._log_debug("CRITICAL-LOG-FAIL", f"Aborting trade log for {p['symbol']} due to invalid numeric data.")
                _play_sound(self.manager, "warning"); self.position = None; self.exit_cooldown_until = datetime.now() + timedelta(seconds=5)
                await self._update_ui_trade_status(); await self._update_ui_performance()
                return
            log_info = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": p["qty"], "pnl": final_pnl, "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.data_manager.trend_state, "atr": round(self.data_manager.data_df.iloc[-1]["atr"], 2) if not self.data_manager.data_df.empty else 0, "charges": final_charges, "net_pnl": final_net_pnl }
            await self.trade_logger.log_trade(log_info)
            await self._log_debug("Database", f"Trade for {p['symbol']} logged successfully.")
            await self.manager.broadcast({"type": "new_trade_log", "payload": log_info})
            self.position = None; self.exit_cooldown_until = datetime.now() + timedelta(seconds=5)
            await self._log_debug("System", "Exit cooldown initiated for 5 seconds.")
            await self._update_ui_trade_status(); await self._update_ui_performance()
        except Exception as e:
            await self._log_debug("CRITICAL-EXIT-FAIL", f"FAILED TO EXIT {p['symbol']}! MANUAL INTERVENTION REQUIRED! Error: {e}"); _play_sound(self.manager, "warning")

    async def evaluate_exit_logic(self):
        """
        Sustained Momentum Adaptive SL Logic from lv35.py + v47.14 Red Candle Exit
        
        Two modes:
        1. Normal Mode: Standard trailing SL
        2. Sustained Momentum Mode: Activated when candle shows body expansion + higher lows
           - Dynamic SL based on candle low (not fixed percentage)
           - Adapts to price structure
        """
        async with self.position_lock:
            if not self.position: return
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"])
            if ltp is None: return

            # --- Layer 0: TRADE PROFIT TARGET (Fixed Amount) ---
            # Exit if trade profit reaches target amount
            trade_profit_target = self.params.get("trade_profit_target", 0)
            if trade_profit_target > 0:
                current_profit = (ltp - p["entry_price"]) * p["qty"]
                if current_profit >= trade_profit_target:
                    await self._log_debug("Exit Logic", f"TRADE PROFIT TARGET HIT: Profit ₹{current_profit:.2f} >= Target ₹{trade_profit_target}")
                    await self.exit_position(f"Trade Profit Target (₹{current_profit:.0f})")
                    return

            # --- Layer 0.5: BREAK EVEN TRIGGER ---
            # Move SL to break-even when profit reaches BE%
            break_even_percent = self.params.get("break_even_percent", 0)
            if break_even_percent > 0 and not self.break_even_triggered:
                profit_pct = ((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0
                if profit_pct >= break_even_percent:
                    self.break_even_triggered = True
                    p["break_even_price"] = p["entry_price"]  # Set break-even at entry price
                    await self._log_debug("Break Even", f"🎯 BREAK EVEN TRIGGERED: Profit {profit_pct:.1f}% >= {break_even_percent}%. SL moved to entry price ₹{p['entry_price']:.2f}")

            # --- Layer 1: RED CANDLE EXIT RULE (from v47.14) ---
            # Instant exit if option candle turns red
            current_candle = self.data_manager.option_candles.get(p['symbol'])
            if current_candle and 'open' in current_candle:
                candle_open = current_candle.get('open')
                # For ANY option we have BOUGHT (CE or PE), exit if its candle turns red
                if candle_open and ltp < candle_open:
                    await self._log_debug("Exit Logic", f"🔴 RED CANDLE DETECTED: {p['symbol']} LTP {ltp:.2f} < Open {candle_open:.2f}")
                    await self.exit_position("Red Candle Exit")
                    return

            df = self.data_manager.data_df
            if len(df) < 2:
                return

            # Get current and previous candles
            last_candle = df.iloc[-1]
            prev_candle = df.iloc[-2] if len(df) >= 2 else None

            # Calculate candle bodies
            last_body = abs(last_candle['close'] - last_candle['open'])
            prev_body = abs(prev_candle['close'] - prev_candle['open']) if prev_candle is not None else 0

            # Detect Sustained Momentum conditions
            body_expanding = last_body > prev_body
            
            # For CE (calls): Check for higher lows
            # For PE (puts): Check for lower highs (inverted logic)
            if p['direction'] == 'CE':
                structure_favorable = (prev_candle is not None and 
                                      last_candle['low'] >= prev_candle['low'])
            else:  # PE
                structure_favorable = (prev_candle is not None and 
                                      last_candle['high'] <= prev_candle['high'])

            # Mode switching logic
            if body_expanding and structure_favorable:
                if self.exit_mode != "Sustained Momentum":
                    self.exit_mode = "Sustained Momentum"
                    await self._log_debug("Exit Mode", "Switched to Sustained Momentum mode (body expansion + favorable structure)")
            else:
                if self.exit_mode == "Sustained Momentum":
                    self.exit_mode = "Normal"
                    await self._log_debug("Exit Mode", "Switched to Normal mode")

            # Update trailing SL based on mode
            if self.exit_mode == "Sustained Momentum":
                # In sustained momentum, use candle low/high as dynamic SL
                if p['direction'] == 'CE':
                    # For CE: SL at last candle's low
                    new_sl = last_candle['low']
                    # Get option price equivalent - estimate based on index movement
                    index_price = self.data_manager.prices.get(self.strategy.index_symbol)
                    if index_price:
                        index_move_from_low = index_price - last_candle['low']
                        # Rough approximation: option moves ~0.5x index for ATM
                        # This is a simplification; actual delta varies
                        option_sl_estimate = ltp - (index_move_from_low * 0.5)
                        p['trail_sl'] = max(p.get('trail_sl', 0), option_sl_estimate)
                else:  # PE
                    # For PE: SL at last candle's high
                    new_sl = last_candle['high']
                    index_price = self.data_manager.prices.get(self.strategy.index_symbol)
                    if index_price:
                        index_move_from_high = last_candle['high'] - index_price
                        option_sl_estimate = ltp - (index_move_from_high * 0.5)
                        p['trail_sl'] = max(p.get('trail_sl', 0), option_sl_estimate)
                
                await self._log_debug("SL Update", f"Sustained Momentum SL updated to {p['trail_sl']:.2f}")

            else:  # Normal Mode
                if ltp > p["max_price"]: 
                    p["max_price"] = ltp
                
                sl_points = float(self.params.get("trailing_sl_points", 5.0))
                sl_percent = float(self.params.get("trailing_sl_percent", 10.0))
                calculated_sl = max(p["max_price"] - sl_points, p["max_price"] * (1 - sl_percent / 100))
                
                # If break-even triggered, ensure SL doesn't go below break-even price
                if self.break_even_triggered and "break_even_price" in p:
                    calculated_sl = max(calculated_sl, p["break_even_price"])
                
                p["trail_sl"] = round(max(p["trail_sl"], calculated_sl), 2)

            await self._update_ui_trade_status()

            # --- Exit Check ---
            if ltp <= p["trail_sl"]:
                await self.exit_position(f"Exit: {self.exit_mode} SL Hit @ {p['trail_sl']:.2f}"); return

            # Invalidation check - Bearish/Bullish engulfing on index
            if 'open' in self.data_manager.current_candle and not self.data_manager.data_df.empty:
                live_index_candle = self.data_manager.current_candle
                prev_index_candle = self.data_manager.data_df.iloc[-1]
                
                if p['direction'] == 'CE' and self._is_bearish_engulfing(prev_index_candle, live_index_candle):
                    await self._log_debug("Exit Logic", "Invalidation: Bearish Engulfing on index. Exiting CE.")
                    await self.exit_position("Invalidation: Bearish Engulfing"); return
                elif p['direction'] == 'PE' and self._is_bullish_engulfing(prev_index_candle, live_index_candle):
                    await self._log_debug("Exit Logic", "Invalidation: Bullish Engulfing on index. Exiting PE.")
                    await self.exit_position("Invalidation: Bullish Engulfing"); return

    async def partial_exit_position(self):
        """
        Multiple Partial Exits from v47.14
        Allows exiting multiple times at different profit levels
        """
        if not self.position: return
        p, partial_exit_pct = self.position, self.params.get("partial_exit_pct", 50); lot_size = p.get("lot_size", 1)
        if lot_size <= 0: lot_size = 1
        qty_to_exit = int(min(math.ceil((p["qty"] / lot_size) * (partial_exit_pct / 100)) * lot_size, p["qty"]))
        if qty_to_exit <= 0: return
        if (p["qty"] - qty_to_exit) < lot_size: 
            await self._log_debug("Partial Exit", f"Remaining qty too small. Doing final exit.")
            await self.exit_position(f"Final Partial Profit-Take"); 
            return
        exit_price = self.data_manager.prices.get(p["symbol"], p["entry_price"])
        try:
            if self.params.get("trading_mode") == "Live Trading":
                # v47.14: Use order chasing for partial exits
                freeze_limit = 900 if self.exchange == "NFO" else 1000
                
                partial_result = await self.order_manager.execute_order_with_chasing(
                    tradingsymbol=p["symbol"],
                    total_qty=qty_to_exit,
                    product=kite.PRODUCT_MIS,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    exchange=self.exchange,
                    freeze_limit=freeze_limit
                )
                
                if partial_result.get('status') != 'COMPLETE':
                    await self._log_debug("PARTIAL EXIT FAIL", f"Partial exit failed: {partial_result.get('reason')}")
                    return  # Don't update position if partial exit failed
            gross_pnl = (exit_price - p["entry_price"]) * qty_to_exit
            charges = await self._calculate_trade_charges(tradingsymbol=p["symbol"], exchange=self.exchange, entry_price=p["entry_price"], exit_price=exit_price, quantity=qty_to_exit)
            net_pnl = gross_pnl - charges
            self.daily_gross_pnl += gross_pnl; self.total_charges += charges; self.daily_net_pnl += net_pnl
            if gross_pnl > 0: self.daily_profit += gross_pnl; _play_sound(self.manager, "profit")
            reason = f"Partial Profit-Take ({self.next_partial_profit_level})"
            log_info = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": qty_to_exit, "pnl": round(gross_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.data_manager.trend_state, "atr": round(self.data_manager.data_df.iloc[-1]["atr"], 2) if not self.data_manager.data_df.empty else 0, "charges": round(charges, 2), "net_pnl": round(net_pnl, 2) }
            await self.trade_logger.log_trade(log_info)
            await self.manager.broadcast({"type": "new_trade_log", "payload": log_info})
            p["qty"] -= qty_to_exit; self.next_partial_profit_level += 1
            await self._log_debug("Profit.Take", f"Partial exit #{self.next_partial_profit_level - 1} complete. Remaining quantity: {p['qty']}. Next level at {self.params.get('partial_profit_pct', 0) * self.next_partial_profit_level}%")
            await self._update_ui_trade_status(); await self._update_ui_performance()
        except Exception as e:
            await self._log_debug("CRITICAL-PARTIAL-EXIT-FAIL", f"Failed to partially exit {p['symbol']}: {e}"); _play_sound(self.manager, "warning")

    async def check_partial_profit_take(self):
        # ... (This function is unchanged)
        if not self.position: return
        async with self.position_lock:
            if not self.position: return
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"])
            if ltp is None: return
            partial_profit_pct = self.params.get("partial_profit_pct", 0)
            if partial_profit_pct <= 0: return
            profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
            target_pct = partial_profit_pct * self.next_partial_profit_level
            if profit_pct >= target_pct: await self.partial_exit_position()

    async def handle_ticks_async(self, ticks):
        """
        V47.14 PURE: Simple tick handler with crossover detection
        """
        try:
            # DEBUG: Track tick reception every 60 seconds
            current_time = datetime.now()
            if not hasattr(self, '_last_tick_debug') or (current_time - self._last_tick_debug).total_seconds() >= 60:
                # Receiving ticks (silent)
                self._last_tick_debug = current_time
            
            if not self.initial_subscription_done and any(t.get("instrument_token") == self.index_token for t in ticks):
                index_price = next(t["last_price"] for t in ticks if t.get("instrument_token") == self.index_token)
                self.data_manager.prices[self.index_symbol] = index_price
                await self._log_debug("WebSocket", f"Index price received: {index_price} for {self.index_symbol}. Subscribing to full token list.")
                
                # Store price and immediately get tokens with explicit price
                tokens = self.get_all_option_tokens(index_price)
                await self.map_option_tokens(tokens)
                if self.ticker_manager: self.ticker_manager.resubscribe(tokens)
                self.initial_subscription_done = True
                await self._log_debug("WebSocket", f"Full subscription complete. Subscribed to {len(tokens)} tokens.")
            
            for tick in ticks:
                token, ltp = tick.get("instrument_token"), tick.get("last_price")
                if token is not None and ltp is not None and (symbol := self.token_to_symbol.get(token)):
                    self.data_manager.prices[symbol] = ltp; self.data_manager.update_price_history(symbol, ltp)
                    is_new_minute = self.data_manager.update_live_candle(ltp, symbol)
                    
                    if symbol == self.index_symbol:
                        if is_new_minute: 
                            self.trades_this_minute = 0
                            await self.data_manager.on_new_minute(ltp)
                            await self._log_debug("New Minute", f"🕐 New minute candle formed - resetting trades count")
                            
                            # V47.14 FULL SYSTEM: New candle crossover detection via coordinator
                            if self.position is None:  # Only check entries if no position
                                await self.v47_coordinator.on_new_candle()
                        
                        # V47.14 FULL SYSTEM: Continuous monitoring for all entry signals
                        if self.position is None:  # Only check entries if no position
                            await self.v47_coordinator.continuous_monitoring()
                        
                        # DEBUG: Add periodic entry check logging (every 30 seconds)
                        current_time = datetime.now()
                        if not hasattr(self, '_last_entry_debug') or (current_time - self._last_entry_debug).total_seconds() >= 30:
                            await self._log_debug("V47 Monitor", f"🔍 Continuous monitoring active - {len(self.v47_coordinator.engines)} engines scanning")
                            self._last_entry_debug = current_time
                    
                    if self.position and self.position["symbol"] == symbol:
                        await self.check_partial_profit_take()
                        await self.evaluate_exit_logic()
        except Exception as e:
            import traceback
            await self._log_debug("Tick Handler Error", f"Critical error: {e}")
            await self._log_debug("Tick Handler Error", f"Traceback: {traceback.format_exc()}")



    # Duplicate check_trade_entry method removed - using the V47.14 Enhanced version above

    async def check_pure_v47_crossover(self):
        """Pure V47.14 crossover detection - immediate trade on supertrend flip + ATM confirmation"""
        if self.position is not None:
            return
            
        df = self.data_manager.data_df
        if len(df) < 2 or 'supertrend_uptrend' not in df.columns:
            return

        last = df.iloc[-1]
        prev = df.iloc[-2]

        curr_uptrend = last.get('supertrend_uptrend')
        prev_uptrend = prev.get('supertrend_uptrend')

        if pd.isna(curr_uptrend) or pd.isna(prev_uptrend):
            return

        side = None
        
        # Trend flipped from Bearish to Bullish
        if prev_uptrend is False and curr_uptrend is True:
            side = 'CE'  # Bullish crossover -> CE trade
            
        # Trend flipped from Bullish to Bearish  
        elif prev_uptrend is True and curr_uptrend is False:
            side = 'PE'  # Bearish crossover -> PE trade

        if side:
            # Pure V47.14: Check ATM confirmation and take trade immediately
            if await self._is_atm_confirming(side, is_reversal=True):
                opt = self.get_entry_option(side)
                if opt:
                    reason = f"V47.14_Pure_Crossover_{side}"
                    await self._log_debug("V47.14 Crossover", f"{reason} - Taking trade immediately")
                    await self.take_trade(reason, opt)

    async def on_ticker_connect(self):
        # ... (This function is unchanged)
        await self._log_debug("WebSocket", f"Connected. Subscribing to index: {self.index_symbol}")
        await self._update_ui_status()
        if self.ticker_manager: self.ticker_manager.resubscribe([self.index_token])

    async def on_ticker_disconnect(self):
        # ... (This function is unchanged)
        await self._update_ui_status(); await self._log_debug("WebSocket", "Kite Ticker Disconnected.")

    @property
    def STRATEGY_PARAMS(self):
        # ... (This function is unchanged)
        try:
            with open("strategy_params.json", "r") as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return MARKET_STANDARD_PARAMS.copy()
    
    async def _log_debug(self, source, message): 
        # V47.14 Original: Simple debug logging without enhanced formatting
        await self.manager.broadcast({"type": "debug_log", "payload": {"time": datetime.now().strftime("%H:%M:%S"), "source": source, "message": message}})
    
    async def _update_ui_status(self):
        # ... (This function is unchanged)
        is_running = self.ticker_manager and self.ticker_manager.is_connected
        payload = { "connection": "CONNECTED" if is_running else "DISCONNECTED", "mode": self.params.get("trading_mode", "Paper").upper(), "indexPrice": self.data_manager.prices.get(self.index_symbol, 0), "is_running": is_running, "is_paused": getattr(self, 'is_paused', False), "trend": self.data_manager.trend_state or "---", "indexName": self.index_name }
        await self.manager.broadcast({"type": "status_update", "payload": payload})

    async def _update_ui_performance(self):
        # ... (This function is unchanged)
        payload = { "grossPnl": self.daily_gross_pnl, "totalCharges": self.total_charges, "netPnl": self.daily_net_pnl, "wins": self.performance_stats["winning_trades"], "losses": self.performance_stats["losing_trades"] }
        await self.manager.broadcast({"type": "daily_performance_update", "payload": payload})

    async def _update_ui_trade_status(self):
        # ... (This function is unchanged)
        payload = None
        if self.position: 
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"], self.position["entry_price"])
            pnl = (ltp - p["entry_price"]) * p["qty"]; profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
            payload = {"symbol": p["symbol"], "entry_price": p["entry_price"],"ltp": ltp, "pnl": pnl, "profit_pct": profit_pct, "trail_sl": p["trail_sl"], "max_price": p["max_price"]}
        await self.manager.broadcast({"type": "trade_status_update", "payload": payload})

    # V47.14 PURE: No UOA list needed

    async def _update_ui_option_chain(self):
        # Wait for initial subscription to complete before updating option chain
        if not self.initial_subscription_done:
            await self.manager.broadcast({"type": "option_chain_update", "payload": []})
            return
            
        # Get strike pairs - this will show structure even without prices
        pairs = self.get_strike_pairs()
        data = []
        
        if pairs:
            for p in pairs: 
                ce_symbol = p["ce"]["tradingsymbol"] if p["ce"] else None
                pe_symbol = p["pe"]["tradingsymbol"] if p["pe"] else None
                ce_ltp = self.data_manager.prices.get(ce_symbol) if ce_symbol else None
                pe_ltp = self.data_manager.prices.get(pe_symbol) if pe_symbol else None
                data.append({
                    "strike": p["strike"], 
                    "ce_ltp": ce_ltp if ce_ltp is not None else "--", 
                    "pe_ltp": pe_ltp if pe_ltp is not None else "--"
                })
        else:
            # Debug: Why are we not getting strike pairs?
            index_price = self.data_manager.prices.get(self.index_symbol)
            await self._log_debug("Option Chain", f"No strike pairs. Index price: {index_price}, Symbol: {self.index_symbol}")
            
        await self.manager.broadcast({"type": "option_chain_update", "payload": data})

    async def _update_ui_straddle_monitor(self):
        # ... (This function is unchanged)
        payload = {"current_straddle": 0, "open_straddle": 0, "change_pct": 0}
        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot:
            await self.manager.broadcast({"type": "straddle_update", "payload": payload})
            return
        atm_strike = self.strike_step * round(spot / self.strike_step); ce_opt = self.get_entry_option('CE', atm_strike); pe_opt = self.get_entry_option('PE', atm_strike)
        if ce_opt and pe_opt:
            ce_sym, pe_sym = ce_opt['tradingsymbol'], pe_opt['tradingsymbol']; ce_ltp = self.data_manager.prices.get(ce_sym); pe_ltp = self.data_manager.prices.get(pe_sym)
            ce_open = self.data_manager.option_open_prices.get(ce_sym); pe_open = self.data_manager.option_open_prices.get(pe_sym)
            if all([ce_ltp, pe_ltp, ce_open, pe_open]):
                current_straddle = ce_ltp + pe_ltp; open_straddle = ce_open + pe_open
                change_pct = ((current_straddle / open_straddle) - 1) * 100 if open_straddle > 0 else 0
                payload = {"current_straddle": current_straddle, "open_straddle": open_straddle, "change_pct": change_pct}
        await self.manager.broadcast({"type": "straddle_update", "payload": payload})

    async def _update_ui_entry_signals(self):
        """Broadcast entry signals update to frontend."""
        try:
            # Get current market data
            current_price = self.data_manager.prices.get(self.index_symbol, 0)
            atm_strike = self.strike_step * round(current_price / self.strike_step) if current_price > 0 else 0
            
            # Get Supertrend data
            df = self.data_manager.data_df
            supertrend_value = None
            supertrend_direction = None
            if not df.empty and 'supertrend' in df.columns and 'supertrend_uptrend' in df.columns:
                last_row = df.iloc[-1]
                if pd.notna(last_row.get('supertrend')):
                    supertrend_value = float(last_row['supertrend'])
                    supertrend_direction = 'UP' if last_row.get('supertrend_uptrend', False) else 'DOWN'
            
            # Check V47.14 entry conditions quickly
            active_strategy = None
            entry_ready = False
            potential_entries = []
            
            # V47.14 PURE: No coordinator needed for UI updates
            
            entry_signals_data = {
                "timestamp": datetime.now().isoformat(),
                "current_price": current_price,
                "atm_strike": atm_strike,
                "supertrend_value": supertrend_value,
                "supertrend_direction": supertrend_direction,
                "active_strategy": active_strategy,
                "entry_ready": entry_ready,
                "potential_entries": potential_entries
            }
            
            await self.manager.broadcast({"type": "entry_signals_update", "payload": entry_signals_data})
            
        except Exception as e:
            # Don't log errors for UI updates to avoid spam
            pass

    async def _update_ui_chart_data(self):
        # ... (This function is unchanged)
        temp_df = self.data_manager.data_df.copy()
        if self.data_manager.current_candle.get("minute"):
            live_candle_df = pd.DataFrame([self.data_manager.current_candle], index=[self.data_manager.current_candle["minute"]])
            temp_df = pd.concat([temp_df, live_candle_df])
        if not temp_df.index.is_unique: temp_df = temp_df[~temp_df.index.duplicated(keep='last')]
        if not temp_df.index.is_monotonic_increasing: temp_df.sort_index(inplace=True)
        
        chart_data = {"candles": [], "rsi": [], "rsi_sma": [], "supertrend": []}
        
        st_col = f"SUPERT_{self.params.get('supertrend_period', 5)}_{self.params.get('supertrend_multiplier', 0.7)}"
        rsi_col = f"RSI_{self.params.get('rsi_period', 14)}"

        if not temp_df.empty:
            for index, row in temp_df.iterrows():
                timestamp = int(index.timestamp())
                chart_data["candles"].append({"time": timestamp, "open": row.get("open", 0), "high": row.get("high", 0), "low": row.get("low", 0), "close": row.get("close", 0)})
                if pd.notna(row.get(rsi_col)): chart_data["rsi"].append({"time": timestamp, "value": row[rsi_col]})
                if pd.notna(row.get("rsi_sma")): chart_data["rsi_sma"].append({"time": timestamp, "value": row["rsi_sma"]})
                # Check for supertrend column (could be from pandas_ta or custom calculation)
                supertrend_value = None
                if 'supertrend' in row and pd.notna(row.get('supertrend')):
                    supertrend_value = row['supertrend']
                elif st_col in row and pd.notna(row.get(st_col)):
                    supertrend_value = row[st_col]
                
                if supertrend_value is not None:
                    chart_data["supertrend"].append({"time": timestamp, "value": supertrend_value})

        await self.manager.broadcast({"type": "chart_data_update", "payload": chart_data})

    # V47.14 PURE: Minimal UOA methods for compatibility
    async def scan_for_unusual_activity(self):
        """V47.14 PURE: UOA scanning disabled in pure mode"""
        pass  # UOA scanning not needed in pure V47.14 mode

    async def reset_uoa_watchlist(self):
        """V47.14 PURE: UOA watchlist reset - compatibility method"""
        self.uoa_watchlist = {}
        await self._update_ui_uoa_list()

    async def _update_ui_uoa_list(self):
        """V47.14 PURE: UOA UI update - compatibility method"""
        # Send empty list to UI in pure mode
        await self.manager.broadcast({
            "type": "uoa_list_update",
            "payload": []
        })

    async def on_trend_update(self, new_trend):
        # ... (This function is unchanged)
        if self.data_manager.trend_state != new_trend: self.trend_candle_count = 1
        else: self.trend_candle_count += 1
    
    def load_instruments(self):
        # ... (This function is unchanged)
        try: return [i for i in kite.instruments(self.exchange) if i['name'] == self.index_name and i['instrument_type'] in ['CE', 'PE']]
        except Exception as e: print(f"FATAL: Could not load instruments: {e}"); raise e

    def get_weekly_expiry(self): 
        # ... (This function is unchanged)
        today = date.today()
        future_expiries = sorted([i['expiry'] for i in self.option_instruments if i.get('expiry') and i['expiry'] >= today])
        return future_expiries[0] if future_expiries else None

    def get_all_option_tokens(self, spot_price=None):
        # CRITICAL FIX: Ensure instruments and expiry are loaded
        if not self.option_instruments or self.last_used_expiry is None:
            self.option_instruments = self.load_instruments()
            self.last_used_expiry = self.get_weekly_expiry()
        
        # Use explicit price if provided, otherwise fall back to stored price
        spot = spot_price or self.data_manager.prices.get(self.index_symbol)
        if not spot: return [self.index_token]
        atm_strike = self.strike_step * round(spot / self.strike_step)
        strikes = [atm_strike + (i - 3) * self.strike_step for i in range(7)]
        tokens = {self.index_token, *[opt['instrument_token'] for strike in strikes for side in ['CE', 'PE'] if (opt := self.get_entry_option(side, strike, spot))]}
        return list(tokens)

    async def map_option_tokens(self, tokens):
        # ... (This function is unchanged)
        self.token_to_symbol = {o['instrument_token']: o['tradingsymbol'] for o in self.option_instruments if o['instrument_token'] in tokens}
        self.token_to_symbol[self.index_token] = self.index_symbol

    def get_strike_pairs(self, count=7):
        # ... (This function is unchanged)
        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot: return []
        atm_strike = self.strike_step * round(spot / self.strike_step)
        strikes = [atm_strike + (i - count // 2) * self.strike_step for i in range(count)]
        return [{"strike": strike, "ce": self.get_entry_option('CE', strike), "pe": self.get_entry_option('PE', strike)} for strike in strikes]

    def get_entry_option(self, side, strike=None, spot_price=None):
        # Use explicit price if provided, otherwise fall back to stored price
        spot = spot_price or self.data_manager.prices.get(self.index_symbol)
        if not spot: return None
        if strike is None: strike = self.strike_step * round(spot / self.strike_step)
        for o in self.option_instruments:
            if o['expiry'] == self.last_used_expiry and o['strike'] == strike and o['instrument_type'] == side: return o
        return None

    def _sanitize_params(self, params):
        p = params.copy()
        try:
            keys_to_convert = [
                "start_capital", "trailing_sl_points", "trailing_sl_percent", 
                "daily_sl", "daily_pt", "trade_profit_target", "break_even_percent", "partial_profit_pct", "partial_exit_pct", 
                "risk_per_trade_percent", "recovery_threshold_pct", "max_lots_per_order",
                "supertrend_period", "supertrend_multiplier"
            ]
            for key in keys_to_convert:
                if key in p and p[key]: p[key] = float(p[key])
        except (ValueError, TypeError) as e: print(f"Warning: Could not convert a parameter to a number: {e}")
        return p