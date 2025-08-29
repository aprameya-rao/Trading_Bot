import asyncio
import json
import pandas as pd
import sqlite3 # <-- FIX: Added missing import
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from datetime import datetime

from core.kite import kite, generate_session_and_set_token, access_token
from core.websocket_manager import manager
from core.strategy import MARKET_STANDARD_PARAMS
from core.optimiser import OptimizerBot
from core.trade_logger import TradeLogger
from core.bot_service import TradingBotService, get_bot_service

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    TradeLogger.setup_databases()
    yield
    print("Application shutdown...")
    service = await get_bot_service()
    if service.ticker_manager_instance:
        await service.stop_bot()
    print("Shutdown tasks complete.")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models for API Requests ---
class TokenRequest(BaseModel): request_token: str
class StartRequest(BaseModel): params: dict; selectedIndex: str
class WatchlistRequest(BaseModel): side: str; strike: int

# --- API Endpoints ---
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
    try:
        # --- FIX: Establish a proper DB connection before querying ---
        conn = sqlite3.connect('trading_data_today.db')
        df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp ASC", conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch today's trade history: {e}")

@app.get("/api/trade_history_all")
async def get_all_trade_history():
    try:
        # --- FIX: Establish a proper DB connection before querying ---
        conn = sqlite3.connect('trading_data_all.db')
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
    return {"status": "error", "report": justifications or ["Optimization failed."]}

@app.post("/api/reset_params")
async def reset_parameters(service: TradingBotService = Depends(get_bot_service)):
    try:
        with open("strategy_params.json", "w") as f:
            json.dump(MARKET_STANDARD_PARAMS, f, indent=4)
        if service.strategy_instance:
            service.strategy_instance.STRATEGY_PARAMS = MARKET_STANDARD_PARAMS.copy()
            await service.strategy_instance._log_debug("System", "Parameters have been reset to market defaults.")
        return {"status": "success", "message": "Parameters reset.", "params": MARKET_STANDARD_PARAMS}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset parameters: {e}")

@app.post("/api/start")
async def start_bot(req: StartRequest, service: TradingBotService = Depends(get_bot_service)):
    return await service.start_bot(req.params, req.selectedIndex)

@app.post("/api/stop")
async def stop_bot(service: TradingBotService = Depends(get_bot_service)):
    return await service.stop_bot()

@app.post("/api/manual_exit")
async def manual_exit_trade(service: TradingBotService = Depends(get_bot_service)):
    return await service.manual_exit_trade()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, service: TradingBotService = Depends(get_bot_service)):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "add_to_watchlist":
                payload = message.get("payload", {})
                await service.add_to_watchlist(payload.get("side"), payload.get("strike"))
    except WebSocketDisconnect:
        manager.disconnect()
    except Exception as e:
        print(f"Error in websocket endpoint: {e}")
        manager.disconnect()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

