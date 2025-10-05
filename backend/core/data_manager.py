# backend/core/data_manager.py
import asyncio
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
from typing import Optional
import time
import pandas_ta as ta

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
    """Calculate Average True Range."""
    if len(high) < length:
        return pd.Series([np.nan] * len(high), index=high.index)
    
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

def calculate_supertrend(df, period=5, multiplier=0.7):
    """
    Calculates Supertrend indicator using manual calculation for reliability.
    Returns df with 'supertrend' and 'supertrend_uptrend' columns added.
    """
    if len(df) < period:
        df['supertrend'] = np.nan
        df['supertrend_uptrend'] = np.nan
        return df
    
    df = df.copy()
    
    # First try pandas_ta if available, fallback to manual calculation
    try:
        st = df.ta.supertrend(length=period, multiplier=multiplier)
        if st is not None and not st.empty:
            supertrend_col = f'SUPERT_{period}_{multiplier}'
            direction_col = f'SUPERTd_{period}_{multiplier}'
            
            if supertrend_col in st.columns and not st[supertrend_col].isna().all():
                df['supertrend'] = st[supertrend_col]
                df['supertrend_uptrend'] = st[direction_col] == 1 if direction_col in st.columns else True
                return df
    except:
        pass
    
    # Manual Supertrend calculation
    high = df['high']
    low = df['low'] 
    close = df['close']
    
    # Calculate ATR
    atr = calculate_atr(high, low, close, period)
    
    # Calculate HL2 (median price)
    hl2 = (high + low) / 2
    
    # Calculate basic upper and lower bands
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)
    
    # Initialize arrays for final bands and supertrend
    final_upper_band = pd.Series(index=df.index, dtype='float64')
    final_lower_band = pd.Series(index=df.index, dtype='float64')
    supertrend = pd.Series(index=df.index, dtype='float64')
    uptrend = pd.Series(index=df.index, dtype='bool')
    
    for i in range(len(df)):
        if i == 0:
            final_upper_band.iloc[i] = upper_band.iloc[i]
            final_lower_band.iloc[i] = lower_band.iloc[i]
        else:
            # Calculate final upper band
            if pd.isna(upper_band.iloc[i]) or pd.isna(final_upper_band.iloc[i-1]):
                final_upper_band.iloc[i] = upper_band.iloc[i]
            elif upper_band.iloc[i] < final_upper_band.iloc[i-1] or close.iloc[i-1] > final_upper_band.iloc[i-1]:
                final_upper_band.iloc[i] = upper_band.iloc[i]
            else:
                final_upper_band.iloc[i] = final_upper_band.iloc[i-1]
                
            # Calculate final lower band  
            if pd.isna(lower_band.iloc[i]) or pd.isna(final_lower_band.iloc[i-1]):
                final_lower_band.iloc[i] = lower_band.iloc[i]
            elif lower_band.iloc[i] > final_lower_band.iloc[i-1] or close.iloc[i-1] < final_lower_band.iloc[i-1]:
                final_lower_band.iloc[i] = lower_band.iloc[i]
            else:
                final_lower_band.iloc[i] = final_lower_band.iloc[i-1]
    
    # Determine supertrend and direction after all bands are calculated
    for i in range(len(df)):
        if i == 0:
            supertrend.iloc[i] = final_lower_band.iloc[i] if not pd.isna(final_lower_band.iloc[i]) else close.iloc[i]
            uptrend.iloc[i] = True
        else:
            prev_uptrend = uptrend.iloc[i-1]
            
            # Check if trend should change
            if prev_uptrend and close.iloc[i] <= final_lower_band.iloc[i]:
                uptrend.iloc[i] = False
                supertrend.iloc[i] = final_upper_band.iloc[i]
            elif not prev_uptrend and close.iloc[i] >= final_upper_band.iloc[i]:
                uptrend.iloc[i] = True  
                supertrend.iloc[i] = final_lower_band.iloc[i]
            else:
                uptrend.iloc[i] = prev_uptrend
                if uptrend.iloc[i]:
                    supertrend.iloc[i] = final_lower_band.iloc[i]
                else:
                    supertrend.iloc[i] = final_upper_band.iloc[i]
    
    df['supertrend'] = supertrend
    df['supertrend_uptrend'] = uptrend
    
    return df


class DataManager:
    def __init__(self, index_token, index_symbol, strategy_params, log_debug_func, trend_update_func):
        self.index_token = index_token
        self.index_symbol = index_symbol
        self.strategy_params = strategy_params
        self.log_debug = log_debug_func
        self.on_trend_update = trend_update_func
        self.trend_state: Optional[str] = None
        self.prices = {}
        self.price_history = {}  # Stores: {symbol: [(timestamp, price), ...]}
        self.current_candle = {}  # Current minute candle for index
        self.option_candles = {}  # Current minute candles for options: {symbol: {minute, open, high, low, close}}
        self.previous_option_candles = {}  # Previous completed candles for options: {symbol: {minute, open, high, low, close}}
        self.option_open_prices = {}
        self.data_df = pd.DataFrame() # Initialize empty, columns will be created in _calculate_indicators

    def update_price_history(self, symbol, price):
        """Updates price history for momentum tracking, keeping last 50 ticks."""
        self.price_history.setdefault(symbol, []).append((datetime.now(), price))
        if len(self.price_history[symbol]) > 50:
            self.price_history[symbol] = self.price_history[symbol][-50:]

    # --- REPLACED: New 40-second average logic ---
    def is_average_price_trending(self, symbol: str, direction: str) -> bool:
        """
        Analyzes the last 40 seconds of tick data by comparing the average of the
        most recent 20 seconds with the average of the 20 seconds prior.
        `direction` can be 'up' or 'down'.
        """
        now = time.time()
        history = self.price_history.get(symbol, [])

        recent_half = []  # Last 0-20 seconds
        older_half = []   # Last 20-40 seconds

        for ts, price in history:
            age = now - ts
            if age <= 20:
                recent_half.append(price)
            elif age <= 40:
                older_half.append(price)
        
        # If there isn't data in both periods, we can't make a comparison
        if not recent_half or not older_half:
            return False

        avg_recent = sum(recent_half) / len(recent_half)
        avg_older = sum(older_half) / len(older_half)

        if direction == 'up':
            return avg_recent > avg_older
        elif direction == 'down':
            return avg_recent < avg_older
        
        return False

    async def bootstrap_data(self):
        # ... (This function is unchanged)
        for attempt in range(1, 4):
            try:
                await self.log_debug("Bootstrap", f"Attempt {attempt}/3: Fetching historical data...")
                def get_data(): return kite.historical_data(self.index_token, datetime.now() - timedelta(days=7), datetime.now(), "minute")
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, get_data)
                if data:
                    df = pd.DataFrame(data).tail(700); df.index = pd.to_datetime(df["date"])
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
        
        # First, calculate Supertrend using dynamic parameters from strategy
        supertrend_period = self.strategy_params.get('supertrend_period', 5)
        supertrend_multiplier = self.strategy_params.get('supertrend_multiplier', 0.7)
        df = calculate_supertrend(df, period=supertrend_period, multiplier=supertrend_multiplier)
        
        # Calculate ATR for the index df
        if all(col in df.columns for col in ['high', 'low', 'close']):
            df['atr'] = calculate_atr(df['high'], df['low'], df['close'], length=14)
        else:
            df['atr'] = np.nan
        
        # Keep other indicators for compatibility
        atr_period = self.strategy_params.get('atr_period', 14)
        atr_col = f"ATR_{atr_period}"
        df[atr_col] = df['atr']  # Duplicate for pandas_ta compatibility
        
        # Add RSI
        df.ta.rsi(length=self.strategy_params['rsi_period'], append=True)
        
        # Add Bollinger Bands and Keltner Channels for ATR Squeeze detection
        if not df['atr'].isnull().all():
            atr_bbands = df.ta.bbands(close=df['atr'], length=20, std=1.5)
            if atr_bbands is not None and not atr_bbands.empty:
                df['ATR_BB_LOWER'] = atr_bbands.iloc[:, 0]
                df['ATR_BB_UPPER'] = atr_bbands.iloc[:, 2]

        atr_kc = df.ta.kc(high=df['high'], low=df['low'], close=df['close'], length=20, scalar=1.5)
        if atr_kc is not None and not atr_kc.empty:
            df['ATR_KC_LOWER'] = atr_kc.iloc[:, 0]
            df['ATR_KC_UPPER'] = atr_kc.iloc[:, 2]

        # Calculate legacy indicators for compatibility
        df['sma'] = df['close'].rolling(window=self.strategy_params['sma_period']).mean()
        df['wma'] = calculate_wma(df['close'], length=self.strategy_params['wma_period'])
        rsi_col = f"RSI_{self.strategy_params['rsi_period']}"
        if rsi_col in df.columns:
            df['rsi_sma'] = df[rsi_col].rolling(window=self.strategy_params['rsi_signal_period']).mean()

        return df

    def update_price_history(self, symbol, price):
        # ... (This function is unchanged)
        now = time.time()
        self.price_history.setdefault(symbol, []).append((now, price))
        if len(self.price_history[symbol]) > 10:
             self.price_history[symbol] = [(ts, p) for ts, p in self.price_history[symbol] if now - ts <= 60]

    async def _update_trend_state(self):
        # Updated to use Supertrend for trend detection
        if len(self.data_df) < 2 or 'supertrend' not in self.data_df.columns:
            return

        last = self.data_df.iloc[-1]
        if pd.isna(last['supertrend']):
            return

        # Trend is BULLISH if close is above the supertrend line
        current_state = 'BULLISH' if last['close'] > last['supertrend'] else 'BEARISH'
        
        if self.trend_state != current_state:
            self.trend_state = current_state
            await self.on_trend_update(current_state)
            await self.log_debug("Trend", f"Trend is now {self.trend_state} (based on Supertrend).")

    async def on_new_minute(self, new_minute_ltp):
        # ... (This function is unchanged)
        if "minute" in self.current_candle:
            candle_to_add = self.current_candle.copy()
            new_row = pd.DataFrame([candle_to_add], index=[candle_to_add["minute"]])
            self.data_df = pd.concat([self.data_df, new_row]).tail(700)
            self.data_df = self._calculate_indicators(self.data_df)
            await self._update_trend_state()
        self.current_candle = {"minute": datetime.now(timezone.utc).replace(second=0, microsecond=0), "open": new_minute_ltp, "high": new_minute_ltp, "low": new_minute_ltp, "close": new_minute_ltp}

    def update_live_candle(self, ltp, symbol=None):
        """Updates live candle and stores previous candles for option validation."""
        is_index = symbol is None or symbol == self.index_symbol
        candle_dict = self.current_candle if is_index else self.option_candles.setdefault(symbol, {})
        current_dt_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        is_new_minute = candle_dict.get("minute") != current_dt_minute
        
        # When a new minute starts, store the previous option candle
        if is_new_minute and not is_index and "minute" in candle_dict:
            self.previous_option_candles[symbol] = candle_dict.copy()
        
        if is_index and is_new_minute and datetime.now().time() < datetime.strptime("09:16", "%H:%M").time(): 
            self.option_open_prices.clear()
        if not is_index and symbol not in self.option_open_prices: 
            self.option_open_prices[symbol] = ltp
        
        # Initialize or update candle
        if is_new_minute:
            candle_dict.update({"minute": current_dt_minute, "open": ltp, "high": ltp, "low": ltp, "close": ltp})
        elif "open" in candle_dict: 
            candle_dict.update({"high": max(candle_dict.get("high", ltp), ltp), "low": min(candle_dict.get("low", ltp), ltp), "close": ltp})
        
        return is_new_minute
    
    def is_candle_bullish(self, symbol):
        # ... (This function is unchanged)
        candle = self.option_candles.get(symbol) if symbol != self.index_symbol else self.current_candle
        return candle and "close" in candle and "open" in candle and candle["close"] > candle["open"]
    
    def get_recent_data(self, minutes=30):
        """Get recent historical data for VPA analysis"""
        if self.data_df.empty:
            return pd.DataFrame()
        
        # Return the last 'minutes' rows from the main dataframe
        return self.data_df.tail(minutes).copy()