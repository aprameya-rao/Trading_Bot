# Standard library imports
import asyncio
import json
import math
import sqlite3
from datetime import datetime, date, timedelta, timezone
from typing import TYPE_CHECKING, Optional

# Third-party imports
import numpy as np
import pandas as pd

# Local application imports
from core.kite import kite
from core.websocket_manager import ConnectionManager

if TYPE_CHECKING:
    from core.kite_ticker_manager import KiteTickerManager


# --- Sound functions are disabled to prevent freezing ---
async def _play_sound_on_frontend(manager, sound_name: str):
    """Sends a WebSocket message to the frontend to play a sound."""
    await manager.broadcast({"type": "play_sound", "payload": sound_name})

async def _play_entry_sound(manager): await _play_sound_on_frontend(manager, "entry")
async def _play_profit_sound(manager): await _play_sound_on_frontend(manager, "profit")
async def _play_loss_sound(manager): await _play_sound_on_frontend(manager, "loss")
async def _play_warning_sound(manager): await _play_sound_on_frontend(manager, "warning")


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


INDEX_CONFIG = {
    "NIFTY": {"name": "NIFTY", "token": 256265, "symbol": "NSE:NIFTY 50", "strike_step": 50, "exchange": "NFO"},
    "SENSEX": {"name": "SENSEX", "token": 265, "symbol": "BSE:SENSEX", "strike_step": 100, "exchange": "BFO"},
}

MARKET_STANDARD_PARAMS = {
    'wma_period': 9, 'sma_period': 9, 'rsi_period': 9, 'rsi_signal_period': 3,
    'rsi_angle_lookback': 2, 'rsi_angle_threshold': 15.0, 'atr_period': 14,
    'min_atr_value': 4, 'ma_gap_threshold_pct': 0.05
}


class Strategy:
    def __init__(self, params, manager: ConnectionManager, selected_index="SENSEX"):
        self.params = params
        self.manager = manager
        self.is_backtest = False
        self.ticker_manager: Optional["KiteTickerManager"] = None
        self.config = INDEX_CONFIG[selected_index]
        self.today_db_path = "trading_data_today.db"
        self.all_db_path = "trading_data_all.db"
        self.ui_update_task: Optional[asyncio.Task] = None

        try:
            numeric_params = [
                "start_capital", "trailing_sl_points", "trailing_sl_percent",
                "daily_sl", "daily_pt", "risk_per_trade_percent",
                "partial_profit_pct", "partial_exit_pct"
            ]
            for p_key in numeric_params:
                if p_key in self.params:
                    if p_key == "risk_per_trade_percent" and not self.params.get(p_key): self.params[p_key] = 1.0
                    self.params[p_key] = float(self.params[p_key])
        except (ValueError, TypeError) as e: print(f"Warning: Could not convert a parameter to a number: {e}")

        self.trading_mode = self.params.get("trading_mode", "Paper Trading"); self.aggressiveness = self.params.get("aggressiveness", "Moderate")
        self.index_name, self.index_token, self.index_symbol, self.strike_step, self.exchange = self.config["name"], self.config["token"], self.config["symbol"], self.config["strike_step"], self.config["exchange"]
        self.position, self.daily_pnl, self.daily_profit, self.daily_loss, self.daily_trade_limit_hit, self.trades_this_minute, self.trend_state, self.pending_steep_signal, self.last_trade_minute, self.initial_subscription_done, self.current_minute, self.current_candle, self.option_candles, self.prices, self.price_history = None, 0, 0, 0, False, 0, None, None, None, False, None, {}, {}, {}, {}
        self.token_to_symbol = {self.index_token: self.index_symbol}
        self.uoa_watchlist, self.trade_log, self.performance_stats = {}, [], {"total_trades": 0, "winning_trades": 0, "losing_trades": 0}
        self.data_df = pd.DataFrame(columns=["open", "high", "low", "close", "sma", "wma", "rsi", "rsi_sma", "atr"])
        self.last_check_log_time, self.last_exit_log_time = None, None
        self.next_partial_profit_level = 1

        self.option_instruments = self.load_instruments(); self.last_used_expiry = self.get_weekly_expiry()
        try:
            with open("strategy_params.json", "r") as f: self.STRATEGY_PARAMS = json.load(f)
        except FileNotFoundError:
            self.STRATEGY_PARAMS = MARKET_STANDARD_PARAMS.copy()

    async def run(self):
        await self._log_debug("System", "Strategy instance created.")
        if not self.is_backtest: await self.bootstrap_data()
        if not self.ui_update_task or self.ui_update_task.done(): self.ui_update_task = asyncio.create_task(self.periodic_ui_updater())

    async def periodic_ui_updater(self):
        while True:
            try:
                if self.is_backtest: await asyncio.sleep(1); continue
                if self.ticker_manager and self.ticker_manager.is_connected:
                    await self._update_ui_status()
                    await self._update_ui_option_chain()
                    await self._update_ui_chart_data()
                await asyncio.sleep(1)
            except asyncio.CancelledError: await self._log_debug("UI Updater", "Task cancelled."); break
            except Exception as e: await self._log_debug("UI Updater Error", f"An error occurred: {e}"); await asyncio.sleep(5)

    async def _log_debug(self, source, message): payload = {"time": datetime.now().strftime("%H:%M:%S"), "source": source, "message": message}; await self.manager.broadcast({"type": "debug_log", "payload": payload})
    async def _update_ui_status(self): payload = {"connection": "CONNECTED" if self.ticker_manager and self.ticker_manager.is_connected else "DISCONNECTED", "mode": self.trading_mode.upper(), "indexPrice": self.prices.get(self.index_symbol, 0), "trend": self.trend_state or "---", "indexName": self.index_name}; await self.manager.broadcast({"type": "status_update", "payload": payload})
    async def _update_ui_performance(self): payload = {"netPnl": self.daily_pnl, "grossProfit": self.daily_profit, "grossLoss": self.daily_loss, "wins": self.performance_stats["winning_trades"], "losses": self.performance_stats["losing_trades"]}; await self.manager.broadcast({"type": "daily_performance_update", "payload": payload})
    async def _update_ui_trade_status(self):
        payload = None
        if self.position: p, ltp = self.position, self.prices.get(self.position["symbol"], self.position["entry_price"]); pnl = (ltp - p["entry_price"]) * p["qty"]; profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0); payload = {"symbol": p["symbol"], "entry_price": p["entry_price"], "pnl": pnl, "profit_pct": profit_pct, "trail_sl": p["trail_sl"], "max_price": p["max_price"]}
        await self.manager.broadcast({"type": "trade_status_update", "payload": payload})
    async def _update_ui_trade_log(self): await self.manager.broadcast({"type": "trade_log_update", "payload": self.trade_log})
    async def _update_ui_uoa_list(self): await self.manager.broadcast({"type": "uoa_list_update", "payload": list(self.uoa_watchlist.values())})
    async def _update_ui_option_chain(self):
        pairs = self.get_strike_pairs(); data = []
        if self.prices.get(self.index_symbol) and pairs:
            for p in pairs:
                ce_symbol, pe_symbol = (p["ce"]["tradingsymbol"] if p["ce"] else None, p["pe"]["tradingsymbol"] if p["pe"] else None)
                data.append({"strike": p["strike"], "ce_ltp": self.prices.get(ce_symbol, "--") if ce_symbol else "--", "pe_ltp": self.prices.get(pe_symbol, "--") if pe_symbol else "--"})
        await self.manager.broadcast({"type": "option_chain_update", "payload": data})
        
    # --- MODIFIED: Added logic to prevent duplicate timestamps ---
    async def _update_ui_chart_data(self):
        temp_df = self.data_df.copy()

        # Combine historical and live candle data
        if self.current_candle.get("minute"):
            live_candle_df = pd.DataFrame([self.current_candle], index=[self.current_candle["minute"]])
            temp_df = pd.concat([temp_df, live_candle_df])

        # --- FIX: Explicitly remove any duplicate timestamps, keeping the last entry ---
        # This is the most robust way to solve the "data must be asc ordered by time" error.
        if not temp_df.index.is_unique:
            temp_df = temp_df[~temp_df.index.duplicated(keep='last')]

        # The original sort check can remain as a final safety measure.
        if not temp_df.index.is_monotonic_increasing:
            temp_df.sort_index(inplace=True)
    
        chart_data = {"candles": [], "wma": [], "sma": [], "rsi": [], "rsi_sma": []}
        if not temp_df.empty:
            for index, row in temp_df.iterrows():
                timestamp = int(index.timestamp())
                chart_data["candles"].append({"time": timestamp, "open": row.get("open", 0), "high": row.get("high", 0), "low": row.get("low", 0), "close": row.get("close", 0)})
            
                wma_val = row.get("wma")
                sma_val = row.get("sma")
                rsi_val = row.get("rsi")
                rsi_sma_val = row.get("rsi_sma")
            
                if pd.notna(wma_val):
                    chart_data["wma"].append({"time": timestamp, "value": wma_val})
                if pd.notna(sma_val):
                    chart_data["sma"].append({"time": timestamp, "value": sma_val})
                if pd.notna(rsi_val):
                    chart_data["rsi"].append({"time": timestamp, "value": rsi_val})
                if pd.notna(rsi_sma_val):
                    chart_data["rsi_sma"].append({"time": timestamp, "value": rsi_sma_val})

        await self.manager.broadcast({"type": "chart_data_update", "payload": chart_data})
    
    async def on_ticker_connect(self):
        await self._log_debug("WebSocket", f"Connected. Subscribing to index: {self.index_symbol}")
        await self._update_ui_status()
        if self.ticker_manager: self.ticker_manager.resubscribe([self.index_token])

    async def on_ticker_disconnect(self):
        await self._update_ui_status()
        await self._log_debug("WebSocket", "Kite Ticker Disconnected.")

    async def handle_ticks_async(self, ticks):
        try:
            if self.ticker_manager and not self.initial_subscription_done and any(t.get("instrument_token") == self.index_token for t in ticks):
                self.prices[self.index_symbol] = next(t["last_price"] for t in ticks if t.get("instrument_token") == self.index_token)
                await self._log_debug("WebSocket", "Index price received. Subscribing to full token list.")
                tokens = self.get_all_option_tokens(); await self.map_option_tokens(tokens); self.ticker_manager.resubscribe(tokens); self.initial_subscription_done = True
            for tick in ticks:
                try:
                    token, ltp = tick.get("instrument_token"), tick.get("last_price")
                    if token is not None and ltp is not None and (symbol := self.token_to_symbol.get(token)):
                        self.prices[symbol] = ltp; self.update_price_history(symbol, ltp); await self.update_candle_and_indicators(ltp, symbol)
                        if self.position and self.position["symbol"] == symbol: await self.evaluate_exit_logic()
                except Exception as e: await self._log_debug("Tick Error", f"Error processing tick {tick.get('instrument_token')}: {e}")
        except Exception as e: await self._log_debug("Tick Handler Error", f"Critical error in handle_ticks_async: {e}")

    async def bootstrap_data(self, df: Optional[pd.DataFrame] = None):
        if df is not None:
            self.data_df = self._calculate_indicators(df); await self._update_trend_state(); await self._log_debug("Bootstrap", f"Backtest data loaded with {len(self.data_df)} candles."); return
        for attempt in range(1, 4):
            try:
                await self._log_debug("Bootstrap", f"Attempt {attempt}/3: Fetching historical data...")
                def get_data(): return kite.historical_data(self.index_token, datetime.now() - timedelta(days=7), datetime.now(), "minute")
                loop = asyncio.get_running_loop(); data = await loop.run_in_executor(None, get_data)
                if data:
                    df = pd.DataFrame(data).tail(300); df.index = pd.to_datetime(df["date"])
                    self.data_df = self._calculate_indicators(df); await self._update_trend_state(); await self._log_debug("Bootstrap", f"Success! Historical data loaded with {len(self.data_df)} candles."); return
                else: await self._log_debug("Bootstrap", f"Attempt {attempt}/3 failed: No data returned from API.")
            except Exception as e: await self._log_debug("Bootstrap", f"Attempt {attempt}/3 failed: {e}")
            if attempt < 3: await asyncio.sleep(3)
        await self._log_debug("Bootstrap", "CRITICAL: Could not bootstrap historical data after 3 attempts.")

    async def _update_trend_state(self):
        if len(self.data_df) < self.STRATEGY_PARAMS.get("sma_period", 9): return
        last = self.data_df.iloc[-1]
        if pd.isna(last["wma"]) or pd.isna(last["sma"]): return
        current_state = "BULLISH" if last["wma"] > last["sma"] else "BEARISH"
        if self.trend_state != current_state: self.trend_state = current_state; await self._log_debug("Trend", f"Trend is now {self.trend_state}.")

    async def update_candle_and_indicators(self, ltp, symbol=None):
        self.current_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        is_index = symbol is None or symbol == self.index_symbol
        candle_dict = self.current_candle if is_index else self.option_candles.setdefault(symbol, {})
        if candle_dict.get("minute") != self.current_minute:
            self.trades_this_minute = 0
            if is_index and "minute" in candle_dict:
                new_row = pd.DataFrame([candle_dict], index=[candle_dict["minute"]])
                self.data_df = pd.concat([self.data_df, new_row]).tail(300); self.data_df = self._calculate_indicators(self.data_df)
                await self._update_trend_state()
                if self.pending_steep_signal: await self.check_pending_steep_signal()
                await self.check_trade_entry()
            candle_dict.update({"minute": self.current_minute, "open": ltp, "high": ltp, "low": ltp, "close": ltp})
        else: candle_dict.update({"high": max(candle_dict.get("high", ltp), ltp), "low": min(candle_dict.get("low", ltp), ltp), "close": ltp})

    async def log_trade_decision(self, trade_info):
        if self.is_backtest: return
        
        def db_call():
            atr_value = (self.data_df.iloc[-1]["atr"] if not self.data_df.empty and "atr" in self.data_df.columns else 0)
            trade_info["atr"] = round(atr_value, 2)
            
            columns = ", ".join(trade_info.keys())
            placeholders = ", ".join("?" * len(trade_info))
            sql = f"INSERT INTO trades ({columns}) VALUES ({placeholders})"
            values = tuple(trade_info.values())

            for db_path in [self.today_db_path, self.all_db_path]:
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute(sql, values)
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"CRITICAL DB ERROR writing to {db_path}: {e}")

        await asyncio.to_thread(db_call)
        await self._log_debug("Database", f"Trade for {trade_info['symbol']} logged to both databases.")

    async def check_trade_entry(self):
        now = datetime.now()
        log_this_time = self.last_check_log_time is None or (now - self.last_check_log_time) > timedelta(seconds=10)
        if log_this_time: self.last_check_log_time = now; await self._log_debug("Check.Entry", "--- Running Entry Checks ---")
        
        if not self.data_df.empty:
            last_atr = self.data_df.iloc[-1]['atr']
            min_atr_multiplier = 2 if self.index_name == "SENSEX" else 1
            min_atr = self.STRATEGY_PARAMS.get("min_atr_value", 4) * min_atr_multiplier
            if pd.isna(last_atr) or last_atr < min_atr:
                if log_this_time:
                    atr_val_str = f"{last_atr:.2f}" if pd.notna(last_atr) else "N/A"
                    await self._log_debug("Check.Entry", f"-> FAIL: ATR ({atr_val_str}) is below threshold ({min_atr}). Market too quiet.")
                return

        if self.position:
            if log_this_time: await self._log_debug("Check.Entry", "-> FAIL: A position is already open."); return
        daily_sl, daily_pt = self.params.get("daily_sl", 0), self.params.get("daily_pt", 0)
        if self.daily_trade_limit_hit:
            if log_this_time: await self._log_debug("Check.Entry", "-> FAIL: Daily trade limit (SL/PT) has been hit."); return
        if daily_sl < 0 and self.daily_pnl <= daily_sl:
            self.daily_trade_limit_hit = True; await _play_warning_sound(self.manager); await self._log_debug("RISK", f"Daily Stop-Loss of {daily_sl} hit. Disabling trading."); return
        if daily_pt > 0 and self.daily_pnl >= daily_pt:
            self.daily_trade_limit_hit = True; await _play_profit_sound(self.manager); await self._log_debug("RISK", f"Daily Profit Target of {daily_pt} hit. Disabling trading."); return
        if self.trades_this_minute >= 2:
            if log_this_time: await self._log_debug("Check.Entry", f"-> FAIL: Trade frequency limit for this minute ({self.trades_this_minute}/2) reached."); return
        if self.data_df.empty or len(self.data_df) < 20:
            if log_this_time: await self._log_debug("Check.Entry", f"-> FAIL: Not enough historical data ({len(self.data_df)}/20 candles)."); return
        if log_this_time: await self._log_debug("Check.Entry", "-> PASS: All pre-checks passed. Evaluating strategies...")
        if await self.check_uoa_entry(log_this_time): return
        if await self.check_ma_crossover_anticipation(log_this_time): return
        if await self.check_trend_continuation(log_this_time): return
        if self.check_steep_reentry(): return
        if await self.check_rsi_immediate_entry(log_this_time): return
        if log_this_time: await self._log_debug("Check.Entry", "--- No entry conditions met this minute. ---")
        
    async def take_trade(self, trigger, opt):
        self.next_partial_profit_level = 1
        if self.position or not opt: return
        symbol, side, price, lot_size = (opt["tradingsymbol"], opt["instrument_type"], self.prices.get(opt["tradingsymbol"]), opt.get("lot_size"))
        if price is None or price < 1.0 or lot_size is None: await self._log_debug("Trade", f"Invalid price/lot_size for {symbol}: P={price}, L={lot_size}"); return
        capital, risk_percent = float(self.params.get("start_capital", 50000)), float(self.params.get("risk_per_trade_percent", 1.0))
        sl_points, sl_percent = float(self.params["trailing_sl_points"]), float(self.params["trailing_sl_percent"])
        initial_sl_price = max(price - sl_points, price * (1 - sl_percent / 100))
        risk_per_share = price - initial_sl_price
        if risk_per_share <= 0: await self._log_debug("Risk", f"Cannot calculate quantity. Risk per share is zero or negative for {symbol}."); return
        risk_amount_per_trade, risk_per_lot = capital * (risk_percent / 100), risk_per_share * lot_size
        num_lots = math.floor(risk_amount_per_trade / risk_per_lot)
        if num_lots == 0:
            if capital > price * lot_size: num_lots = 1; await self._log_debug("Risk", "Calculated lots is 0. Defaulting to 1 lot as capital permits.")
            else: await self._log_debug("Risk", f"Insufficient capital to take even 1 lot of {symbol}."); return
        qty = num_lots * lot_size
        if self.trading_mode == "Live Trading" and not self.is_backtest:
            try:
                def place_order_sync(): return kite.place_order(tradingsymbol=symbol, exchange=self.exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=qty, variety=kite.VARIETY_REGULAR, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                order_id = await asyncio.to_thread(place_order_sync)
                await self._log_debug("LIVE TRADE", f"Placed BUY order for {qty} {symbol}. Order ID: {order_id}")
            except Exception as e: await self._log_debug("LIVE TRADE ERROR", f"Order placement failed: {e}"); await _play_loss_sound(self.manager); return
        else: await self._log_debug("PAPER TRADE", f"Simulating BUY order for {qty} {symbol}.")
        self.position = {"symbol": symbol, "entry_price": price, "direction": side, "qty": qty, "trail_sl": round(initial_sl_price, 1), "max_price": price, "trigger_reason": trigger, "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lot_size": lot_size}
        self.trades_this_minute += 1; self.performance_stats["total_trades"] += 1; await _play_entry_sound(self.manager)
        await self._update_ui_trade_status()
        await self._log_debug("Trade", f"Position taken: {symbol} @ {price} Qty: {qty} Trigger: {trigger}")

    async def evaluate_exit_logic(self):
        if not self.position: return
        p, ltp = self.position, self.prices.get(self.position["symbol"])
        if ltp is None: return

        partial_profit_pct = self.params.get("partial_profit_pct", 0)
        if partial_profit_pct > 0:
            profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
            target_profit_pct = partial_profit_pct * self.next_partial_profit_level
            if profit_pct >= target_profit_pct:
                await self._log_debug("Profit.Take", f"Target of {target_profit_pct:.2f}% reached (current: {profit_pct:.2f}%).")
                await self.partial_exit_position()
                self.next_partial_profit_level += 1
                return 

        if ltp > p["max_price"]: p["max_price"] = ltp
        sl_points, sl_percent = float(self.params["trailing_sl_points"]), float(self.params["trailing_sl_percent"])
        p["trail_sl"] = round(max(p["trail_sl"], max(p["max_price"] - sl_points, p["max_price"] * (1 - sl_percent / 100))), 1)
        now = datetime.now()
        log_this_time = self.last_exit_log_time is None or (now - self.last_exit_log_time) > timedelta(seconds=5)
        if log_this_time:
            self.last_exit_log_time = now
            if not self.is_backtest: await self._log_debug("Check.Exit", f"LTP: {ltp:.2f} vs Trail SL: {p['trail_sl']:.2f}")
        if not self.is_backtest: await self._update_ui_trade_status()
        if ltp <= p["trail_sl"]: await self.exit_position("Trailing SL")

    async def partial_exit_position(self):
        if not self.position: return
        p = self.position; partial_exit_pct = self.params.get("partial_exit_pct", 50)
        qty_to_exit = math.ceil(p["qty"] * (partial_exit_pct / 100))
        qty_to_exit = int(min(qty_to_exit, p["qty"]))
        if qty_to_exit < 1: return
        if (p["qty"] - qty_to_exit) <= 0: await self.exit_position(f"Final Partial Profit-Take"); return

        exit_price = self.prices.get(p["symbol"], p["entry_price"])
        if self.trading_mode == "Live Trading" and not self.is_backtest:
            try:
                def place_order_sync(): return kite.place_order(tradingsymbol=p["symbol"], exchange=self.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, variety=kite.VARIETY_REGULAR, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                await asyncio.to_thread(place_order_sync)
                await self._log_debug("LIVE TRADE", f"Partially exited {qty_to_exit} of {p['symbol']}.")
            except Exception as e: await self._log_debug("LIVE TRADE ERROR", f"Partial exit failed: {e}"); await _play_loss_sound(self.manager); return
        else: await self._log_debug("PAPER TRADE", f"Simulating partial exit of {qty_to_exit} of {p['symbol']}.")
        
        net_pnl = (exit_price - p["entry_price"]) * qty_to_exit
        self.daily_pnl += net_pnl
        if net_pnl > 0: self.daily_profit += net_pnl; await _play_profit_sound(self.manager)
        
        reason = f"Partial Profit-Take ({self.next_partial_profit_level})"
        trade_entry = (p["symbol"], qty_to_exit, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), p["trigger_reason"], f"{p['entry_price']:.2f}", f"{exit_price:.2f}", f"{net_pnl:.2f}", reason)
        self.trade_log.append(trade_entry)
        log_info = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": qty_to_exit, "pnl": round(net_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.trend_state}
        await self.log_trade_decision(log_info)

        p["qty"] -= qty_to_exit
        await self._log_debug("Profit.Take", f"Remaining quantity: {p['qty']}.")
        await self._update_ui_trade_status(); await self._update_ui_trade_log(); await self._update_ui_performance()

    async def exit_position(self, reason):
        self.next_partial_profit_level = 1
        if not self.position: return
        p, exit_price = self.position, self.prices.get(self.position["symbol"], self.position["entry_price"])
        if self.trading_mode == "Live Trading" and not self.is_backtest:
            try:
                def place_order_sync(): return kite.place_order(tradingsymbol=p["symbol"], exchange=self.exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=p["qty"], variety=kite.VARIETY_REGULAR, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                order_id = await asyncio.to_thread(place_order_sync)
                await self._log_debug("LIVE TRADE", f"Placed SELL order for {p['qty']} {p['symbol']}. Order ID: {order_id}")
            except Exception as e: await self._log_debug("LIVE TRADE ERROR", f"Exit order placement failed: {e}"); await _play_loss_sound(self.manager)
        else: await self._log_debug("PAPER TRADE", f"Simulating SELL order for {p['qty']} {p['symbol']}.")
        net_pnl = (exit_price - p["entry_price"]) * p["qty"]; self.daily_pnl += net_pnl
        if net_pnl > 0: self.performance_stats["winning_trades"] += 1; self.daily_profit += net_pnl; await _play_profit_sound(self.manager)
        else: self.performance_stats["losing_trades"] += 1; self.daily_loss += net_pnl; await _play_loss_sound(self.manager)
        trade_entry = (p["symbol"], p["qty"], p["entry_time"], p["trigger_reason"], f"{p['entry_price']:.2f}", f"{exit_price:.2f}", f"{net_pnl:.2f}", reason)
        self.trade_log.append(trade_entry)
        log_info = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": p["qty"], "pnl": round(net_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.trend_state}
        await self.log_trade_decision(log_info)
        self.position = None; await self._update_ui_trade_status(); await self._update_ui_trade_log(); await self._update_ui_performance()

    def is_price_rising(self, symbol):
        history = self.price_history.get(symbol, [])
        return len(history) >= 2 and history[-1] > history[-2]

    def is_candle_bullish(self, symbol):
        candle = self.option_candles.get(symbol) if symbol != self.index_symbol else self.current_candle
        return candle and "close" in candle and "open" in candle and candle["close"] > candle["open"]

    def _calculate_rsi_angle(self):
        lookback = self.STRATEGY_PARAMS["rsi_angle_lookback"]
        if len(self.data_df) < lookback + 1: return 0
        rsi_values = self.data_df["rsi"].iloc[-(lookback + 1):].values
        try: return math.degrees(math.atan(np.polyfit(np.arange(len(rsi_values)), rsi_values, 1)[0]))
        except (np.linalg.LinAlgError, ValueError): return 0

    async def check_uoa_entry(self, log=False):
        try:
            if not self.uoa_watchlist: return False
            if log: await self._log_debug("Check.UOA", f"Evaluating {len(self.uoa_watchlist)} item(s)...")
            current_second = datetime.now().second
            if current_second < 10 and not self.is_backtest:
                if log: await self._log_debug("Check.UOA", "-> FAIL: In confirmation period (0-10s)."); return False
            for token, data in list(self.uoa_watchlist.items()):
                symbol, side = data['symbol'], data['type']
                trigger_reason = "UOA_Entry_Unknown"
                if self.aggressiveness == 'Conservative':
                    if log: await self._log_debug("Check.UOA", f"[{symbol}] Mode: Conservative")
                    trend_ok = (not self.trend_state) or (side == 'CE' and self.trend_state == 'BULLISH') or (side == 'PE' and self.trend_state == 'BEARISH')
                    if not trend_ok:
                        if log: await self._log_debug("Check.UOA", f"-> FAIL: Trend ({self.trend_state}) is against trade side ({side})."); continue
                    if log: await self._log_debug("Check.UOA", f"-> PASS: Trend ({self.trend_state}) confirms trade side ({side}).")
                    trigger_reason = "UOA_Trend_Confirmed"
                else:
                    if log: await self._log_debug("Check.UOA", f"[{symbol}] Mode: Moderate")
                    index_momentum_ok = (side == 'CE' and self.is_price_rising(self.index_symbol)) or (side == 'PE' and not self.is_price_rising(self.index_symbol))
                    if not index_momentum_ok:
                        if log: await self._log_debug("Check.UOA", f"-> FAIL: Index momentum is against trade side ({side})."); continue
                    if log: await self._log_debug("Check.UOA", f"-> PASS: Index momentum confirms trade side ({side}).")
                    trigger_reason = "UOA_Momentum_Confirmed"
                option_candle, current_price = self.option_candles.get(symbol), self.prices.get(symbol)
                if not option_candle or 'open' not in option_candle or not current_price:
                    if log: await self._log_debug("Check.UOA", f"-> FAIL: Awaiting full candle data for {symbol}."); continue
                if current_price <= option_candle['open']:
                    if log: await self._log_debug("Check.UOA", f"-> FAIL: Price ({current_price}) not above candle open ({option_candle['open']})."); continue
                if log: await self._log_debug("Check.UOA", f"-> PASS: Price ({current_price}) is above candle open ({option_candle['open']}).")
                if not self.is_price_rising(symbol):
                    if log: await self._log_debug("Check.UOA", f"-> FAIL: Option price is not rising."); continue
                if log: await self._log_debug("Check.UOA", f"-> PASS: Option price is rising. Taking trade.")
                opt = self.get_entry_option(side, strike=data['strike']); await self.take_trade(trigger_reason, opt); del self.uoa_watchlist[token]; await self._update_ui_uoa_list(); return True
            return False
        except Exception as e: await self._log_debug("CrashGuard", f"Error in UOA check: {e}"); return False

    async def check_ma_crossover_anticipation(self, log=False):
        try:
            if log: await self._log_debug("Check.MA", "Evaluating MA Crossover Anticipation...")
            last = self.data_df.iloc[-1]; wma, sma = last['wma'], last['sma']
            if pd.isna(wma) or pd.isna(sma): return False
            gap = abs(wma - sma); threshold = last['close'] * self.STRATEGY_PARAMS.get('ma_gap_threshold_pct', 0.0055)
            if gap >= threshold:
                if log: await self._log_debug("Check.MA", f"-> FAIL: MA Gap ({gap:.2f}) is wider than threshold ({threshold:.2f})."); return False
            if log: await self._log_debug("Check.MA", f"-> PASS: MA Gap ({gap:.2f}) is within threshold.")
            if sma > wma:
                if not self.is_price_rising(self.index_symbol):
                    if log: await self._log_debug("Check.MA", "-> FAIL: Index price not rising for bullish crossover."); return False
                if log: await self._log_debug("Check.MA", "-> PASS: Index price is rising for bullish crossover.")
                opt = self.get_entry_option('CE');
                if opt and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('MA_Anticipate_CE', opt); return True
            if wma > sma:
                if self.is_price_rising(self.index_symbol):
                    if log: await self._log_debug("Check.MA", "-> FAIL: Index price not falling for bearish crossover."); return False
                if log: await self._log_debug("Check.MA", "-> PASS: Index price is falling for bearish crossover.")
                opt = self.get_entry_option('PE');
                if opt and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('MA_Anticipate_PE', opt); return True
            return False
        except Exception as e: await self._log_debug("CrashGuard", f"Error in MA crossover check: {e}"); return False

    async def check_trend_continuation(self, log=False):
        try:
            if not self.trend_state: return False
            if log: await self._log_debug("Check.Trend", f"Evaluating Trend Continuation for {self.trend_state} state...")
            side = 'CE' if self.trend_state == 'BULLISH' else 'PE'
            opt = self.get_entry_option(side)
            if not opt: return False
            if self.aggressiveness == 'Conservative':
                if self.trend_state == 'BULLISH':
                    if not (self.is_candle_bullish(self.index_symbol) and self.is_candle_bullish(opt['tradingsymbol']) and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol'])):
                        if log: await self._log_debug("Check.Trend", "-> FAIL: Conservative bullish conditions not met."); return False
                    if log: await self._log_debug("Check.Trend", "-> PASS: All conservative bullish conditions met.")
                    await self.take_trade('Trend_Continuation_CE', opt); return True
                else:
                    if not (not self.is_candle_bullish(self.index_symbol) and not self.is_candle_bullish(opt['tradingsymbol']) and not self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol'])):
                        if log: await self._log_debug("Check.Trend", "-> FAIL: Conservative bearish conditions not met."); return False
                    if log: await self._log_debug("Check.Trend", "-> PASS: All conservative bearish conditions met.")
                    await self.take_trade('Trend_Continuation_PE', opt); return True
            else:
                if self.trend_state == 'BULLISH':
                    if not (self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol'])):
                        if log: await self._log_debug("Check.Trend", "-> FAIL: Moderate bullish conditions not met."); return False
                    if log: await self._log_debug("Check.Trend", "-> PASS: All moderate bullish conditions met.")
                    await self.take_trade('Trend_Continuation_CE (M)', opt); return True
                else:
                    if not (not self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol'])):
                        if log: await self._log_debug("Check.Trend", "-> FAIL: Moderate bearish conditions not met."); return False
                    if log: await self._log_debug("Check.Trend", "-> PASS: All moderate bearish conditions met.")
                    await self.take_trade('Trend_Continuation_PE (M)', opt); return True
            return False
        except Exception as e: await self._log_debug("CrashGuard", f"Error in trend continuation check: {e}"); return False

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
        try:
            if len(self.data_df) < self.STRATEGY_PARAMS['rsi_angle_lookback'] + 1: return False
            if log: await self._log_debug("Check.RSI", "Evaluating RSI Immediate Entry...")
            last, prev = self.data_df.iloc[-1], self.data_df.iloc[-2]
            if any(pd.isna(v) for v in [last['rsi'], prev['rsi'], last['rsi_sma'], prev['rsi_sma']]): return False
            angle = self._calculate_rsi_angle(); angle_thresh = self.STRATEGY_PARAMS['rsi_angle_threshold']
            
            if last['rsi'] > last['rsi_sma'] and prev['rsi'] <= prev['rsi_sma']:
                if log: await self._log_debug("Check.RSI", f"-> PASS: Bullish RSI crossover detected.")
                if angle <= angle_thresh:
                    if log: await self._log_debug("Check.RSI", f"-> FAIL: Angle ({angle:.2f}) not steep enough ( > {angle_thresh:.2f})."); return False
                if log: await self._log_debug("Check.RSI", f"-> PASS: Angle ({angle:.2f}) is steep enough.")
                opt = self.get_entry_option('CE')
                if opt and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('RSI_Immediate_CE', opt); return True

            if last['rsi'] < last['rsi_sma'] and prev['rsi'] >= prev['rsi_sma']:
                if log: await self._log_debug("Check.RSI", f"-> PASS: Bearish RSI crossover detected.")
                if angle >= -angle_thresh:
                    if log: await self._log_debug("Check.RSI", f"-> FAIL: Angle ({angle:.2f}) not steep enough ( < -{angle_thresh:.2f})."); return False
                if log: await self._log_debug("Check.RSI", f"-> PASS: Angle ({angle:.2f}) is steep enough.")
                opt = self.get_entry_option('PE')
                if opt and self.is_price_rising(self.index_symbol) and self.is_price_rising(opt['tradingsymbol']): await self.take_trade('RSI_Immediate_PE', opt); return True
            
            return False
        except Exception as e: await self._log_debug("CrashGuard", f"Error in RSI immediate check: {e}"); return False

    def load_instruments(self):
        if self.is_backtest: return []
        try:
            instruments = [i for i in kite.instruments(self.exchange) if i['name'] == self.index_name and i['instrument_type'] in ['CE', 'PE']]
            if not instruments: raise Exception(f"No {self.index_name} options found for the {self.exchange} exchange.")
            return instruments
        except Exception as e: print(f"FATAL: Could not load instruments for {self.exchange}: {e}"); raise e

    def get_weekly_expiry(self):
        if self.is_backtest: return date.today() + timedelta(days=2)
        today = date.today(); future_expiries = sorted([i['expiry'] for i in self.option_instruments if i.get('expiry') and i['expiry'] >= today]); return future_expiries[0] if future_expiries else None

    def _calculate_indicators(self, df):
        df = df.copy(); df['sma'] = df['close'].rolling(window=self.STRATEGY_PARAMS['sma_period']).mean(); df['wma'] = calculate_wma(df['close'], length=self.STRATEGY_PARAMS['wma_period'])
        df['rsi'] = calculate_rsi(df['close'], length=self.STRATEGY_PARAMS['rsi_period']); df['rsi_sma'] = df['rsi'].rolling(window=self.STRATEGY_PARAMS['rsi_signal_period']).mean()
        df['atr'] = calculate_atr(df['high'], df['low'], df['close'], length=self.STRATEGY_PARAMS['atr_period']); return df

    def get_entry_option(self, side, strike=None):
        spot = self.prices.get(self.index_symbol)
        if not spot: return None
        if strike is None: strike = self.strike_step * round(spot / self.strike_step)
        if self.is_backtest:
            return {'tradingsymbol': f"{self.index_name}{strike}{side}", 'instrument_type': side, 'strike': strike, 'lot_size': 15 if self.index_name == "SENSEX" else 50}
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

    async def map_option_tokens(self, tokens):
        for o in self.option_instruments:
            if o['instrument_token'] in tokens: self.token_to_symbol[o['instrument_token']] = o['tradingsymbol']
        await self._log_debug("Tokens", f"Mapped {len(self.token_to_symbol)} symbols for websocket.")

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
            token = opt.get('instrument_token', opt.get('tradingsymbol'))
            if token in self.uoa_watchlist: return False
            self.uoa_watchlist[token] = {'symbol': opt['tradingsymbol'], 'type': side, 'strike': strike}
            await self._log_debug("UOA", f"Added {opt['tradingsymbol']} to watchlist."); await self._update_ui_uoa_list(); await _play_entry_sound(self.manager)
            if self.ticker_manager and not self.is_backtest:
                tokens = self.get_all_option_tokens()
                await self.map_option_tokens(tokens)
                self.ticker_manager.resubscribe(tokens)
            return True
        await self._log_debug("UOA", f"Could not find {side} option for strike {strike}"); return False

    async def scan_for_unusual_activity(self):
        if self.is_backtest: return
        try:
            await self._log_debug("Scanner", "Running intelligent UOA scan...")
            spot = self.prices.get(self.index_symbol)
            if not spot: await self._log_debug("Scanner", "Aborting scan: Index price not available."); return
            atm_strike = self.strike_step * round(spot / self.strike_step); scan_range = 5 if self.index_name == "NIFTY" else 8
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
            if found_count == 0: await self._log_debug("Scanner", "Scan complete. No new high-conviction opportunities found.")
        except Exception as e:
            await self._log_debug("Scanner ERROR", f"An error occurred during UOA scan: {e}")
