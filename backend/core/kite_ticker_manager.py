# backend/core/kite_ticker_manager.py
import asyncio
from kiteconnect import KiteTicker
from core.kite import API_KEY, access_token
from typing import TYPE_CHECKING

# This block is only processed by type checkers, not at runtime
if TYPE_CHECKING:
    from core.strategy import Strategy

class KiteTickerManager:
    # --- UPDATED: __init__ now accepts the main_loop ---
    def __init__(self, strategy_instance: "Strategy", main_loop):
        self.kws = KiteTicker(API_KEY, access_token)
        self.strategy = strategy_instance
        self.main_loop = main_loop  # <-- Store the reference to the main event loop
        self.kws.on_ticks = self.on_ticks
        self.kws.on_connect = self.on_connect
        self.kws.on_close = self.on_close
        self.kws.on_error = self.on_error
        self.is_connected = False

    def on_ticks(self, ws, ticks):
        if self.strategy:
            # --- FIXED: Use the stored main_loop reference ---
            asyncio.run_coroutine_threadsafe(self.strategy.handle_ticks_async(ticks), self.main_loop)

    def on_connect(self, ws, response):
        self.is_connected = True
        print("Kite Ticker connected.")
        if self.strategy:
             # --- FIXED: Use the stored main_loop reference ---
             asyncio.run_coroutine_threadsafe(self.strategy.on_ticker_connect(), self.main_loop)

    def on_close(self, ws, code, reason):
        self.is_connected = False
        print(f"Kite Ticker closed: {code} - {reason}")
        if self.strategy:
             # --- FIXED: Use the stored main_loop reference ---
             asyncio.run_coroutine_threadsafe(self.strategy.on_ticker_disconnect(), self.main_loop)

    def on_error(self, ws, code, reason):
        print(f"Kite Ticker error: {code} - {reason}")

    def start(self):
        if not self.is_connected and access_token:
            print("Starting Kite Ticker...")
            self.kws.connect(threaded=True)
        elif not access_token:
            print("Cannot start Kite Ticker: Access token not available.")

    def stop(self):
        if self.is_connected:
            print("Stopping Kite Ticker...")
            self.kws.close()
            
    def resubscribe(self, tokens):
        if self.is_connected:
            print(f"Resubscribing to {len(tokens)} tokens.")
            self.kws.subscribe(tokens)
            self.kws.set_mode(self.kws.MODE_LTP, tokens)