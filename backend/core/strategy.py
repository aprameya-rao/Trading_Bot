import os, json, math, asyncio, sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from core.kite import kite
from core.websocket_manager import ConnectionManager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.kite_ticker_manager import KiteTickerManager

# --- Cross-Platform Sound Alerts & Indicator Helpers ---
try:
    import simpleaudio as sa
    def generate_tone(frequency, duration_ms):
        sample_rate = 44100
        t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), False)
        audio = np.sin(frequency * t * 2 * np.pi); max_abs = np.max(np.abs(audio))
        if max_abs > 0: audio *= 32767 / max_abs
        return audio.astype(np.int16)
    def play_sound(frequency, duration_ms):
        try: sa.play_buffer(generate_tone(frequency, duration_ms), 1, 2, 44100)
        except Exception as e: print(f"Could not play sound: {e}")
except ImportError:
    def play_sound(frequency, duration_ms): pass
def play_entry_sound(): play_sound(1200, 200)
def play_profit_sound(): play_sound(1500, 300)
def play_loss_sound(): play_sound(300, 500)
def play_warning_sound(): play_sound(400, 800)
def calculate_wma(series, length=9):
    if length < 1 or len(series) < length: return pd.Series(index=series.index, dtype=float)
    weights = np.arange(1, length + 1); return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
def calculate_rsi(series, length=9):
    if length < 1 or len(series) < length: return pd.Series(index=series.index, dtype=float)
    delta = series.diff(); gain = (delta.where(delta > 0, 0)).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/length, adjust=False).mean().replace(0, 1e-10)
    return 100 - (100 / (1 + (gain / loss)))
def calculate_atr(high, low, close, length=14):
    if length < 1 or len(close) < length: return pd.Series(index=close.index, dtype=float)
    tr = pd.concat([high - low, np.abs(high - close.shift()), np.abs(low - close.shift())], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

INDEX_CONFIG = {
    "NIFTY": {"name": "NIFTY", "token": 256265, "symbol": "NSE:NIFTY 50", "strike_step": 50, "exchange": "NFO"},
    "SENSEX": {"name": "SENSEX", "token": 265, "symbol": "BSE:SENSEX", "strike_step": 100, "exchange": "BFO"}
}

class Strategy:
    def __init__(self, params, manager: ConnectionManager, selected_index="SENSEX"):
        self.params = params
        self.manager = manager
        self.ticker_manager: "KiteTickerManager" | None = None
        self.config = INDEX_CONFIG[selected_index]
        self.db_path = 'trading_data.db'
        self.trading_mode = self.params.get('trading_mode', 'Paper Trading')
        self.aggressiveness = self.params.get('aggressiveness', 'Moderate')
        self.index_name, self.index_token, self.index_symbol, self.strike_step, self.exchange = self.config["name"], self.config["token"], self.config["symbol"], self.config["strike_step"], self.config["exchange"]
        self.token_to_symbol = {self.index_token: self.index_symbol}
        self.prices, self.price_history = {}, {}
        self.option_instruments = self.load_instruments()
        self.last_used_expiry = self.get_weekly_expiry()
        self.position = None
        self.daily_pnl, self.daily_profit, self.daily_loss = 0, 0, 0
        self.trade_log, self.performance_stats = [], {'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0}
        self.daily_trade_limit_hit = False
        self.data_df = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'sma', 'wma', 'rsi', 'rsi_sma', 'atr'])
        self.current_minute, self.current_candle = None, {}
        self.option_candles = {}
        self.uoa_watchlist = {}
        self.initial_subscription_done = False
        self.pending_steep_signal = None
        self.last_trade_minute = None
        self.trend_state = None
        self.trades_this_minute = 0
        try:
            with open('strategy_params.json', 'r') as f: self.STRATEGY_PARAMS = json.load(f)
        except FileNotFoundError:
            self.STRATEGY_PARAMS = {'wma_period': 9, 'sma_period': 9, 'rsi_period': 9, 'rsi_signal_period': 3, 'rsi_angle_lookback': 2, 'rsi_angle_threshold': 15.0, 'atr_period': 14, 'min_atr_value': 4, 'ma_gap_threshold_pct': 0.05}
    
    async def run(self):
        await self._log_debug("System", "Strategy instance created.")
        await self.bootstrap_data()

    # --- Communication Methods ---
    async def _log_debug(self, source, message):
        await self.manager.broadcast({'type': 'debug_log', 'payload': {'time': datetime.now().strftime('%H:%M:%S'), 'source': source, 'message': message}})
    
    async def _update_ui_status(self):
        await self.manager.broadcast({'type': 'status_update', 'payload': {'connection': 'CONNECTED' if self.ticker_manager and self.ticker_manager.is_connected else 'DISCONNECTED', 'mode': self.trading_mode.upper(), 'indexPrice': self.prices.get(self.index_symbol, 0), 'trend': self.trend_state or '---'}})
    
    async def _update_ui_performance(self):
        await self.manager.broadcast({'type': 'daily_performance_update', 'payload': {'netPnl': self.daily_pnl, 'grossProfit': self.daily_profit, 'grossLoss': self.daily_loss, 'wins': self.performance_stats['winning_trades'], 'losses': self.performance_stats['losing_trades']}})
    
    async def _update_ui_trade_status(self):
        payload = None
        if self.position:
            p = self.position; ltp = self.prices.get(p['symbol'], p['entry_price']); pnl = (ltp - p['entry_price']) * p['qty']; profit_pct = ((ltp - p['entry_price']) / p['entry_price']) * 100 if p['entry_price'] > 0 else 0
            payload = {'symbol': p['symbol'], 'entry_price': p['entry_price'], 'pnl': pnl, 'profit_pct': profit_pct, 'trail_sl': p['trail_sl'], 'max_price': p['max_price']}
        await self.manager.broadcast({'type': 'trade_status_update', 'payload': payload})
    
    async def _update_ui_trade_log(self):
        await self.manager.broadcast({'type': 'trade_log_update', 'payload': self.trade_log})
    
    async def _update_ui_uoa_list(self):
        await self.manager.broadcast({'type': 'uoa_list_update', 'payload': list(self.uoa_watchlist.values())})
    
    async def _update_ui_option_chain(self):
        pairs = self.get_strike_pairs(); data = []
        if self.prices.get(self.index_symbol) and pairs:
            for p in pairs: data.append({"strike": p["strike"], "ce_ltp": self.prices.get(p['ce']['tradingsymbol'], "--") if p['ce'] else "--", "pe_ltp": self.prices.get(p['pe']['tradingsymbol'], "--") if p['pe'] else "--"})
        await self.manager.broadcast({'type': 'option_chain_update', 'payload': data})
    
    async def _update_ui_chart_data(self):
        if self.data_df.empty and not self.current_candle: return
        temp_df = self.data_df.copy()
        if self.current_candle.get('minute'):
            live_candle_df = pd.DataFrame([self.current_candle], index=[self.current_candle['minute']]); temp_df = pd.concat([temp_df, live_candle_df])
        if temp_df.empty: return
        chart_data = {'candles': [], 'wma': [], 'sma': [], 'rsi': [], 'rsi_sma': []}
        for index, row in temp_df.iterrows():
            timestamp = int(index.timestamp())
            chart_data['candles'].append({'time': timestamp, 'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close']})
            if pd.notna(row['wma']): chart_data['wma'].append({'time': timestamp, 'value': row['wma']})
            if pd.notna(row['sma']): chart_data['sma'].append({'time': timestamp, 'value': row['sma']})
            if pd.notna(row['rsi']): chart_data['rsi'].append({'time': timestamp, 'value': row['rsi']})
            if pd.notna(row['rsi_sma']): chart_data['rsi_sma'].append({'time': timestamp, 'value': row['rsi_sma']})
        await self.manager.broadcast({'type': 'chart_data_update', 'payload': chart_data})
    
    # --- Ticker Connection Callbacks ---
    async def on_ticker_connect(self):
        await self._log_debug("WebSocket", f"Connected. Subscribing to index: {self.index_symbol}")
        await self._update_ui_status()
        if self.ticker_manager: self.ticker_manager.resubscribe([self.index_token])
    
    async def on_ticker_disconnect(self):
        await self._update_ui_status()
        await self._log_debug("WebSocket", "Kite Ticker Disconnected.")
    
    async def handle_ticks_async(self, ticks):
        if self.ticker_manager and not self.initial_subscription_done and any(t.get('instrument_token') == self.index_token for t in ticks):
            self.prices[self.index_symbol] = next(t['last_price'] for t in ticks if t.get('instrument_token') == self.index_token)
            await self._log_debug("WebSocket", "Index price received. Subscribing to full token list.")
            tokens = self.get_all_option_tokens()
            await self.map_option_tokens(tokens)
            self.ticker_manager.resubscribe(tokens)
            self.initial_subscription_done = True
        for tick in ticks:
            token, ltp = tick.get('instrument_token'), tick.get('last_price')
            if token is not None and ltp is not None and (symbol := self.token_to_symbol.get(token)):
                self.prices[symbol] = ltp
                self.update_price_history(symbol, ltp)
                await self.update_candle_and_indicators(ltp, symbol)
                if self.position and self.position['symbol'] == symbol:
                    await self.evaluate_exit_logic()
        if datetime.now().second % 2 == 0:
            await self._update_ui_status()
            await self._update_ui_option_chain()
            await self._update_ui_chart_data()
        
    # --- Data and State Management ---
    async def bootstrap_data(self):
        try:
            def get_data():
                return kite.historical_data(self.index_token, datetime.now() - timedelta(days=7), datetime.now(), "minute")
            data = await asyncio.to_thread(get_data)
            df = pd.DataFrame(data).tail(100); df.index = pd.to_datetime(df['date'])
            self.data_df = self._calculate_indicators(df)
            await self._update_trend_state()
            await self._log_debug("Bootstrap", f"Historical data loaded with {len(self.data_df)} candles.")
        except Exception as e:
            await self._log_debug("Bootstrap", f"Could not bootstrap data: {e}")
            
    async def _update_trend_state(self):
        if len(self.data_df) < self.STRATEGY_PARAMS.get('sma_period', 9): return
        last = self.data_df.iloc[-1]
        if pd.isna(last['wma']) or pd.isna(last['sma']): return
        current_state = 'BULLISH' if last['wma'] > last['sma'] else 'BEARISH'
        if self.trend_state != current_state:
            self.trend_state = current_state
            await self._log_debug("Trend", f"Trend is now {self.trend_state}.")

    async def update_candle_and_indicators(self, ltp, symbol=None):
        self.current_minute = datetime.now().replace(second=0, microsecond=0)
        is_index = (symbol is None or symbol == self.index_symbol)
        candle_dict = self.current_candle if is_index else self.option_candles.setdefault(symbol, {})
        if candle_dict.get('minute') != self.current_minute:
            self.trades_this_minute = 0
            if is_index and 'minute' in candle_dict:
                new_row = pd.DataFrame([candle_dict], index=[candle_dict['minute']])
                self.data_df = pd.concat([self.data_df, new_row]).tail(100)
                self.data_df = self._calculate_indicators(self.data_df)
                await self._update_trend_state()
                if self.pending_steep_signal: await self.check_pending_steep_signal()
                await self.check_trade_entry()
            candle_dict.update({'minute': self.current_minute, 'open': ltp, 'high': ltp, 'low': ltp, 'close': ltp})
        else:
            candle_dict.update({'high': max(candle_dict.get('high', ltp), ltp), 'low': min(candle_dict.get('low', ltp), ltp), 'close': ltp})
    
    # --- Core Trading Strategy ---
    async def check_trade_entry(self):
        daily_sl = self.params.get('daily_sl', 0); daily_pt = self.params.get('daily_pt', 0)
        if self.daily_trade_limit_hit:
            if datetime.now().second % 30 == 0: await self._log_debug("System", "Daily trade limit hit. No new trades.")
            return
        if daily_sl < 0 and self.daily_pnl <= daily_sl:
            self.daily_trade_limit_hit = True; play_warning_sound(); await self._log_debug("RISK", f"Daily Stop-Loss of {daily_sl} hit. Disabling trading."); return
        if daily_pt > 0 and self.daily_pnl >= daily_pt:
            self.daily_trade_limit_hit = True; play_profit_sound(); await self._log_debug("RISK", f"Daily Profit Target of {daily_pt} hit. Disabling trading."); return
        if self.trades_this_minute >= 2:
            if datetime.now().second % 15 == 0: await self._log_debug("Risk", "Max trades (2) for this minute reached.")
            return
        if self.position or self.data_df.empty or len(self.data_df) < 20: return
        last_atr = self.data_df.iloc[-1]['atr']; min_atr = self.STRATEGY_PARAMS["min_atr_value"] * (2 if self.index_name == "SENSEX" else 1)
        if pd.isna(last_atr) or last_atr < min_atr: return
        
        if await self.check_uoa_entry(): return
        if await self.check_ma_crossover_anticipation(): return
        if await self.check_trend_continuation(): return
        if self.check_steep_reentry(): return
        if await self.check_rsi_immediate_entry(): return

    # --- Trade Execution and Management ---
    async def take_trade(self, trigger, opt):
        if self.position or not opt: return
        symbol, side, price, lot_size = opt['tradingsymbol'], opt['instrument_type'], self.prices.get(opt['tradingsymbol']), opt.get('lot_size')
        if price is None or price < 1.0 or lot_size is None: await self._log_debug("Trade", f"Invalid price/lot_size for {symbol}: P={price}, L={lot_size}"); return
        qty = 15 
        if self.trading_mode == 'Live Trading':
            try:
                def place_order_sync():
                    return kite.place_order(tradingsymbol=symbol, exchange=self.exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=qty, variety=kite.VARIETY_REGULAR, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                order_id = await asyncio.to_thread(place_order_sync)
                await self._log_debug("LIVE TRADE", f"Placed BUY order for {qty} {symbol}. Order ID: {order_id}")
            except Exception as e:
                await self._log_debug("LIVE TRADE ERROR", f"Order placement failed: {e}"); play_loss_sound(); return
        else: await self._log_debug("PAPER TRADE", f"Simulating BUY order for {qty} {symbol}.")
        initial_sl = max(price - self.params['trailing_sl_points'], price * (1 - self.params['trailing_sl_percent'] / 100))
        self.position = {'symbol': symbol, 'entry_price': price, 'direction': side, 'qty': qty, 'trail_sl': round(initial_sl, 1), 'max_price': price, 'trigger_reason': trigger, 'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'lot_size': lot_size}
        self.trades_this_minute += 1; self.performance_stats['total_trades'] += 1; play_entry_sound(); await self._update_ui_trade_status(); await self._log_debug("Trade", f"Position taken: {symbol} @ {price} Qty: {qty} Trigger: {trigger}")

    async def evaluate_exit_logic(self):
        if not self.position: return
        p, ltp = self.position, self.prices.get(self.position['symbol'])
        if ltp is None: return
        if ltp > p['max_price']: p['max_price'] = ltp
        p['trail_sl'] = round(max(p['trail_sl'], max(p['max_price'] - self.params['trailing_sl_points'], p['max_price'] * (1 - self.params['trailing_sl_percent'] / 100))), 1)
        await self._update_ui_trade_status()
        if ltp <= p['trail_sl']: await self.exit_position("Trailing SL")

    async def exit_position(self, reason):
        if not self.position: return
        p, exit_price = self.position, self.prices.get(self.position['symbol'], self.position['entry_price'])
        if self.trading_mode == 'Live Trading':
            try:
                def place_order_sync():
                    return kite.place_order(tradingsymbol=p['symbol'], exchange=self.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=p['qty'], variety=kite.VARIETY_REGULAR, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                order_id = await asyncio.to_thread(place_order_sync)
                await self._log_debug("LIVE TRADE", f"Placed SELL order for {p['qty']} {p['symbol']}. Order ID: {order_id}")
            except Exception as e: await self._log_debug("LIVE TRADE ERROR", f"Exit order placement failed: {e}"); play_loss_sound()
        else: await self._log_debug("PAPER TRADE", f"Simulating SELL order for {p['qty']} {p['symbol']}.")
        net_pnl = (exit_price - p['entry_price']) * p['qty']; self.daily_pnl += net_pnl
        if net_pnl > 0: self.performance_stats['winning_trades'] += 1; self.daily_profit += net_pnl; play_profit_sound()
        else: self.performance_stats['losing_trades'] += 1; self.daily_loss += net_pnl; play_loss_sound()
        trade_entry = (p['symbol'], p['entry_time'], p['trigger_reason'], f"{p['entry_price']:.2f}", f"{exit_price:.2f}", f"{net_pnl:.2f}", reason)
        self.trade_log.append(trade_entry)
        log_info = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'trigger_reason': p['trigger_reason'], 'symbol': p['symbol'], 'pnl': round(net_pnl, 2), 'entry_price': p['entry_price'], 'exit_price': exit_price, 'exit_reason': reason, 'trend_state': self.trend_state}
        await self.log_trade_decision(log_info)
        self.position = None; await self._update_ui_trade_status(); await self._update_ui_trade_log(); await self._update_ui_performance()
    
    # --- All Other Helper Functions (Sub-strategies, UOA, Instruments) ---
    def is_price_rising(self, symbol):
        history = self.price_history.get(symbol, []); return len(history) >= 2 and history[-1] > history[-2]
    def is_candle_bullish(self, symbol):
        candle = self.option_candles.get(symbol) if symbol != self.index_symbol else self.current_candle
        return candle and 'close' in candle and 'open' in candle and candle['close'] > candle['open']
    def _calculate_rsi_angle(self):
        lookback = self.STRATEGY_PARAMS['rsi_angle_lookback']
        if len(self.data_df) < lookback + 1: return 0
        rsi_values = self.data_df['rsi'].iloc[-(lookback + 1):].values
        try: return math.degrees(math.atan(np.polyfit(np.arange(len(rsi_values)), rsi_values, 1)[0]))
        except (np.linalg.LinAlgError, ValueError): return 0
    async def check_ma_crossover_anticipation(self, log=False):
        last = self.data_df.iloc[-1]; wma, sma = last['wma'], last['sma']
        if pd.isna(wma) or pd.isna(sma): return False
        gap = abs(wma - sma); threshold = last['close'] * self.STRATEGY_PARAMS.get('ma_gap_threshold_pct', 0.0055)
        if gap >= threshold: return False
        if sma > wma and self.is_price_rising(self.index_symbol):
            opt = self.get_entry_option('CE');
            if opt and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('MA_Anticipate_CE', opt); return True
        if wma > sma and not self.is_price_rising(self.index_symbol):
            opt = self.get_entry_option('PE');
            if opt and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('MA_Anticipate_PE', opt); return True
        return False
    async def check_trend_continuation(self, log=False):
        if not self.trend_state: return False
        if self.aggressiveness == 'Conservative':
            if self.trend_state == 'BULLISH':
                opt = self.get_entry_option('CE');
                if opt and self.is_candle_bullish(self.index_symbol) and self.is_candle_bullish(opt['tradingsymbol']) and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('Trend_Continuation_CE', opt); return True
            if self.trend_state == 'BEARISH':
                opt = self.get_entry_option('PE');
                if opt and not self.is_candle_bullish(self.index_symbol) and not self.is_candle_bullish(opt['tradingsymbol']) and not self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('Trend_Continuation_PE', opt); return True
        else:
            if self.trend_state == 'BULLISH':
                opt = self.get_entry_option('CE');
                if opt and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('Trend_Continuation_CE (M)', opt); return True
            if self.trend_state == 'BEARISH':
                opt = self.get_entry_option('PE');
                if opt and not self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('Trend_Continuation_PE (M)', opt); return True
        return False
    def check_steep_reentry(self):
        last = self.data_df.iloc[-1];
        if last['wma'] > last['sma'] and not self.is_candle_bullish(self.index_symbol): self.pending_steep_signal = {'side': 'PE', 'reason': 'Reversal_PE'}
        if last['wma'] < last['sma'] and self.is_candle_bullish(self.index_symbol): self.pending_steep_signal = {'side': 'CE', 'reason': 'Reversal_CE'}
        return False
    async def check_pending_steep_signal(self):
        if not self.pending_steep_signal: return
        signal, self.pending_steep_signal = self.pending_steep_signal, None; opt = self.get_entry_option(signal['side'])
        if opt and self.is_price_rising(opt['tradingsymbol']): await self.take_trade(f"{signal['reason']}", opt)
    async def check_rsi_immediate_entry(self, log=False):
        if len(self.data_df) < self.STRATEGY_PARAMS['rsi_angle_lookback'] + 1: return False
        last, prev = self.data_df.iloc[-1], self.data_df.iloc[-2]
        if any(pd.isna(v) for v in [last['rsi'], prev['rsi'], last['rsi_sma'], prev['rsi_sma']]): return False
        angle = self._calculate_rsi_angle(); angle_thresh = self.STRATEGY_PARAMS['rsi_angle_threshold']
        if last['rsi'] > last['rsi_sma'] and prev['rsi'] <= prev['rsi_sma'] and angle > angle_thresh:
            opt = self.get_entry_option('CE');
            if opt and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('RSI_Immediate_CE', opt); return True
        if last['rsi'] < last['rsi_sma'] and prev['rsi'] >= prev['rsi_sma'] and angle < -angle_thresh:
            opt = self.get_entry_option('PE');
            if opt and not self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('RSI_Immediate_PE', opt); return True
        return False
    def load_instruments(self):
        try: return [i for i in kite.instruments(self.exchange) if i['name'] == self.index_name and i['instrument_type'] in ['CE', 'PE']]
        except Exception as e: print(f"Error loading instruments: {e}"); return []
    def get_weekly_expiry(self):
        today = date.today(); future_expiries = sorted([i['expiry'] for i in self.option_instruments if i.get('expiry') and i['expiry'] >= today]); return future_expiries[0] if future_expiries else None
    def _calculate_indicators(self, df):
        df = df.copy(); df['sma'] = df['close'].rolling(window=self.STRATEGY_PARAMS['sma_period']).mean(); df['wma'] = calculate_wma(df['close'], length=self.STRATEGY_PARAMS['wma_period'])
        df['rsi'] = calculate_rsi(df['close'], length=self.STRATEGY_PARAMS['rsi_period']); df['rsi_sma'] = df['rsi'].rolling(window=self.STRATEGY_PARAMS['rsi_signal_period']).mean()
        df['atr'] = calculate_atr(df['high'], df['low'], df['close'], length=self.STRATEGY_PARAMS['atr_period']); return df
    def get_entry_option(self, side, strike=None):
        spot = self.prices.get(self.index_symbol)
        if not spot: return None
        if strike is None: strike = self.strike_step * round(spot / self.strike_step)
        for o in self.option_instruments:
            if o['expiry'] == self.last_used_expiry and o['strike'] == strike and o['instrument_type'] == side: return o
        return None
    def update_price_history(self, symbol, price):
        self.price_history.setdefault(symbol, []).append(price)
        if len(self.price_history[symbol]) > 10: self.price_history[symbol].pop(0)
    def get_all_option_tokens(self):
        spot = self.prices.get(self.index_symbol);
        if not spot: return [self.index_token]
        atm_strike = self.strike_step * round(spot / self.strike_step); strikes = [atm_strike + (i - 3) * self.strike_step for i in range(7)]
        tokens = {self.index_token, *[opt['instrument_token'] for strike in strikes for side in ['CE', 'PE'] if (opt := self.get_entry_option(side, strike))], *self.uoa_watchlist.keys()}; return list(tokens)
    def get_strike_pairs(self, count=7):
        spot = self.prices.get(self.index_symbol)
        if not spot: return []
        atm_strike = self.strike_step * round(spot / self.strike_step); strikes = [atm_strike + (i - count // 2) * self.strike_step for i in range(count)]
        return [{"strike": strike, "ce": self.get_entry_option('CE', strike), "pe": self.get_entry_option('PE', strike)} for strike in strikes]
    def calculate_uoa_conviction_score(self, option_data, atm_strike):
        score, v_oi_ratio = 0, option_data.get('volume', 0) / (option_data.get('oi', 0) + 1)
        score += min(v_oi_ratio / 2.0, 5); price_change_pct = option_data.get('change', 0); score += min(price_change_pct / 10.0, 5)
        strike_distance = abs(option_data['strike'] - atm_strike) / self.strike_step
        if strike_distance <= 2: score += 3
        elif strike_distance <= 4: score += 1
        return score
    async def add_to_watchlist(self, side, strike):
        opt = self.get_entry_option(side, strike=strike)
        if opt:
            if opt['instrument_token'] in self.uoa_watchlist: return False
            self.uoa_watchlist[opt['instrument_token']] = {'symbol': opt['tradingsymbol'], 'type': side, 'strike': strike}
            await self._log_debug("UOA", f"Added {opt['tradingsymbol']} to watchlist."); await self._update_ui_uoa_list(); play_entry_sound(); return True
        await self._log_debug("UOA", f"Could not find {side} option for strike {strike}"); return False
    async def scan_for_unusual_activity(self):
        await self._log_debug("Scanner", "Running intelligent UOA scan...")
        spot = self.prices.get(self.index_symbol)
        if not spot: await self._log_debug("Scanner", "Aborting scan: Index price not available."); return
        try:
            atm_strike = self.strike_step * round(spot / self.strike_step)
            scan_range = 5 if self.index_name == "NIFTY" else 8
            target_strikes = [atm_strike + (i * self.strike_step) for i in range(-scan_range, scan_range + 1)]
            target_options = [i for i in self.option_instruments if i['expiry'] == self.last_used_expiry and i['strike'] in target_strikes]
            if not target_options: return
            instrument_tokens = [opt['instrument_token'] for opt in target_options]
            def blocking_quote_call(): return kite.quote(instrument_tokens)
            quotes = await asyncio.to_thread(blocking_quote_call)
            found_count, CONVICTION_THRESHOLD = 0, 7.0
            for instrument, data in quotes.items():
                opt_details = next((opt for opt in target_options if opt['instrument_token'] == data['instrument_token']), None)
                if not opt_details: continue
                quote_data = {"volume": data.get('volume', 0), "oi": data.get('oi', 0), "change": data.get('change', 0), "strike": opt_details['strike']}
                score = self.calculate_uoa_conviction_score(quote_data, atm_strike)
                if score >= CONVICTION_THRESHOLD:
                    if await self.add_to_watchlist(opt_details['instrument_type'], opt_details['strike']):
                        await self._log_debug("Scanner", f"High conviction: {opt_details['tradingsymbol']} (Score: {score:.1f}). Added."); found_count += 1
            if found_count > 0 and self.ticker_manager:
                await self._log_debug("Scanner", f"Scan complete. Added {found_count} new UOA. Resubscribing.")
                tokens = self.get_all_option_tokens(); await self.map_option_tokens(tokens); self.ticker_manager.resubscribe(tokens)
            else: await self._log_debug("Scanner", "Scan complete. No new high-conviction opportunities found.")
        except Exception as e: await self._log_debug("Scanner", f"Error during intelligent UOA scan: {e}")