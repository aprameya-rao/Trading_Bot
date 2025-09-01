import asyncio
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
from typing import Optional

from .kite import kite

# --- Indicator Calculation Functions ---
def calculate_wma(series, length=9):
    if length < 1 or len(series) < length: return pd.Series(index=series.index, dtype=float)
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def calculate_rsi(series, length=9):
    if length < 1 or len(series) < length: return pd.Series(index=series.index, dtype=float)
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / length, adjust=False).mean()
    loss = ((-delta.where(delta < 0, 0)).ewm(alpha=1 / length, adjust=False).mean().replace(0, 1e-10))
    return 100 - (100 / (1 + (gain / loss)))

def calculate_atr(high, low, close, length=14):
    if length < 1 or len(close) < length: return pd.Series(index=close.index, dtype=float)
    tr = pd.concat([high - low, np.abs(high - close.shift()), np.abs(low - close.shift())], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


class DataManager:
    """
    Handles all data-related tasks: candle aggregation, indicator calculation,
    price tracking, and historical data bootstrapping.
    """
    def __init__(self, index_token, index_symbol, strategy_params, log_debug_func, trend_update_func):
        self.index_token = index_token
        self.index_symbol = index_symbol
        self.strategy_params = strategy_params
        self.log_debug = log_debug_func
        self.on_trend_update = trend_update_func

        self.trend_state: Optional[str] = None
        
        # State variables
        self.prices = {}
        self.price_history = {}
        self.current_candle = {}
        self.option_candles = {}
        self.data_df = pd.DataFrame(columns=["open", "high", "low", "close", "sma", "wma", "rsi", "rsi_sma", "atr"])

    async def bootstrap_data(self):
        for attempt in range(1, 4):
            try:
                await self.log_debug("Bootstrap", f"Attempt {attempt}/3: Fetching historical data...")
                def get_data(): return kite.historical_data(self.index_token, datetime.now() - timedelta(days=7), datetime.now(), "minute")
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, get_data)
                if data:
                    df = pd.DataFrame(data).tail(700)
                    df.index = pd.to_datetime(df["date"])
                    self.data_df = self._calculate_indicators(df)
                    await self._update_trend_state()
                    await self.log_debug("Bootstrap", f"Success! Historical data loaded with {len(self.data_df)} candles.")
                    return
                else:
                    await self.log_debug("Bootstrap", f"Attempt {attempt}/3 failed: No data returned from API.")
            except Exception as e:
                await self.log_debug("Bootstrap", f"Attempt {attempt}/3 failed: {e}")
            if attempt < 3: await asyncio.sleep(3)
        await self.log_debug("Bootstrap", "CRITICAL: Could not bootstrap historical data after 3 attempts.")
        
    def _calculate_indicators(self, df):
        df = df.copy()
        df['sma'] = df['close'].rolling(window=self.strategy_params['sma_period']).mean()
        df['wma'] = calculate_wma(df['close'], length=self.strategy_params['wma_period'])
        df['rsi'] = calculate_rsi(df['close'], length=self.strategy_params['rsi_period'])
        df['rsi_sma'] = df['rsi'].rolling(window=self.strategy_params['rsi_signal_period']).mean()
        df['atr'] = calculate_atr(df['high'], df['low'], df['close'], length=self.strategy_params['atr_period'])
        return df

    def update_price_history(self, symbol, price):
        self.price_history.setdefault(symbol, []).append(price)
        if len(self.price_history[symbol]) > 10: self.price_history[symbol].pop(0)
    
    async def _update_trend_state(self):
        if len(self.data_df) < self.strategy_params.get("sma_period", 9): return
        last = self.data_df.iloc[-1]
        if pd.isna(last["wma"]) or pd.isna(last["sma"]): return
        
        current_state = "BULLISH" if last["wma"] > last["sma"] else "BEARISH"
        if self.trend_state != current_state:
            self.trend_state = current_state
            await self.on_trend_update(current_state)
            await self.log_debug("Trend", f"Trend is now {self.trend_state}.")

    async def on_new_minute(self, new_minute_ltp):
        """Called by the main strategy when a new minute starts."""
        # First, check if there's a completed candle to save
        if "minute" in self.current_candle:
            # This candle is the one from the previous minute, now complete.
            candle_to_add = self.current_candle.copy()
            new_row = pd.DataFrame([candle_to_add], index=[candle_to_add["minute"]])
            self.data_df = pd.concat([self.data_df, new_row]).tail(700)
            self.data_df = self._calculate_indicators(self.data_df)
            await self._update_trend_state()

        # Second, create the new candle for the current minute
        self.current_candle = {
            "minute": datetime.now(timezone.utc).replace(second=0, microsecond=0),
            "open": new_minute_ltp,
            "high": new_minute_ltp,
            "low": new_minute_ltp,
            "close": new_minute_ltp
        }

    def update_live_candle(self, ltp, symbol=None):
        """Updates the current (incomplete) candle for the index or an option."""
        is_index = symbol is None or symbol == self.index_symbol
        candle_dict = self.current_candle if is_index else self.option_candles.setdefault(symbol, {})
        
        current_dt_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        is_new_minute = candle_dict.get("minute") != current_dt_minute

        # Only update the H/L/C if it's for the currently forming candle
        if not is_new_minute and "open" in candle_dict:
            candle_dict.update({
                "high": max(candle_dict.get("high", ltp), ltp),
                "low": min(candle_dict.get("low", ltp), ltp),
                "close": ltp
            })
        
        return is_new_minute

    # --- Helper methods used by entry strategies ---
    def is_price_rising(self, symbol):
        history = self.price_history.get(symbol, [])
        return len(history) >= 2 and history[-1] > history[-2]

    def is_candle_bullish(self, symbol):
        candle = self.option_candles.get(symbol) if symbol != self.index_symbol else self.current_candle
        return candle and "close" in candle and "open" in candle and candle["close"] > candle["open"]
