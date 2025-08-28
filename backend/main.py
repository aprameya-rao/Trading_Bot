# backend/main.py
import asyncio
import sqlite3
import json
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os
import signal
from datetime import datetime

from core.kite import kite, generate_session_and_set_token, access_token
from core.websocket_manager import manager
from core.strategy import Strategy, MARKET_STANDARD_PARAMS
from core.kite_ticker_manager import KiteTickerManager
from core.optimiser import OptimizerBot

# --- Global state management ---
strategy_instance: Strategy | None = None
ticker_manager_instance: KiteTickerManager | None = None
uoa_scanner_task: asyncio.Task | None = None
bot_lock = asyncio.Lock()

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code to run on startup
    print("Application startup...")
    setup_databases()
    yield
    # Code to run on shutdown
    print("Application shutdown...")
    if ticker_manager_instance:
        await ticker_manager_instance.stop()
    if uoa_scanner_task:
        uoa_scanner_task.cancel()
    if strategy_instance and strategy_instance.ui_update_task:
        strategy_instance.ui_update_task.cancel()
    print("Shutdown tasks complete.")

def setup_databases():
    """
    Creates both database files if they don't exist and clears the 'today'
    database if it's a new day.
    """
    db_paths = ['trading_data_today.db', 'trading_data_all.db']
    for db_path in db_paths:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trigger_reason TEXT NOT NULL,
                symbol TEXT,
                quantity INTEGER,
                pnl REAL,
                entry_price REAL,
                exit_price REAL,
                exit_reason TEXT,
                trend_state TEXT,
                atr REAL
            )
        ''')
        conn.commit()
        conn.close()
    
    try:
        with open("last_run_date.txt", "r") as f:
            last_run_date = f.read()
    except FileNotFoundError:
        last_run_date = ""

    today_date = datetime.now().strftime("%Y-%m-%d")
    if last_run_date != today_date:
        print(f"New day detected. Clearing today's trade log ({db_paths[0]})...")
        conn = sqlite3.connect(db_paths[0])
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades")
        conn.commit()
        conn.close()
        with open("last_run_date.txt", "w") as f:
            f.write(today_date)
        print("Today's trade log cleared.")

    print("Databases setup complete.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TokenRequest(BaseModel):
    request_token: str

class StartRequest(BaseModel):
    params: dict
    selectedIndex: str

async def uoa_scanner_worker():
    while True:
        try:
            if strategy_instance and strategy_instance.params.get('auto_scan_uoa'):
                await strategy_instance.scan_for_unusual_activity()
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            print("UOA scanner task cancelled.")
            break
        except Exception as e:
            print(f"Error in UOA scanner worker: {e}")
            await asyncio.sleep(60)

@app.get("/api/status")
async def get_status():
    if access_token:
        return {"status": "authenticated", "user": kite.profile()['user_id']}
    return {"status": "unauthenticated", "login_url": kite.login_url()}

@app.post("/api/authenticate")
async def authenticate(token_request: TokenRequest):
    success, data = generate_session_and_set_token(token_request.request_token)
    if success:
        return {"status": "success", "message": "Authentication successful.", "user": data.get('user_id')}
    raise HTTPException(status_code=400, detail=data)

@app.get("/api/trade_history")
async def get_trade_history():
    """Fetches trade history for the current day."""
    try:
        conn = sqlite3.connect('trading_data_today.db')
        df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp ASC", conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch today's trade history: {e}")

@app.get("/api/trade_history_all")
async def get_all_trade_history():
    """Fetches all trade history from the beginning of time."""
    try:
        conn = sqlite3.connect('trading_data_today.db')
        df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp ASC", conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all trade history: {e}")

@app.post("/api/optimize")
async def run_optimizer():
    optimizer = OptimizerBot()
    new_params, justifications = await optimizer.find_optimal_parameters()
    if new_params:
        optimizer.update_strategy_file(new_params)
        return {"status": "success", "report": justifications}
    else:
        return {"status": "error", "report": justifications or ["Optimization failed."]}

@app.post("/api/reset_params")
async def reset_parameters():
    try:
        with open("strategy_params.json", "w") as f:
            json.dump(MARKET_STANDARD_PARAMS, f, indent=4)
        if strategy_instance:
            strategy_instance.STRATEGY_PARAMS = MARKET_STANDARD_PARAMS.copy()
            await strategy_instance._log_debug("System", "Parameters have been reset to market defaults.")
        return {"status": "success", "message": "Parameters have been reset to market defaults."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset parameters: {e}")

@app.post("/api/start")
async def start_bot(start_request: StartRequest):
    global strategy_instance, ticker_manager_instance, uoa_scanner_task
    async with bot_lock:
        if ticker_manager_instance and ticker_manager_instance.is_connected:
            raise HTTPException(status_code=400, detail="Bot is already running.")
        
        print(f"Starting bot with params: {start_request.params}")
        main_event_loop = asyncio.get_running_loop()
        strategy_instance = Strategy(
            params=start_request.params, 
            manager=manager, 
            selected_index=start_request.selectedIndex
        )
        ticker_manager_instance = KiteTickerManager(strategy_instance, main_event_loop)
        strategy_instance.ticker_manager = ticker_manager_instance
        await strategy_instance.run()
        ticker_manager_instance.start()
        
        if not uoa_scanner_task or uoa_scanner_task.done():
            uoa_scanner_task = asyncio.create_task(uoa_scanner_worker())
            
        return {"status": "success", "message": "Bot started."}

@app.post("/api/stop")
async def stop_bot():
    global ticker_manager_instance, strategy_instance, uoa_scanner_task
    async with bot_lock:
        if not (ticker_manager_instance and ticker_manager_instance.is_connected):
            raise HTTPException(status_code=400, detail="Bot is not running.")

        print("Stopping bot...")

        # --- MODIFICATION START ---
        # Check if a trade is active and exit it before shutting down.
        if strategy_instance and strategy_instance.position:
            print("Active trade detected. Exiting position before stopping.")
            await strategy_instance.exit_position("Bot Stopped by User")
            # Give a moment for the exit to process before continuing shutdown.
            await asyncio.sleep(1)
        # --- MODIFICATION END ---
        
        await ticker_manager_instance.stop()
        
        if strategy_instance and strategy_instance.ui_update_task:
            strategy_instance.ui_update_task.cancel()
        
        if uoa_scanner_task:
            uoa_scanner_task.cancel()
        
        ticker_manager_instance = None
        strategy_instance = None
        uoa_scanner_task = None
        
        print("Bot stopped successfully.")
        return {"status": "success", "message": "Bot stopped."}

@app.post("/api/manual_exit")
async def manual_exit_trade():
    global strategy_instance
    if not strategy_instance:
        raise HTTPException(status_code=400, detail="Bot is not running.")
    if not strategy_instance.position:
        raise HTTPException(status_code=400, detail="No active trade to exit.")
    
    await strategy_instance.exit_position("Manual Exit from UI")
    return {"status": "success", "message": "Manual exit signal sent."}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "add_to_watchlist":
                if strategy_instance:
                    payload = message.get("payload", {})
                    strike = payload.get("strike")
                    side = payload.get("side")
                    if strike and side:
                        asyncio.create_task(strategy_instance.add_to_watchlist(side, strike))
                else:
                    print("Warning: Received 'add_to_watchlist' but bot is not running.")

    except WebSocketDisconnect:
        manager.disconnect()
    except Exception as e:
        print(f"Error in websocket endpoint: {e}")
        manager.disconnect()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
