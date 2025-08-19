# backend/core/websocket_manager.py
from fastapi import WebSocket
import json
import numpy as np
import math

# --- NEW: Custom JSON encoder to handle numpy/pandas data types ---
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            # Handle NaN, Infinity, -Infinity by converting them to None (JSON null)
            if math.isnan(obj) or math.isinf(obj):
                return None
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(CustomJSONEncoder, self).default(obj)

class ConnectionManager:
    def __init__(self):
        self.active_connection: WebSocket | None = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connection = websocket
        print("Frontend client connected.")

    def disconnect(self):
        self.active_connection = None
        print("Frontend client disconnected.")

    async def broadcast(self, message: dict):
        if self.active_connection:
            try:
                # --- UPDATED: Use the custom encoder ---
                json_message = json.dumps(message, cls=CustomJSONEncoder)
                await self.active_connection.send_text(json_message)
            except Exception as e:
                print(f"Error broadcasting message: {e}")
                self.disconnect()

manager = ConnectionManager()