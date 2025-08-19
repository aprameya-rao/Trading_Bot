# backend/main.py
import asyncio
import sqlite3
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os

from core.kite import kite, generate_session_and_set_token, access_token
from core.websocket_manager import manager
from core.strategy import Strategy
from core.kite_ticker_manager import KiteTickerManager
from core.optimiser import OptimizerBot # <-- NEW IMPORT

# --- NEW: Database Setup on Startup ---
def setup_database(db_path='trading_data.db'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trigger_reason TEXT NOT NULL,
            symbol TEXT,
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
    print("Database setup complete.")

setup_database()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- UPDATED: Global state management ---
strategy_instance: Strategy | None = None
ticker_manager_instance: KiteTickerManager | None = None
uoa_scanner_task: asyncio.Task | None = None

class TokenRequest(BaseModel):
    request_token: str

class StartRequest(BaseModel):
    params: dict
    selectedIndex: str

# --- NEW: Background Task for UOA Scanner ---
async def uoa_scanner_worker():
    while True:
        try:
            if strategy_instance and strategy_instance.params.get('auto_scan_uoa'):
                await strategy_instance.scan_for_unusual_activity()
            # Scan every 5 minutes (300 seconds)
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            print("UOA scanner task cancelled.")
            break
        except Exception as e:
            print(f"Error in UOA scanner worker: {e}")
            await asyncio.sleep(60) # Wait a minute before retrying on error

@app.on_event("shutdown")
def shutdown_event():
    global ticker_manager_instance
    if ticker_manager_instance:
        ticker_manager_instance.stop()
    if uoa_scanner_task:
        uoa_scanner_task.cancel()
    print("Application shutdown.")

@app.get("/api/status")
async def get_status():
    if access_token:
        return {"status": "authenticated", "user": kite.profile()['user_id']}
    return {"status": "unauthenticated", "login_url": kite.login_url()}

@app.post("/api/authenticate")
async def authenticate(token_request: TokenRequest):
    success, message = generate_session_and_set_token(token_request.request_token)
    if success:
        return {"status": "success", "message": "Authentication successful."}
    raise HTTPException(status_code=400, detail=message)

# --- NEW: Endpoint for Optimizer ---
@app.post("/api/optimize")
async def run_optimizer():
    optimizer = OptimizerBot()
    new_params, justifications = await optimizer.find_optimal_parameters()
    if new_params:
        optimizer.update_strategy_file(new_params)
        return {"status": "success", "report": justifications}
    else:
        return {"status": "error", "report": justifications or ["Optimization failed."]}

@app.post("/api/start")
async def start_bot(start_request: StartRequest):
    global strategy_instance, ticker_manager_instance, uoa_scanner_task
    if ticker_manager_instance and ticker_manager_instance.is_connected:
        raise HTTPException(status_code=400, detail="Bot is already running.")

    print(f"Starting bot with params: {start_request.params}")
    
    strategy_instance = Strategy(
        params=start_request.params, 
        manager=manager, 
        selected_index=start_request.selectedIndex
    )
    
    ticker_manager_instance = KiteTickerManager(strategy_instance)
    strategy_instance.ticker_manager = ticker_manager_instance
    
    await strategy_instance.run()
    ticker_manager_instance.start()

    if not uoa_scanner_task or uoa_scanner_task.done():
        uoa_scanner_task = asyncio.create_task(uoa_scanner_worker())
    
    return {"status": "success", "message": "Bot started."}

@app.post("/api/stop")
async def stop_bot():
    global ticker_manager_instance, strategy_instance, uoa_scanner_task
    if ticker_manager_instance and ticker_manager_instance.is_connected:
        ticker_manager_instance.stop()
        ticker_manager_instance = None
        strategy_instance = None
        if uoa_scanner_task:
            uoa_scanner_task.cancel()
            uoa_scanner_task = None
        return {"status": "success", "message": "Bot stopped."}
    raise HTTPException(status_code=400, detail="Bot is not running.")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)