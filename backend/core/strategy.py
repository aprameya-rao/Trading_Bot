import asyncio
import json
import pandas as pd
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING, Optional
import math

from .kite import kite
from .websocket_manager import ConnectionManager
from .data_manager import DataManager
from .risk_manager import RiskManager
from .trade_logger import TradeLogger
from .order_manager import OrderManager
from .entry_strategies import (
    UoaEntryStrategy, MaCrossoverAnticipationStrategy, TrendContinuationStrategy,
    CandlestickEntryStrategy, RsiImmediateEntryStrategy
)

if TYPE_CHECKING:
    from .kite_ticker_manager import KiteTickerManager

def _play_sound(manager, sound): asyncio.create_task(manager.broadcast({"type": "play_sound", "payload": sound}))

INDEX_CONFIG = {
    "NIFTY": {"name": "NIFTY", "token": 256265, "symbol": "NSE:NIFTY 50", "strike_step": 50, "exchange": "NFO"},
    "SENSEX": {"name": "SENSEX", "token": 265, "symbol": "BSE:SENSEX", "strike_step": 100, "exchange": "BFO"},
}

MARKET_STANDARD_PARAMS = {
    "strategy_priority": ["UOA", "MA_CROSSOVER", "TREND_CONTINUATION", "CANDLESTICK", "RSI"],
    'wma_period': 9, 'sma_period': 9, 'rsi_period': 9, 'rsi_signal_period': 3,
    'rsi_angle_lookback': 2, 'rsi_angle_threshold': 15.0, 'atr_period': 14,
    'min_atr_value': 4, 'ma_gap_threshold_pct': 0.05
}

class Strategy:
    """
    The refactored Strategy class now acts as an orchestrator, coordinating
    specialized components for data, risk, logging, and entry logic.
    """
    def __init__(self, params, manager: ConnectionManager, selected_index="SENSEX"):
        self.params = self._sanitize_params(params)
        self.manager = manager
        self.ticker_manager: Optional["KiteTickerManager"] = None
        self.config = INDEX_CONFIG[selected_index]
        self.ui_update_task: Optional[asyncio.Task] = None
        self.position_lock = asyncio.Lock()
        self.db_lock = asyncio.Lock()
        
        self.index_name, self.index_token, self.index_symbol, self.strike_step, self.exchange = \
            self.config["name"], self.config["token"], self.config["symbol"], self.config["strike_step"], self.config["exchange"]

        # --- Initialize refactored components ---
        self.data_manager = DataManager(self.index_token, self.index_symbol, self.STRATEGY_PARAMS, self._log_debug, self.on_trend_update)
        self.risk_manager = RiskManager(self.params, self._log_debug)
        self.trade_logger = TradeLogger(self.db_lock)
        self.order_manager = OrderManager(self._log_debug)

        # --- Dynamically build entry strategies based on config ---
        strategy_map = {
            "UOA": UoaEntryStrategy, "MA_CROSSOVER": MaCrossoverAnticipationStrategy,
            "TREND_CONTINUATION": TrendContinuationStrategy, "CANDLESTICK": CandlestickEntryStrategy,
            "RSI": RsiImmediateEntryStrategy
        }
        self.entry_strategies = []
        # Use a default priority list if the key is missing in params
        default_priority = ["UOA", "MA_CROSSOVER", "TREND_CONTINUATION", "CANDLESTICK", "RSI"]
        priority_list = self.STRATEGY_PARAMS.get("strategy_priority", default_priority)
        for name in priority_list:
            if name in strategy_map:
                self.entry_strategies.append(strategy_map[name](self))
        
        self._reset_state()
        self.option_instruments = self.load_instruments()
        self.last_used_expiry = self.get_weekly_expiry()

    async def run(self):
        await self._log_debug("System", "Strategy instance created.")
        await self.data_manager.bootstrap_data()
        if not self.ui_update_task or self.ui_update_task.done():
            self.ui_update_task = asyncio.create_task(self.periodic_ui_updater())
    
    async def periodic_ui_updater(self):
        while True:
            try:
                # Failsafe logic for ticker disconnection
                if self.position and (not self.ticker_manager or not self.ticker_manager.is_connected):
                    if self.disconnected_since is None:
                        self.disconnected_since = datetime.now()
                        await self._log_debug("CRITICAL", "Ticker disconnected in trade! Starting 15s failsafe timer.")
                    
                    if datetime.now() - self.disconnected_since > timedelta(seconds=15):
                        await self._log_debug("CRITICAL", "Failsafe triggered! Exiting position due to prolonged disconnection.")
                        await self.exit_position("Failsafe: Ticker Disconnected")
                
                elif self.ticker_manager and self.ticker_manager.is_connected:
                    if self.disconnected_since is not None:
                        await self._log_debug("INFO", "Ticker reconnected, failsafe timer cancelled.")
                        self.disconnected_since = None
                    
                    # Original UI update logic
                    await self._update_ui_status()
                    await self._update_ui_option_chain()
                    await self._update_ui_chart_data()

                await asyncio.sleep(1)
            except asyncio.CancelledError: await self._log_debug("UI Updater", "Task cancelled."); break
            except Exception as e: await self._log_debug("UI Updater Error", f"An error occurred: {e}"); await asyncio.sleep(5)

    async def take_trade(self, trigger, opt):
        async with self.position_lock:
            if self.position or not opt: return
            
            symbol, side, price, lot_size = opt["tradingsymbol"], opt["instrument_type"], self.data_manager.prices.get(opt["tradingsymbol"]), opt.get("lot_size")
            qty, initial_sl_price = self.risk_manager.calculate_trade_details(price, lot_size)
            if qty is None: return

            try:
                if self.params.get("trading_mode") == "Live Trading":
                    await self.order_manager.execute_order(
                        transaction_type=kite.TRANSACTION_TYPE_BUY,
                        tradingsymbol=symbol, exchange=self.exchange, quantity=qty
                    )
                    await self._log_debug("LIVE TRADE", f"Confirmed BUY for {qty} {symbol}.")
                else:
                    await self._log_debug("PAPER TRADE", f"Simulating BUY order for {qty} {symbol}.")

                self.position = {"symbol": symbol, "entry_price": price, "direction": side, "qty": qty, "trail_sl": round(initial_sl_price, 2), "max_price": price, "trigger_reason": trigger, "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lot_size": lot_size}
                self.trades_this_minute += 1; self.performance_stats["total_trades"] += 1
                self.next_partial_profit_level = 1
                _play_sound(self.manager, "entry")
                await self._update_ui_trade_status()

            except Exception as e:
                await self._log_debug("CRITICAL-ENTRY-FAIL", f"Failed to execute entry for {symbol}: {e}")
                _play_sound(self.manager, "loss")

    async def exit_position(self, reason):
        async with self.position_lock:
            if not self.position: return
            p = self.position
            # Use last known price for exit, as LTP might not be available during disconnection
            exit_price = self.data_manager.prices.get(p["symbol"], p["max_price"])
            
            try:
                if self.params.get("trading_mode") == "Live Trading":
                    await self.order_manager.execute_order(
                        transaction_type=kite.TRANSACTION_TYPE_SELL,
                        tradingsymbol=p["symbol"], exchange=self.exchange, quantity=p["qty"]
                    )
                # Log both paper and live trades after simulated/confirmed execution
                net_pnl = (exit_price - p["entry_price"]) * p["qty"]
                self.daily_pnl += net_pnl
                if net_pnl > 0: self.performance_stats["winning_trades"] += 1; self.daily_profit += net_pnl; _play_sound(self.manager, "profit")
                else: self.performance_stats["losing_trades"] += 1; self.daily_loss += net_pnl; _play_sound(self.manager, "loss")

                log_info = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": p["qty"], "pnl": round(net_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.data_manager.trend_state, "atr": round(self.data_manager.data_df.iloc[-1]["atr"], 2) if not self.data_manager.data_df.empty else 0 }
                await self.trade_logger.log_trade(log_info)

                self.position = None # Nullify position only after successful exit and logging
                self.exit_cooldown_until = datetime.now() + timedelta(seconds=5)
                await self._update_ui_trade_status(); await self._update_ui_performance()

            except Exception as e:
                await self._log_debug("CRITICAL-EXIT-FAIL", f"FAILED TO EXIT {p['symbol']}! MANUAL INTERVENTION REQUIRED! Error: {e}")
                _play_sound(self.manager, "warning")

    async def evaluate_exit_logic(self):
        async with self.position_lock:
            if not self.position: return
            p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"])
            if ltp is None: return

            partial_profit_pct = self.params.get("partial_profit_pct", 0)
            if partial_profit_pct > 0:
                profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0)
                if profit_pct >= (partial_profit_pct * self.next_partial_profit_level):
                    await self.partial_exit_position()
                    return 
            
            if ltp > p["max_price"]: p["max_price"] = ltp
            sl_points = float(self.params["trailing_sl_points"])
            sl_percent = float(self.params["trailing_sl_percent"])
            p["trail_sl"] = round(max(p["trail_sl"], max(p["max_price"] - sl_points, p["max_price"] * (1 - sl_percent / 100))), 2)

            await self._update_ui_trade_status()
            if ltp <= p["trail_sl"]: await self.exit_position("Trailing SL")

    async def partial_exit_position(self):
        if not self.position: return
        p, partial_exit_pct = self.position, self.params.get("partial_exit_pct", 50)
        lot_size = p.get("lot_size", 1)
        if lot_size <= 0: lot_size = 1
        qty_to_exit = int(min(math.ceil((p["qty"] / lot_size) * (partial_exit_pct / 100)) * lot_size, p["qty"]))
        if qty_to_exit <= 0: return
        if (p["qty"] - qty_to_exit) < lot_size: await self.exit_position(f"Final Partial Profit-Take"); return

        exit_price = self.data_manager.prices.get(p["symbol"], p["entry_price"])
        try:
            if self.params.get("trading_mode") == "Live Trading":
                await self.order_manager.execute_order(
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    tradingsymbol=p["symbol"], exchange=self.exchange, quantity=qty_to_exit
                )
            
            net_pnl = (exit_price - p["entry_price"]) * qty_to_exit
            self.daily_pnl += net_pnl
            if net_pnl > 0: self.daily_profit += net_pnl; _play_sound(self.manager, "profit")
            
            reason = f"Partial Profit-Take ({self.next_partial_profit_level})"
            log_info = { "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "trigger_reason": p["trigger_reason"], "symbol": p["symbol"], "quantity": qty_to_exit, "pnl": round(net_pnl, 2), "entry_price": p["entry_price"], "exit_price": exit_price, "exit_reason": reason, "trend_state": self.data_manager.trend_state, "atr": round(self.data_manager.data_df.iloc[-1]["atr"], 2) if not self.data_manager.data_df.empty else 0 }
            await self.trade_logger.log_trade(log_info)

            p["qty"] -= qty_to_exit
            self.next_partial_profit_level += 1
            await self._log_debug("Profit.Take", f"Remaining quantity: {p['qty']}.")
            await self._update_ui_trade_status(); await self._update_ui_performance()
        except Exception as e:
            await self._log_debug("CRITICAL-PARTIAL-EXIT-FAIL", f"Failed to partially exit {p['symbol']}: {e}")
            _play_sound(self.manager, "warning")

    # The rest of the file continues with all helper, UI, and callback methods
    # ... (Code from previous answers for handle_ticks_async, check_trade_entry, UI updaters, etc.)
    # The following is a condensed version of the remaining unchanged methods for completeness.
    
    def _reset_state(self):
        self.position, self.daily_pnl, self.daily_profit, self.daily_loss, self.daily_trade_limit_hit = None, 0, 0, 0, False
        self.trades_this_minute, self.initial_subscription_done = 0, False
        self.token_to_symbol, self.uoa_watchlist = {self.index_token: self.index_symbol}, {}
        self.performance_stats = {"total_trades": 0, "winning_trades": 0, "losing_trades": 0}
        self.exit_cooldown_until: Optional[datetime] = None
        self.disconnected_since: Optional[datetime] = None
        self.next_partial_profit_level = 1
    
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
                    self.data_manager.prices[symbol] = ltp
                    self.data_manager.update_price_history(symbol, ltp)
                    is_new_minute = self.data_manager.update_live_candle(ltp, symbol)
                    if symbol == self.index_symbol:
                        if is_new_minute: self.trades_this_minute = 0; await self.data_manager.on_new_minute()
                        await self.check_trade_entry()
                    if self.position and self.position["symbol"] == symbol: await self.evaluate_exit_logic()
        except Exception as e: await self._log_debug("Tick Handler Error", f"Critical error: {e}")

    async def check_trade_entry(self):
        if self.position is not None or self.daily_trade_limit_hit: return
        if self.exit_cooldown_until and datetime.now() < self.exit_cooldown_until: return
        if self.trades_this_minute >= 2: return
        daily_sl, daily_pt = self.params.get("daily_sl", 0), self.params.get("daily_pt", 0)
        if (daily_sl < 0 and self.daily_pnl <= daily_sl) or (daily_pt > 0 and self.daily_pnl >= daily_pt):
            self.daily_trade_limit_hit = True; await self._log_debug("RISK", "Daily SL/PT hit. Trading disabled."); return
        for entry_strategy in self.entry_strategies:
            side, reason = await entry_strategy.check()
            if side and reason: 
                opt = self.get_entry_option(side)
                if opt: 
                    await self.take_trade(reason, opt)
                return

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
        payload = {"netPnl": self.daily_pnl, "grossProfit": self.daily_profit, "grossLoss": self.daily_loss, "wins": self.performance_stats["winning_trades"], "losses": self.performance_stats["losing_trades"]}
        await self.manager.broadcast({"type": "daily_performance_update", "payload": payload})
    async def _update_ui_trade_status(self):
        payload = None
        if self.position: p, ltp = self.position, self.data_manager.prices.get(self.position["symbol"], self.position["entry_price"]); pnl = (ltp - p["entry_price"]) * p["qty"]; profit_pct = (((ltp - p["entry_price"]) / p["entry_price"]) * 100 if p["entry_price"] > 0 else 0); payload = {"symbol": p["symbol"], "entry_price": p["entry_price"],"ltp": ltp, "pnl": pnl, "profit_pct": profit_pct, "trail_sl": p["trail_sl"], "max_price": p["max_price"]}
        await self.manager.broadcast({"type": "trade_status_update", "payload": payload})
    async def _update_ui_uoa_list(self): await self.manager.broadcast({"type": "uoa_list_update", "payload": list(self.uoa_watchlist.values())})
    async def _update_ui_option_chain(self):
        pairs, data = self.get_strike_pairs(), []
        if self.data_manager.prices.get(self.index_symbol) and pairs:
            for p in pairs: ce_symbol, pe_symbol = (p["ce"]["tradingsymbol"] if p["ce"] else None, p["pe"]["tradingsymbol"] if p["pe"] else None); data.append({"strike": p["strike"], "ce_ltp": self.data_manager.prices.get(ce_symbol, "--") if ce_symbol else "--", "pe_ltp": self.data_manager.prices.get(pe_symbol, "--") if pe_symbol else "--"})
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
    async def add_to_watchlist(self, side, strike): pass
    async def scan_for_unusual_activity(self): pass
    async def on_trend_update(self, new_trend): self.trend_state = new_trend
    def load_instruments(self):
        try: return [i for i in kite.instruments(self.exchange) if i['name'] == self.index_name and i['instrument_type'] in ['CE', 'PE']]
        except Exception as e: print(f"FATAL: Could not load instruments: {e}"); raise e
    def get_weekly_expiry(self): today = date.today(); future_expiries = sorted([i['expiry'] for i in self.option_instruments if i.get('expiry') and i['expiry'] >= today]); return future_expiries[0] if future_expiries else None
    def get_all_option_tokens(self):
        spot = self.data_manager.prices.get(self.index_symbol);
        if not spot: return [self.index_token]
        atm_strike = self.strike_step * round(spot / self.strike_step); strikes = [atm_strike + (i - 3) * self.strike_step for i in range(7)]
        tokens = {self.index_token, *[opt['instrument_token'] for strike in strikes for side in ['CE', 'PE'] if (opt := self.get_entry_option(side, strike))], *self.uoa_watchlist.keys()}; return list(tokens)
    async def map_option_tokens(self, tokens):
        self.token_to_symbol = {o['instrument_token']: o['tradingsymbol'] for o in self.option_instruments if o['instrument_token'] in tokens}
        self.token_to_symbol[self.index_token] = self.index_symbol
    def get_strike_pairs(self, count=7):
        spot = self.data_manager.prices.get(self.index_symbol);
        if not spot: return []
        atm_strike = self.strike_step * round(spot / self.strike_step); strikes = [atm_strike + (i - count // 2) * self.strike_step for i in range(count)]
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