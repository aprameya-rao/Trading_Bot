import asyncio
import json
import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from datetime import datetime
import os

from core.kite import kite, generate_session_and_set_token, access_token
from core.websocket_manager import manager
from core.strategy import MARKET_STANDARD_PARAMS
from core.optimiser import OptimizerBot
from core.trade_logger import TradeLogger
from core.bot_service import TradingBotService, get_bot_service
from core.database import today_engine, all_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    TradeLogger.setup_databases()

    # --- ADDED: Open Position Reconciliation Logic ---
    # Small delay to ensure WebSocket manager is ready for potential connections
    await asyncio.sleep(2)
    if access_token:
        try:
            print("Reconciling open positions...")
            positions = await asyncio.to_thread(kite.positions)
            net_positions = positions.get('net', [])
            open_mis_positions = [
                p['tradingsymbol'] for p in net_positions 
                if p.get('product') == 'MIS' and p.get('quantity') != 0
            ]
            if open_mis_positions:
                warning_message = f"Found open MIS positions at broker: {', '.join(open_mis_positions)}. Manual action may be required."
                print(f"WARNING: {warning_message}")
                # Broadcast a warning to any connected frontend
                await manager.broadcast({
                    "type": "system_warning", 
                    "payload": {
                        "title": "Open Positions Detected on Startup",
                        "message": warning_message
                    }
                })
        except Exception as e:
            print(f"Could not reconcile open positions: {e}")
    # --- END OF ADDED LOGIC ---

    yield
    print("Application shutdown...")
    service = await get_bot_service()
    if service.ticker_manager_instance:
        await service.stop_bot()
    print("Shutdown tasks complete.")

app = FastAPI(lifespan=lifespan)



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # This is the key change
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TokenRequest(BaseModel): request_token: str
class StartRequest(BaseModel): params: dict; selectedIndex: str
class WatchlistRequest(BaseModel): side: str; strike: int

@app.get("/api/status")
async def get_status():
    # Check if the global access_token variable exists first
    if access_token:
        try:
            # Actively VERIFY the token by making a network API call.
            profile = await asyncio.to_thread(kite.profile)
            # If the call succeeds, we are truly authenticated.
            return {"status": "authenticated", "user": profile.get('user_id')}
        except Exception:
            # If kite.profile() fails, it means the token is invalid.
            # We catch the error and fall through to the unauthenticated response.
            pass
    
    # This is the fallback for BOTH "no token" and "invalid token" cases.
    return {"status": "unauthenticated", "login_url": kite.login_url()}

@app.post("/api/authenticate")
async def authenticate(token_request: TokenRequest):
    success, data = generate_session_and_set_token(token_request.request_token)
    if success:
        return {"status": "success", "message": "Authentication successful.", "user": data.get('user_id')}
    raise HTTPException(status_code=400, detail=data)

@app.get("/api/trade_history")
async def get_trade_history():
    def db_call():
        try:
            with today_engine.connect() as conn:
                df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp ASC", conn)
                return df.to_dict('records')
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch today's trade history: {e}")
    return await asyncio.to_thread(db_call)

@app.get("/api/trade_history_all")
async def get_all_trade_history():
    def db_call():
        try:
            with all_engine.connect() as conn:
                df = pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp ASC", conn)
                return df.to_dict('records')
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch all trade history: {e}")
    return await asyncio.to_thread(db_call)

@app.post("/api/optimize")
async def run_optimizer(service: TradingBotService = Depends(get_bot_service)):
    optimizer = OptimizerBot()
    new_params, justifications = await optimizer.find_optimal_parameters()
    if new_params:
        optimizer.update_strategy_file(new_params)
        if service.strategy_instance:
            await service.strategy_instance.reload_params()
            await service.strategy_instance._log_debug("Optimizer", "Live parameter reload successful.")
        return {"status": "success", "report": justifications}
    return {"status": "error", "report": justifications or ["Optimization failed."]}

@app.post("/api/reset_uoa_watchlist")
async def reset_uoa(service: TradingBotService = Depends(get_bot_service)):
    if not service.strategy_instance:
        raise HTTPException(status_code=400, detail="Bot is not running.")
    
    await service.strategy_instance.reset_uoa_watchlist()
    return {"status": "success", "message": "UOA Watchlist has been cleared."}

# --- THIS IS THE CORRECTED FUNCTION ---
@app.post("/api/reset_params")
async def reset_parameters(service: TradingBotService = Depends(get_bot_service)):
    try:
        # Step 1: Overwrite the JSON file with the market standard defaults.
        with open("strategy_params.json", "w") as f:
            json.dump(MARKET_STANDARD_PARAMS, f, indent=4)
        
        # Step 2: If the bot is running, tell it to reload its parameters from the file.
        if service.strategy_instance:
            await service.strategy_instance.reload_params()
            await service.strategy_instance._log_debug("System", "Parameters have been reset to market defaults.")
            
        return {"status": "success", "message": "Parameters reset.", "params": MARKET_STANDARD_PARAMS}
    except Exception as e:
        # The str(e) is included for better debugging if something else goes wrong.
        raise HTTPException(status_code=500, detail=f"Failed to reset parameters: {str(e)}")

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
    print("Client connected. Synchronizing state...")
    try:
        if service.strategy_instance:
            await service.strategy_instance._update_ui_status()
            await service.strategy_instance._update_ui_performance()
            await service.strategy_instance._update_ui_trade_status()
            print("State synchronization complete.")
        else:
             await manager.broadcast({"type": "status_update", "payload": {
                "connection": "DISCONNECTED", "mode": "NOT STARTED", "is_running": False,
                "indexPrice": 0, "trend": "---", "indexName": "INDEX"
            }})

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_text('{"type": "pong"}')
                continue
            
            if message.get("type") == "add_to_watchlist":
                payload = message.get("payload", {})
                if service.strategy_instance:
                    await service.strategy_instance.add_to_watchlist(payload.get("side"), payload.get("strike"))
    
    except WebSocketDisconnect:
        manager.disconnect()
    except Exception as e:
        print(f"Error in websocket endpoint: {e}")
        manager.disconnect()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
