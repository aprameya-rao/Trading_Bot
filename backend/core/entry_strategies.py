import math
import pandas as pd  # <-- FIX: Added pandas import
import numpy as np   # <-- FIX: Added numpy import
from abc import ABC, abstractmethod

# --- Candlestick Pattern Helpers (moved from strategy.py) ---
def is_bullish_engulfing(prev, last): return prev['open'] > prev['close'] and last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
def is_bearish_engulfing(prev, last): return prev['close'] > prev['open'] and last['open'] > last['close'] and last['open'] > prev['close'] and last['close'] < prev['open']
def is_hammer(c): body = abs(c['close'] - c['open']); return body > 0 and min(c['open'], c['close']) - c['low'] >= 2 * body and c['high'] - max(c['open'], c['close']) < body
def is_shooting_star(c): body = abs(c['close'] - c['open']); return body > 0 and c['high'] - max(c['open'], c['close']) >= 2 * body and min(c['open'], c['close']) - c['low'] < body
def is_doji(c): body = abs(c['close'] - c['open']); price_range = c['high'] - c['low']; return price_range > 0 and body / price_range < 0.2

class BaseEntryStrategy(ABC):
    """Abstract base class for all entry strategy logic."""
    def __init__(self, strategy_instance):
        self.strategy = strategy_instance
        self.params = strategy_instance.params
        self.data_manager = strategy_instance.data_manager
        self.aggressiveness = self.params.get("aggressiveness", "Moderate")

    @abstractmethod
    async def check(self):
        """
        Check if the conditions for this strategy are met.
        Returns a tuple (side, trigger_reason) or (None, None).
        """
        pass

class UoaEntryStrategy(BaseEntryStrategy):
    async def check(self):
        if not self.strategy.uoa_watchlist: return None, None
        for token, data in list(self.strategy.uoa_watchlist.items()):
            symbol, side, strike = data['symbol'], data['type'], data['strike']
            
            trend_ok = (side == 'CE' and self.data_manager.trend_state == 'BULLISH') or \
                       (side == 'PE' and self.data_manager.trend_state == 'BEARISH')
            momentum_ok = (side == 'CE' and self.data_manager.is_price_rising(self.data_manager.index_symbol)) or \
                          (side == 'PE' and not self.data_manager.is_price_rising(self.data_manager.index_symbol))

            if (self.aggressiveness == 'Conservative' and not trend_ok) or \
               (self.aggressiveness == 'Moderate' and not momentum_ok):
                continue
            
            if self.data_manager.is_price_rising(symbol):
                opt = self.strategy.get_entry_option(side, strike=strike)
                if opt:
                    # Consume the UOA signal
                    del self.strategy.uoa_watchlist[token]
                    await self.strategy._update_ui_uoa_list()
                    return side, "UOA_Confirmed"
        return None, None

class MaCrossoverAnticipationStrategy(BaseEntryStrategy):
    async def check(self):
        df = self.data_manager.data_df
        if len(df) < 2: return None, None
        last = df.iloc[-1]
        if pd.isna(last['wma']) or pd.isna(last['sma']): return None, None

        gap = abs(last['wma'] - last['sma'])
        threshold = last['close'] * self.strategy.STRATEGY_PARAMS.get('ma_gap_threshold_pct', 0.0055)
        if gap >= threshold: return None, None

        side = None
        if last['sma'] > last['wma'] and self.data_manager.is_price_rising(self.data_manager.index_symbol):
            side = 'CE'
        elif last['wma'] > last['sma'] and not self.data_manager.is_price_rising(self.data_manager.index_symbol):
            side = 'PE'
        
        if side:
            opt = self.strategy.get_entry_option(side)
            if opt and self.data_manager.is_price_rising(opt['tradingsymbol']):
                return side, f'MA_Anticipate_{side}'
        return None, None

class TrendContinuationStrategy(BaseEntryStrategy):
    async def check(self):
        trend = self.data_manager.trend_state
        if not trend: return None, None
        
        side = 'CE' if trend == 'BULLISH' else 'PE'
        opt = self.strategy.get_entry_option(side)
        if not opt: return None, None
        
        opt_symbol = opt['tradingsymbol']
        index_symbol = self.data_manager.index_symbol

        if self.aggressiveness == 'Conservative':
            if trend == 'BULLISH' and all([
                self.data_manager.is_candle_bullish(index_symbol),
                self.data_manager.is_candle_bullish(opt_symbol),
                self.data_manager.is_price_rising(index_symbol),
                self.data_manager.is_price_rising(opt_symbol)
            ]):
                return 'CE', 'Trend_Continuation_CE'
            elif trend == 'BEARISH' and all([
                not self.data_manager.is_candle_bullish(index_symbol),
                self.data_manager.is_price_rising(opt_symbol)
            ]):
                return 'PE', 'Trend_Continuation_PE'
        else: # Moderate
            if trend == 'BULLISH' and self.data_manager.is_price_rising(index_symbol) and self.data_manager.is_price_rising(opt_symbol):
                return 'CE', 'Trend_Continuation_CE (M)'
            elif trend == 'BEARISH' and not self.data_manager.is_price_rising(index_symbol) and self.data_manager.is_price_rising(opt_symbol):
                return 'PE', 'Trend_Continuation_PE (M)'
        
        return None, None

class CandlestickEntryStrategy(BaseEntryStrategy):
    async def check(self):
        df = self.data_manager.data_df
        if len(df) < 4: return None, None
        
        candle_minus_3, pattern_candle, confirm_candle = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        
        patterns = {
            'BULLISH': [
                (is_bearish_engulfing(candle_minus_3, pattern_candle), 'PE', 'Candle_BearEngulf'),
                (is_shooting_star(pattern_candle), 'PE', 'Candle_ShootStar'),
            ],
            'BEARISH': [
                (is_bullish_engulfing(candle_minus_3, pattern_candle), 'CE', 'Candle_BullEngulf'),
                (is_hammer(pattern_candle), 'CE', 'Candle_Hammer'),
            ]
        }
        
        trend = self.data_manager.trend_state
        if trend in patterns:
            for condition, side, reason in patterns[trend]:
                if condition and self._is_confirmed(side, confirm_candle, pattern_candle):
                     opt = self.strategy.get_entry_option(side)
                     if opt and self.data_manager.is_price_rising(opt['tradingsymbol']):
                         return side, reason
        return None, None

    def _is_confirmed(self, side, confirm_candle, pattern_candle):
        if side == 'CE':
            return confirm_candle['close'] > confirm_candle['open'] and confirm_candle['close'] > pattern_candle['high']
        else: # PE
            return confirm_candle['open'] > confirm_candle['close'] and confirm_candle['close'] < pattern_candle['low']

class RsiImmediateEntryStrategy(BaseEntryStrategy):
    async def check(self):
        df = self.data_manager.data_df
        if len(df) < self.strategy.STRATEGY_PARAMS['rsi_angle_lookback'] + 2: return None, None
            
        last, prev = df.iloc[-1], df.iloc[-2]
        if any(pd.isna(v) for v in [last['rsi'], prev['rsi'], last['rsi_sma'], prev['rsi_sma']]):
            return None, None

        angle_thresh = self.strategy.STRATEGY_PARAMS['rsi_angle_threshold']
        angle = self._calculate_rsi_angle(df)
        
        side = None
        if (last['rsi'] > last['rsi_sma'] and prev['rsi'] <= prev['rsi_sma'] and angle > angle_thresh):
            side = 'CE'
        elif (last['rsi'] < last['rsi_sma'] and prev['rsi'] >= prev['rsi_sma'] and angle < -angle_thresh):
            side = 'PE'

        if side:
            opt = self.strategy.get_entry_option(side)
            if opt and self.data_manager.is_price_rising(opt['tradingsymbol']):
                return side, f'RSI_Immediate_{side}'
        return None, None

    def _calculate_rsi_angle(self, df):
        lookback = self.strategy.STRATEGY_PARAMS["rsi_angle_lookback"]
        if len(df) < lookback + 1: return 0
        rsi_values = df["rsi"].iloc[-(lookback + 1):].values
        try: return math.degrees(math.atan(np.polyfit(np.arange(len(rsi_values)), rsi_values, 1)[0]))
        except (np.linalg.LinAlgError, ValueError): return 0

