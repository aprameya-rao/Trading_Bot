import asyncio
from fastapi import HTTPException
from .strategy import Strategy
from .kite_ticker_manager import KiteTickerManager
from .websocket_manager import manager

class TradingBotService:
    _instance = None

    def __init__(self):
        self.strategy_instance: Strategy | None = None
        self.ticker_manager_instance: KiteTickerManager | None = None
        self.uoa_scanner_task: asyncio.Task | None = None
        self.bot_lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def uoa_scanner_worker(self):
        while True:
            try:
                if self.strategy_instance and self.strategy_instance.params.get('auto_scan_uoa'):
                    await self.strategy_instance.scan_for_unusual_activity()
                await asyncio.sleep(300)
            except asyncio.CancelledError: break
            except Exception as e: print(f"Error in UOA scanner worker: {e}"); await asyncio.sleep(60)

    async def start_bot(self, params, selected_index):
        async with self.bot_lock:
            if self.ticker_manager_instance and self.ticker_manager_instance.is_connected:
                raise HTTPException(status_code=400, detail="Bot is already running.")
            
            try:
                main_loop = asyncio.get_running_loop()
                self.strategy_instance = Strategy(params=params, manager=manager, selected_index=selected_index)
                self.ticker_manager_instance = KiteTickerManager(self.strategy_instance, main_loop)
                self.strategy_instance.ticker_manager = self.ticker_manager_instance
                await self.strategy_instance.run()

                self.ticker_manager_instance.start()
                await asyncio.wait_for(self.ticker_manager_instance.connected_event.wait(), timeout=15)
                
                if not self.ticker_manager_instance.is_connected:
                     raise Exception("Ticker failed to connect after start attempt.")

                if not self.uoa_scanner_task or self.uoa_scanner_task.done():
                    self.uoa_scanner_task = asyncio.create_task(self.uoa_scanner_worker())

                # --- FIX: Explicitly send the status update BEFORE returning the HTTP response ---
                await self.strategy_instance._update_ui_status()
                
                print("Bot started successfully and ticker is connected.")
                return {"status": "success", "message": "Bot started and connected."}

            except asyncio.TimeoutError:
                await self._cleanup_bot_state()
                raise HTTPException(status_code=504, detail="Ticker connection timed out.")
            except Exception as e:
                await self._cleanup_bot_state()
                raise HTTPException(status_code=500, detail=str(e))

    async def stop_bot(self):
        async with self.bot_lock:
            if not (self.ticker_manager_instance and self.ticker_manager_instance.is_connected):
                raise HTTPException(status_code=400, detail="Bot is not running.")

            if self.strategy_instance and self.strategy_instance.position:
                await self.strategy_instance.exit_position("Bot Stopped by User")
                await asyncio.sleep(1)
            
            await self._cleanup_bot_state()
            print("Bot stopped successfully.")
            
            # Send final disconnected status
            await manager.broadcast({"type": "status_update", "payload": {
                "connection": "DISCONNECTED", "mode": "NOT STARTED", "is_running": False,
                "indexPrice": 0, "trend": "---", "indexName": "INDEX"
            }})

            return {"status": "success", "message": "Bot stopped."}

    async def manual_exit_trade(self):
        if not self.strategy_instance:
            raise HTTPException(status_code=400, detail="Bot is not running.")
        if not self.strategy_instance.position:
            raise HTTPException(status_code=400, detail="No active trade to exit.")
        
        await self.strategy_instance.exit_position("Manual Exit from UI")
        return {"status": "success", "message": "Manual exit signal sent."}

    async def add_to_watchlist(self, side, strike):
        if self.strategy_instance and side and strike is not None:
            await self.strategy_instance.add_to_watchlist(side, strike)

    async def _cleanup_bot_state(self):
        if self.ticker_manager_instance:
            await self.ticker_manager_instance.stop()
        if self.strategy_instance and self.strategy_instance.ui_update_task:
            self.strategy_instance.ui_update_task.cancel()
        if self.uoa_scanner_task:
            self.uoa_scanner_task.cancel()
        
        self.ticker_manager_instance = None
        self.strategy_instance = None
        self.uoa_scanner_task = None

async def get_bot_service():
    return await TradingBotService.get_instance()

