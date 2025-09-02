import asyncio
import json
import pandas as pd
from datetime import datetime, date, timedelta, time
from typing import TYPE_CHECKING, Optional
import math
import numpy as np

from .kite import kite
from .websocket_manager import ConnectionManager
from .data_manager import DataManager
from .risk_manager import RiskManager
from .trade_logger import TradeLogger
from .order_manager import OrderManager
from .database import today_engine, sql_text
from .entry_strategies import (
    IntraCandlePatternStrategy,
    UoaEntryStrategy,
    TrendContinuationStrategy,
    RsiImmediateEntryStrategy,
    MaCrossoverStrategy,
    CandlePatternEntryStrategy
)

if TYPE_CHECKING:
    from .kite_ticker_manager import KiteTickerManager

def _play_sound(manager, sound): asyncio.create_task(manager.broadcast({"type": "play_sound", "payload": sound}))

# ... (Constants like INDEX_CONFIG and MARKET_STANDARD_PARAMS are unchanged) ...
INDEX_CONFIG = {
    "NIFTY": {"name": "NIFTY", "token": 256265, "symbol": "NSE:NIFTY 50", "strike_step": 50, "exchange": "NFO"},
    "SENSEX": {"name": "SENSEX", "token": 265, "symbol": "BSE:SENSEX", "strike_step": 100, "exchange": "BFO"},
}

MARKET_STANDARD_PARAMS = {
    "strategy_priority": ["UOA", "TREND_CONTINUATION", "MA_CROSSOVER", "CANDLE_PATTERN", "RSI", "INTRA_CANDLE"],
    'wma_period': 9, 'sma_period': 9, 'rsi_period': 9, 'rsi_signal_period': 3,
    'rsi_angle_lookback': 2, 'rsi_angle_threshold': 15.0, 'atr_period': 14,
    'min_atr_value': 4, 'ma_gap_threshold_pct': 0.05
}


class Strategy:
    # ... (__init__ and other methods are unchanged up to evaluate_exit_logic) ...
    def __init__(self, params, manager: ConnectionManager, selected_index="SENSEX"):
        self.params = self._sanitize_params(params)
        self.manager = manager
        self.ticker_manager: Optional["KiteTickerManager"] = None
        self.config = INDEX_CONFIG[selected_index]
        self.ui_update_task: Optional[asyncio.Task] = None
        self.position_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        
        self.is_backtest = False
        
        self.index_name, self.index_token, self.index_symbol, self.strike_step, self.exchange = \
            self.config["name"], self.config["token"], self.config["symbol"], self.config["strike_step"], self.config["exchange"]

        self.trend_candle_count = 0
        self.pending_steep_signal = None

        self.data_manager = DataManager(self.index_token, self.index_symbol, self.STRATEGY_PARAMS, self._log_debug, self.on_trend_update)
        self.risk_manager = RiskManager(self.params, self._log_debug)
        self.trade_logger = TradeLogger(self.db_lock)
        self.order_manager = OrderManager(self._log_debug)

        strategy_map = {
            "INTRA_CANDLE": IntraCandlePatternStrategy, "UOA": UoaEntryStrategy,
            "TREND_CONTINUATION": TrendContinuationStrategy, "RSI": RsiImmediateEntryStrategy,
            "MA_CROSSOVER": MaCrossoverStrategy, "CANDLE_PATTERN": CandlePatternEntryStrategy
        }
        self.entry_strategies = []
        default_priority = ["UOA", "TREND_CONTINUATION", "MA_CROSSOVER", "CANDLE_PATTERN", "RSI", "INTRA_CANDLE"]
        priority_list = self.STRATEGY_PARAMS.get("strategy_priority", default_priority)
        for name in priority_list:
            if name in strategy_map:
                self.entry_strategies.append(strategy_map[name](self))
        
        self._reset_state()
        self.option_instruments = self.load_instruments()
        self.last_used_expiry = self.get_weekly_expiry()

    async def _calculate_trade_charges(self, tradingsymbol, exchange, entry_price, exit_price, quantity):
        brokerage = 40; 
        sell_value = exit_price * quantity; 
        buy_value = entry_price * quantity
        stt = sell_value * 0.000625; 
        txn_charges = (buy_value + sell_value) * 0.00053
        gst = (brokerage + txn_charges) * 0.18; 
        return brokerage + stt + txn_charges + gst

    def _reset_state(self):
        self.position = None; self.daily_gross_pnl = 0; self.daily_net_pnl = 0; self.total_charges = 0
        self.daily_profit = 0; self.daily_loss = 0; self.daily_trade_limit_hit = False
        self.trades_this_minute = 0; self.initial_subscription_done = False
        self.token_to_symbol = {self.index_token: self.index_symbol}; self.uoa_watchlist = {}
        self.performance_stats = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0}
        self.exit_cooldown_until: Optional[datetime] = None; self.disconnected_since: Optional[datetime] = None
        self.next_partial_profit_level = 1; self.trend_candle_count = 0
        self.pending_steep_signal = None

    async def _restore_daily_performance(self):
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
                last['open'] > prev['close'] and last['close'] < prev['open'] and
                last_body > prev_body * 0.8)

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
                    await self._update_ui_status(); await self._update_ui_option_chain(); await self._update_ui_chart_data()
                await asyncio.sleep(1)
            except asyncio.CancelledError: await self._log_debug("UI Updater", "Task cancelled."); break
            except Exception as e: await self._log_debug("UI Updater Error", f"An error occurred: {e}"); await asyncio.sleep(5)

    async def take_trade(self, trigger, opt):
        async with self.position_lock:
            if self.position or not opt: return
        instrument_token = opt.get("instrument_token")
        symbol, side, price, lot_size = opt["tradingsymbol"], opt["instrument_type"], self.data_manager.prices.get(opt["tradingsymbol"]), opt.get("lot_size")
        qty, initial_sl_price = self.risk_manager.calculate_trade_details(price, lot_size)
        if qty is None or instrument_token is None: await self._log_debug("Trade Rejected", "Could not calculate quantity or find instrument token."); return
        try:
            if self.params.get("trading_mode") == "Live Trading":
                await self.order_manager.execute_order(transaction_type=kite.TRANSACTION_TYPE_BUY, tradingsymbol=symbol, exchange=self.exchange, quantity=qty)
                await self._log_debug("LIVE TRADE", f"Confirmed BUY for {symbol}. Qty: {qty} @ Price: {price:.2f}.Reason: {trigger}")
            else:
                await self._log_debug("PAPER TRADE", f"Simulating BUY order for {symbol}. Qty: {qty} @ Price: {price:.2f}.Reason: {trigger}")
            self.position = {"symbol": symbol, "entry_price": price, "direction": side, "qty": qty, "trail_sl": round(initial_sl_price, 2), "max_price": price, "trigger_reason": trigger, "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lot_size": lot_size}
            if self.ticker_manager:
                await self._log_debug("WebSocket", f"Subscribing to active trade token: {instrument_token}")
                self.ticker_manager.subscribe([instrument_token])
            self.trades_this_minute += 1; self.performance_stats["total_trades"] += 1
            self.next_partial_profit_level = 1; _play_sound(self.manager, "entry"); await self._update_ui_trade_status()
        except Exception as e:
            await self._log_debug("CRITICAL-ENTRY-FAIL", f"Failed to execute entry for {symbol}: {e}"); _play_sound(self.manager, "loss")

    async def exit_position(self, reason):
        if not self.position: return
        p = self.position; exit_price = self.data_manager.prices.get(p["symbol"], p["max_price"])
        try:
            # --- NEW: Added a debug log for the sell action for clarity ---
            sell_log_message = f"Simulating SELL order for {p['symbol']}. Reason: {reason}"
            if self.params.get("trading_mode") == "Live Trading":
                await self._log_debug("LIVE TRADE", sell_log_message)
                await self.order_manager.execute_order(transaction_type=kite.TRANSACTION_TYPE_SELL, tradingsymbol=p["symbol"], exchange=self.exchange, quantity=p["qty"])
            else:
                await self._log_debug("PAPER TRADE", sell_log_message)
                
            gross_pnl = (exit_price - p["entry_price"]) * p["qty"]
            charges = await self._calculate_trade_charges(tradingsymbol=p["symbol"], exchange=self.exchange, entry_price=p["entry_price"], exit_price=exit_price, quantity=p["qty"])
            net_pnl = gross_pnl - charges
            self.daily_gross_pnl += gross_pnl; self.total_charges += charges; self.daily_net_pnl += net_pnl
            if gross_pnl > 0: self.performance_stats["winning_trades"] += 1; self.daily_profit += gross_pnl; _play_sound(self.manager, "profit")
            else: self.performance_stats["losing_trades"] += 1; self.daily_loss += gross_pnl; _play_sound(self.manager, "loss")
            log_info = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": p["qty"], "pnl": round(gross_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.data_manager.trend_state, "atr": round(self.data_manager.data_df.iloc[-1]["atr"], 2) if not self.data_manager.data_df.empty else 0, "charges": round(charges, 2), "net_pnl": round(net_pnl, 2) }
            await self.trade_logger.log_trade(log_info)
            await self._log_debug("Database", f"Trade for {p['symbol']} logged successfully.")
            await self.manager.broadcast({"type": "new_trade_log", "payload": log_info})
            self.position = None; self.exit_cooldown_until = datetime.now() + timedelta(seconds=5)
            await self._log_debug("System", "Exit cooldown initiated for 5 seconds.")
            await self._update_ui_trade_status(); await self._update_ui_performance()
        except Exception as e:
            await self._log_debug("CRITICAL-EXIT-FAIL", f"FAILED TO EXIT {p['symbol']}! MANUAL INTERVENTION REQUIRED! Error: {e}"); _play_sound(self.manager, "warning")

    # --- THIS IS THE CORRECTED FUNCTION ---
    async def evaluate_exit_logic(self):
        async with self.position_lock:
            if not self.position: return
            
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"])
            if ltp is None: return

            # Standard Trailing Stop-Loss Logic
            if ltp > p["max_price"]: p["max_price"] = ltp
            sl_points = float(self.params.get("trailing_sl_points", 5.0))
            sl_percent = float(self.params.get("trailing_sl_percent", 10.0))
            p["trail_sl"] = round(max(p["trail_sl"], max(p["max_price"] - sl_points, p["max_price"] * (1 - sl_percent / 100))), 2)
            await self._update_ui_trade_status()
            
            if ltp <= p["trail_sl"]:
                await self.exit_position("Trailing SL")
                return

            # Invalidation Exit Logic
            if 'open' in self.data_manager.current_candle and not self.data_manager.data_df.empty:
                live_index_candle = self.data_manager.current_candle
                prev_index_candle = self.data_manager.data_df.iloc[-1]
                
                if p['direction'] == 'CE' and self._is_bearish_engulfing(prev_index_candle, live_index_candle):
                    await self._log_debug("Exit Logic", "Invalidation: Bearish Engulfing on index. Exiting CE.")
                    await self.exit_position("Invalidation: Bearish Engulfing")
                    return
                elif p['direction'] == 'PE' and self._is_bullish_engulfing(prev_index_candle, live_index_candle):
                    await self._log_debug("Exit Logic", "Invalidation: Bullish Engulfing on index. Exiting PE.")
                    await self.exit_position("Invalidation: Bullish Engulfing")
                    return
    
    # ... (the rest of the file continues below) ...
    async def partial_exit_position(self):
        # ... (This function remains unchanged) ...
        if not self.position: return
        p, partial_exit_pct = self.position, self.params.get("partial_exit_pct", 50); lot_size = p.get("lot_size", 1)
        if lot_size <= 0: lot_size = 1
        qty_to_exit = int(min(math.ceil((p["qty"] / lot_size) * (partial_exit_pct / 100)) * lot_size, p["qty"]))
        if qty_to_exit <= 0: return
        if (p["qty"] - qty_to_exit) < lot_size: await self.exit_position(f"Final Partial Profit-Take"); return
        exit_price = self.data_manager.prices.get(p["symbol"], p["entry_price"])
        try:
            if self.params.get("trading_mode") == "Live Trading":
                await self.order_manager.execute_order(transaction_type=kite.TRANSACTION_TYPE_SELL, tradingsymbol=p["symbol"], exchange=self.exchange, quantity=qty_to_exit)
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
            await self._log_debug("Profit.Take", f"Remaining quantity: {p['qty']}.")
            await self._update_ui_trade_status(); await self._update_ui_performance()
        except Exception as e:
            await self._log_debug("CRITICAL-PARTIAL-EXIT-FAIL", f"Failed to partially exit {p['symbol']}: {e}"); _play_sound(self.manager, "warning")

    async def check_partial_profit_take(self):
        if not self.position: return
        # This needs to be inside the lock to prevent race conditions with exit_position
        async with self.position_lock:
            if not self.position: return # Check again after acquiring lock
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"])
            if ltp is None: return
            partial_profit_pct = self.params.get("partial_profit_pct", 0)
            if partial_profit_pct <= 0: return
            profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
            target_pct = partial_profit_pct * self.next_partial_profit_level
            if profit_pct >= target_pct: await self.partial_exit_position()

    async def handle_ticks_async(self, ticks):
        try:
            if not self.initial_subscription_done and any(t.get("instrument_token") == self.index_token for t in ticks):
                self.data_manager.prices[self.index_symbol] = next(t["last_price"] for t in ticks if t.get("instrument_token") == self.index_token)
                await self._log_debug("WebSocket", "Index price received. Subscribing to full token list.")
                tokens = self.get_all_option_tokens(); await self.map_option_tokens(tokens)
                if self.ticker_manager: self.ticker_manager.resubscribe(tokens)
                self.initial_subscription_done = True
            for tick in ticks:
                token, ltp = tick.get("instrument_token"), tick.get("last_price")
                if token is not None and ltp is not None and (symbol := self.token_to_symbol.get(token)):
                    self.data_manager.prices[symbol] = ltp; self.data_manager.update_price_history(symbol, ltp)
                    is_new_minute = self.data_manager.update_live_candle(ltp, symbol)
                    if symbol == self.index_symbol:
                        if is_new_minute: self.trades_this_minute = 0; await self.data_manager.on_new_minute(ltp)
                        await self.check_trade_entry()
                    
                    # --- THIS IS THE CORRECTED LOGIC ---
                    if self.position and self.position["symbol"] == symbol:
                        await self.check_partial_profit_take()
                        await self.evaluate_exit_logic()
        except Exception as e: await self._log_debug("Tick Handler Error", f"Critical error: {e}")

    async def _check_pending_reversal_entry(self):
        if not self.pending_steep_signal: return False
        signal_to_check = self.pending_steep_signal; self.pending_steep_signal = None
        side, reason = signal_to_check['side'], signal_to_check['reason']
        opt = self.get_entry_option(side)
        if opt and self.entry_strategies:
            validator = self.entry_strategies[0]
            if await validator._validate_entry_conditions(side, opt):
                await self.take_trade(reason, opt); return True
        return False

    def _set_pending_reversal_signal(self):
        if len(self.data_manager.data_df) < 1: return
        last = self.data_manager.data_df.iloc[-1]; is_bullish_candle = last['close'] > last['open']
        if last['wma'] > last['sma'] and not is_bullish_candle:
            self.pending_steep_signal = {'side': 'PE', 'reason': 'Reversal_PE'}
        elif last['wma'] < last['sma'] and is_bullish_candle:
            self.pending_steep_signal = {'side': 'CE', 'reason': 'Reversal_CE'}
        else:
            self.pending_steep_signal = None

    async def check_trade_entry(self):
        if self.position is not None or self.daily_trade_limit_hit: return
        if self.exit_cooldown_until and datetime.now() < self.exit_cooldown_until: return
        if self.trades_this_minute >= 2: return
        daily_sl, daily_pt = self.params.get("daily_sl", 0), self.params.get("daily_pt", 0)
        if (daily_sl < 0 and self.daily_gross_pnl <= daily_sl) or (daily_pt > 0 and self.daily_gross_pnl >= daily_pt):
            self.daily_trade_limit_hit = True; await self._log_debug("RISK", "Daily Gross SL/PT hit. Trading disabled."); return
        if await self._check_pending_reversal_entry(): return
        for entry_strategy in self.entry_strategies:
            side, reason = await entry_strategy.check()
            if side and reason:
                if opt := self.get_entry_option(side):
                    await self.take_trade(reason, opt)
                    return
        self._set_pending_reversal_signal()
        
    async def on_ticker_connect(self):
        await self._log_debug("WebSocket", f"Connected. Subscribing to index: {self.index_symbol}")
        await self._update_ui_status()
        if self.ticker_manager: self.ticker_manager.resubscribe([self.index_token])

    async def on_ticker_disconnect(self):
        await self._update_ui_status(); await self._log_debug("WebSocket", "Kite Ticker Disconnected.")

    @property
    def STRATEGY_PARAMS(self):
        try:
            with open("strategy_params.json", "r") as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return MARKET_STANDARD_PARAMS.copy()
    
    async def _log_debug(self, source, message): await self.manager.broadcast({"type": "debug_log", "payload": {"time": datetime.now().strftime("%H:%M:%S"), "source": source, "message": message}})
    
    async def _update_ui_status(self):
        is_running = self.ticker_manager and self.ticker_manager.is_connected
        payload = { "connection": "CONNECTED" if is_running else "DISCONNECTED", "mode": self.params.get("trading_mode", "Paper").upper(), "indexPrice": self.data_manager.prices.get(self.index_symbol, 0), "is_running": is_running, "trend": self.data_manager.trend_state or "---", "indexName": self.index_name }
        await self.manager.broadcast({"type": "status_update", "payload": payload})

    async def _update_ui_performance(self):
        payload = { "grossPnl": self.daily_gross_pnl, "totalCharges": self.total_charges, "netPnl": self.daily_net_pnl, "wins": self.performance_stats["winning_trades"], "losses": self.performance_stats["losing_trades"] }
        await self.manager.broadcast({"type": "daily_performance_update", "payload": payload})

    async def _update_ui_trade_status(self):
        payload = None
        if self.position: 
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"], self.position["entry_price"])
            pnl = (ltp - p["entry_price"]) * p["qty"]; profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
            payload = {"symbol": p["symbol"], "entry_price": p["entry_price"],"ltp": ltp, "pnl": pnl, "profit_pct": profit_pct, "trail_sl": p["trail_sl"], "max_price": p["max_price"]}
        await self.manager.broadcast({"type": "trade_status_update", "payload": payload})

    async def _update_ui_uoa_list(self): await self.manager.broadcast({"type": "uoa_list_update", "payload": list(self.uoa_watchlist.values())})

    async def _update_ui_option_chain(self):
        pairs, data = self.get_strike_pairs(), []
        if self.data_manager.prices.get(self.index_symbol) and pairs:
            for p in pairs: 
                ce_symbol = p["ce"]["tradingsymbol"] if p["ce"] else None; pe_symbol = p["pe"]["tradingsymbol"] if p["pe"] else None
                data.append({"strike": p["strike"], "ce_ltp": self.data_manager.prices.get(ce_symbol, "--") if ce_symbol else "--", "pe_ltp": self.data_manager.prices.get(pe_symbol, "--") if pe_symbol else "--"})
        await self.manager.broadcast({"type": "option_chain_update", "payload": data})

    async def _update_ui_chart_data(self):
        temp_df = self.data_manager.data_df.copy()
        if self.data_manager.current_candle.get("minute"):
            live_candle_df = pd.DataFrame([self.data_manager.current_candle], index=[self.data_manager.current_candle["minute"]])
            temp_df = pd.concat([temp_df, live_candle_df])
        if not temp_df.index.is_unique: temp_df = temp_df[~temp_df.index.duplicated(keep='last')]
        if not temp_df.index.is_monotonic_increasing: temp_df.sort_index(inplace=True)
        chart_data = {"candles": [], "wma": [], "sma": [], "rsi": [], "rsi_sma": []}
        if not temp_df.empty:
            for index, row in temp_df.iterrows():
                timestamp = int(index.timestamp())
                chart_data["candles"].append({"time": timestamp, "open": row.get("open", 0), "high": row.get("high", 0), "low": row.get("low", 0), "close": row.get("close", 0)})
                if pd.notna(row.get("wma")): chart_data["wma"].append({"time": timestamp, "value": row["wma"]})
                if pd.notna(row.get("sma")): chart_data["sma"].append({"time": timestamp, "value": row["sma"]})
                if pd.notna(row.get("rsi")): chart_data["rsi"].append({"time": timestamp, "value": row["rsi"]})
                if pd.notna(row.get("rsi_sma")): chart_data["rsi_sma"].append({"time": timestamp, "value": row["rsi_sma"]})
        await self.manager.broadcast({"type": "chart_data_update", "payload": chart_data})

    def calculate_uoa_conviction_score(self, option_data, atm_strike):
        score, v_oi_ratio = 0, option_data.get('volume', 0) / (option_data.get('oi', 0) + 1)
        score += min(v_oi_ratio / 2.0, 5); score += min(option_data.get('change', 0) / 10.0, 5)
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
            await self._log_debug("UOA", f"Added {opt['tradingsymbol']} to watchlist.")
            await self._update_ui_uoa_list(); _play_sound(self.manager, "entry")
            if self.ticker_manager and not self.is_backtest:
                tokens = self.get_all_option_tokens(); await self.map_option_tokens(tokens)
                self.ticker_manager.resubscribe(tokens)
            return True
        await self._log_debug("UOA", f"Could not find {side} option for strike {strike}"); _play_sound(self.manager, "warning"); return False
    
    async def scan_for_unusual_activity(self):
        if self.is_backtest: return
        try:
            await self._log_debug("Scanner", "Running intelligent UOA scan...")
            spot = self.data_manager.prices.get(self.index_symbol)
            if not spot: await self._log_debug("Scanner", "Aborting scan: Index price not available."); return
            atm_strike = self.strike_step * round(spot / self.strike_step); scan_range = 5 if self.index_name == "NIFTY" else 8
            target_strikes = [atm_strike + (i * self.strike_step) for i in range(-scan_range, scan_range + 1)]
            target_options = [i for i in self.option_instruments if i['expiry'] == self.last_used_expiry and i['strike'] in target_strikes]
            if not target_options: return
            quotes = await asyncio.to_thread(lambda: kite.quote([opt['instrument_token'] for opt in target_options]))
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
        except Exception as e: await self._log_debug("Scanner ERROR", f"An error occurred during UOA scan: {e}")

    async def on_trend_update(self, new_trend):
        if self.data_manager.trend_state != new_trend: self.trend_candle_count = 1
        else: self.trend_candle_count += 1
    
    def load_instruments(self):
        try: return [i for i in kite.instruments(self.exchange) if i['name'] == self.index_name and i['instrument_type'] in ['CE', 'PE']]
        except Exception as e: print(f"FATAL: Could not load instruments: {e}"); raise e

    def get_weekly_expiry(self): 
        today = date.today()
        future_expiries = sorted([i['expiry'] for i in self.option_instruments if i.get('expiry') and i['expiry'] >= today])
        return future_expiries[0] if future_expiries else None

    def get_all_option_tokens(self):
        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot: return [self.index_token]
        atm_strike = self.strike_step * round(spot / self.strike_step)
        strikes = [atm_strike + (i - 3) * self.strike_step for i in range(7)]
        tokens = {self.index_token, *[opt['instrument_token'] for strike in strikes for side in ['CE', 'PE'] if (opt := self.get_entry_option(side, strike))], *self.uoa_watchlist.keys()}
        return list(tokens)

    async def map_option_tokens(self, tokens):
        self.token_to_symbol = {o['instrument_token']: o['tradingsymbol'] for o in self.option_instruments if o['instrument_token'] in tokens}
        self.token_to_symbol[self.index_token] = self.index_symbol

    def get_strike_pairs(self, count=7):
        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot: return []
        atm_strike = self.strike_step * round(spot / self.strike_step)
        strikes = [atm_strike + (i - count // 2) * self.strike_step for i in range(count)]
        return [{"strike": strike, "ce": self.get_entry_option('CE', strike), "pe": self.get_entry_option('PE', strike)} for strike in strikes]

    def get_entry_option(self, side, strike=None):
        spot = self.data_manager.prices.get(self.index_symbol)
        if not spot: return None
        if strike is None: strike = self.strike_step * round(spot / self.strike_step)
        for o in self.option_instruments:
            if o['expiry'] == self.last_used_expiry and o['strike'] == strike and o['instrument_type'] == side: return o
        return None

    def _sanitize_params(self, params):
        p = params.copy()
        try:
            for key in ["start_capital", "trailing_sl_points", "trailing_sl_percent", "daily_sl", "daily_pt", "partial_profit_pct", "partial_exit_pct", "risk_per_trade_percent"]:
                if key in p and p[key]: p[key] = float(p[key])
        except (ValueError, TypeError) as e: print(f"Warning: Could not convert a parameter to a number: {e}")
        return p