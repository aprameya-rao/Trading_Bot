import math
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod

# ==============================================================================
# SECTION 1: CANDLESTICK PATTERN HELPER FUNCTIONS
# ==============================================================================

def is_bullish_engulfing(prev, last):
    if prev is None or last is None or pd.isna(prev['open']) or pd.isna(last['open']): return False
    prev_body = abs(prev['close'] - prev['open'])
    last_body = abs(last['close'] - last['open'])
    return (prev['close'] < prev['open'] and last['close'] > last['open'] and
            last['close'] > prev['open'] and last['open'] < prev['close'] and
            last_body > prev_body * 0.8)

def is_bearish_engulfing(prev, last):
    if prev is None or last is None or pd.isna(prev['open']) or pd.isna(last['open']): return False
    prev_body = abs(prev['close'] - prev['open'])
    last_body = abs(last['close'] - last['open'])
    return (prev['close'] > prev['open'] and last['close'] < last['open'] and
            last['open'] > prev['close'] and last['close'] < prev['open'] and
            last_body > prev_body * 0.8)

def is_morning_star(c1, c2, c3):
    if c1 is None or c2 is None or c3 is None or any(pd.isna(c['open']) for c in [c1, c2, c3]): return False
    b1 = abs(c1['close'] - c1['open'])
    b2 = abs(c2['close'] - c2['open'])
    b3 = abs(c3['close'] - c3['open'])
    return (c1['close'] < c1['open'] and b2 < b1 * 0.3 and
            c2['high'] < c1['close'] and c3['open'] > c2['high'] and
            c3['close'] > c3['open'] and b3 > b1 * 0.6)

def is_evening_star(c1, c2, c3):
    if c1 is None or c2 is None or c3 is None or any(pd.isna(c['open']) for c in [c1, c2, c3]): return False
    b1 = abs(c1['close'] - c1['open'])
    b2 = abs(c2['close'] - c2['open'])
    b3 = abs(c3['close'] - c3['open'])
    return (c1['close'] > c1['open'] and b2 < b1 * 0.3 and
            c2['low'] > c1['close'] and c3['open'] < c2['low'] and
            c3['close'] < c3['open'] and b3 > b1 * 0.6)

def is_hammer(c):
    if c is None or pd.isna(c['open']): return False
    body = abs(c['close'] - c['open'])
    if body == 0: return False
    lower_wick = min(c['open'], c['close']) - c['low']
    upper_wick = c['high'] - max(c['open'], c['close'])
    price_range = c['high'] - c['low']
    return (lower_wick > body * 2.5 and upper_wick < body * 0.5 and
            (min(c['open'], c['close']) - c['low']) > price_range * 0.6)

def is_hanging_man(c):
    return is_hammer(c)

# ==============================================================================
# SECTION 2: BASE CLASS AND MODIFIED ENTRY STRATEGIES
# ==============================================================================

class BaseEntryStrategy(ABC):
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        self.params = strategy_instance.params
        # --- BUG FIX: Correctly assign the data_manager instance ---
        self.data_manager = strategy_instance.data_manager
        self.aggressiveness = self.params.get("aggressiveness", "Moderate")

    @abstractmethod
    async def check(self):
        pass

    def _momentum_ok(self, side, opt_sym, look=3):
        # --- BUG FIX: Reworked to handle a simple list of prices ---
        idx_prices = self.data_manager.price_history.get(self.strategy.index_symbol, [])
        opt_prices = self.data_manager.price_history.get(opt_sym, [])
        if len(idx_prices) < look or len(opt_prices) < look:
            return False
        
        idx_up = sum(1 for i in range(1, look) if idx_prices[-i] > idx_prices[-i - 1])
        opt_up = sum(1 for i in range(1, look) if opt_prices[-i] > opt_prices[-i - 1])
        
        if side == 'CE':
            return idx_up >= 1 and opt_up >= 1
        else: # PE
            idx_dn = (look - 1) - idx_up
            return idx_dn >= 1 and opt_up >= 1

    def _is_accelerating(self, symbol, lookback_ticks=5, acceleration_factor=1.5):
        # --- BUG FIX: Reworked to calculate acceleration from price changes, not timestamps ---
        prices = self.data_manager.price_history.get(symbol, [])
        if len(prices) < lookback_ticks:
            return False
            
        recent_prices = prices[-lookback_ticks:]
        
        # Calculate recent price changes (velocities)
        diffs = np.diff(recent_prices)
        if len(diffs) < 2: return False

        current_velocity = diffs[-1]
        avg_velocity = np.mean(diffs[:-1])

        if current_velocity <= 0: return False

        # Check for acceleration if average velocity was also positive
        if avg_velocity > 0 and current_velocity > avg_velocity * acceleration_factor:
            # await self.strategy._log_debug("Momentum", f"{symbol} detected ACCELERATION.")
            return True
            
        return False

class IntraCandlePatternStrategy(BaseEntryStrategy):
    """
    Identifies patterns on the LIVE, FORMING candle.
    CONSERVATIVE MODE: Checks RSI to avoid entries against strong momentum.
    """
    async def check(self):
        if self.strategy.position: return None, None
        df = self.data_manager.data_df
        if len(df) < 3 or 'open' not in self.data_manager.current_candle: return None, None

        live_candle = self.data_manager.current_candle
        prev_candle = df.iloc[-1]
        prev_candle_2 = df.iloc[-2]
        pattern, side = None, None
        
        if is_bullish_engulfing(prev_candle, live_candle): pattern, side = 'Live_BullishEngulf', 'CE'
        elif is_bearish_engulfing(prev_candle, live_candle): pattern, side = 'Live_BearishEngulf', 'PE'
        elif is_morning_star(prev_candle_2, prev_candle, live_candle): pattern, side = 'Live_MorningStar', 'CE'
        elif is_evening_star(prev_candle_2, prev_candle, live_candle): pattern, side = 'Live_EveningStar', 'PE'
        elif is_hammer(live_candle) and self.data_manager.trend_state == 'BEARISH': pattern, side = 'Live_Hammer', 'CE'
        elif is_hanging_man(live_candle) and self.data_manager.trend_state == 'BULLISH': pattern, side = 'Live_HangingMan', 'PE'

        if not pattern: return None, None
            
        # --- ADDED CONSERVATIVE LOGIC ---
        if self.aggressiveness == 'Conservative':
            last_rsi = df.iloc[-1]['rsi']
            if pd.notna(last_rsi):
                if side == 'CE' and last_rsi < 40: return None, None # Avoid buying if momentum is strongly down
                if side == 'PE' and last_rsi > 60: return None, None # Avoid selling if momentum is strongly up
        
        opt = self.strategy.get_entry_option(side)
        if not opt: return None, None

        if self._momentum_ok(side, opt['tradingsymbol']) and self._is_accelerating(opt['tradingsymbol']):
            return side, pattern
            
        return None, None

class UoaEntryStrategy(BaseEntryStrategy):
    """Checks UOA watchlist. CONSERVATIVE MODE: Requires trend confirmation."""
    async def check(self):
        if not self.strategy.uoa_watchlist: return None, None
        for token, data in list(self.strategy.uoa_watchlist.items()):
            symbol, side, strike = data['symbol'], data['type'], data['strike']
            
            trend_ok = (side == 'CE' and self.data_manager.trend_state == 'BULLISH') or \
                       (side == 'PE' and self.data_manager.trend_state == 'BEARISH')
            
            if self.aggressiveness == 'Conservative' and not trend_ok:
                continue
            
            if self.data_manager.is_price_rising(symbol) and self._is_accelerating(symbol):
                opt = self.strategy.get_entry_option(side, strike=strike)
                if opt:
                    del self.strategy.uoa_watchlist[token]
                    # --- BUG FIX: Correctly call the UI update function ---
                    await self.strategy._update_ui_uoa_list()
                    return side, "UOA_Confirmed_Accel"
        return None, None

class TrendContinuationStrategy(BaseEntryStrategy):
    """
    Enters on a breakout.
    CONSERVATIVE MODE: Requires the previous candle to also be in the trend's direction.
    """
    async def check(self):
        trend = self.data_manager.trend_state
        # --- BUG FIX: Removed check for non-existent 'trend_candle_count' ---
        if not trend: return None, None
        df = self.data_manager.data_df
        if len(df) < 2: return None, None
        
        prev_candle = df.iloc[-1]
        current_price = self.data_manager.prices.get(self.strategy.index_symbol)
        if not current_price: return None, None

        side, reason = None, None
        if trend == 'BULLISH' and current_price > prev_candle['high']:
            # --- ADDED CONSERVATIVE LOGIC ---
            if self.aggressiveness == 'Conservative' and prev_candle['close'] < prev_candle['open']:
                return None, None # In conservative mode, don't buy a breakout of a red candle
            side, reason = 'CE', 'Trend_Cont_CE_Breakout'
        elif trend == 'BEARISH' and current_price < prev_candle['low']:
            # --- ADDED CONSERVATIVE LOGIC ---
            if self.aggressiveness == 'Conservative' and prev_candle['close'] > prev_candle['open']:
                return None, None # In conservative mode, don't sell a breakout of a green candle
            side, reason = 'PE', 'Trend_Cont_PE_Breakout'
            
        if side:
            opt = self.strategy.get_entry_option(side)
            if not opt: return None, None
            if self._momentum_ok(side, opt['tradingsymbol']) and self._is_accelerating(opt['tradingsymbol']):
                return side, reason
                
        return None, None

class RsiImmediateEntryStrategy(BaseEntryStrategy):
    """
    Enters on a sharp RSI crossover.
    CONSERVATIVE MODE: Requires the signal to align with the main trend.
    """
    async def check(self):
        df = self.data_manager.data_df
        if len(df) < self.strategy.STRATEGY_PARAMS.get('rsi_angle_lookback', 2) + 2: return None, None
        last, prev = df.iloc[-1], df.iloc[-2]
        if any(pd.isna(v) for v in [last['rsi'], prev['rsi'], last['rsi_sma'], prev['rsi_sma']]): return None, None

        angle_thresh = self.strategy.STRATEGY_PARAMS.get('rsi_angle_threshold', 12.5)
        angle = self._calculate_rsi_angle(df)
        
        side = None
        if (last['rsi'] > last['rsi_sma'] and prev['rsi'] <= prev['rsi_sma'] and angle > angle_thresh):
            side = 'CE'
        elif (last['rsi'] < last['rsi_sma'] and prev['rsi'] >= prev['rsi_sma'] and angle < -angle_thresh):
            side = 'PE'

        if side:
            # --- ADDED CONSERVATIVE LOGIC ---
            if self.aggressiveness == 'Conservative':
                if side == 'CE' and self.data_manager.trend_state != 'BULLISH': return None, None
                if side == 'PE' and self.data_manager.trend_state != 'BEARISH': return None, None

            opt = self.strategy.get_entry_option(side)
            if not opt: return None, None
            if self.data_manager.is_price_rising(opt['tradingsymbol']) and self._is_accelerating(opt['tradingsymbol']):
                return side, f'RSI_Immediate_{side}'
        return None, None

    def _calculate_rsi_angle(self, df):
        lookback = self.strategy.STRATEGY_PARAMS.get("rsi_angle_lookback", 2)
        if len(df) < lookback + 1: return 0
        rsi_values = df["rsi"].iloc[-(lookback + 1):].values
        try:
            coeffs = np.polyfit(np.arange(len(rsi_values)), rsi_values, 1)
            return math.degrees(math.atan(coeffs[0]))
        except (np.linalg.LinAlgError, ValueError):
            return 0

class MaCrossoverAnticipationStrategy(BaseEntryStrategy):
    """
    Enters before an MA cross.
    CONSERVATIVE MODE: Requires the MAs to be even closer together.
    """
    async def check(self):
        df = self.data_manager.data_df
        if len(df) < 2: return None, None
        last = df.iloc[-1]
        if pd.isna(last['wma']) or pd.isna(last['sma']): return None, None

        gap = abs(last['wma'] - last['sma'])
        threshold = last['close'] * self.strategy.STRATEGY_PARAMS.get('ma_gap_threshold_pct', 0.0055)

        # --- ADDED CONSERVATIVE LOGIC ---
        if self.aggressiveness == 'Conservative':
            threshold *= 0.75 # Require a 25% tighter gap
        
        if gap >= threshold: return None, None

        side = None
        if last['sma'] > last['wma'] and self.data_manager.is_price_rising(self.data_manager.index_symbol):
            side = 'CE'
        elif last['wma'] > last['sma'] and not self.data_manager.is_price_rising(self.data_manager.index_symbol):
            side = 'PE'
        
        if side:
            opt = self.strategy.get_entry_option(side)
            if not opt: return None, None
            if self.data_manager.is_price_rising(opt['tradingsymbol']) and self._is_accelerating(opt['tradingsymbol']):
                return side, f'MA_Anticipate_{side}'
                
        return None, None