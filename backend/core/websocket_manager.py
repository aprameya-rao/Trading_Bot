# backend/core/websocket_manager.py
from fastapi import WebSocket
import json
import numpy as np
import math
from typing import List # Import List

# --- Custom JSON encoder remains the same ---
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(CustomJSONEncoder, self).default(obj)

class ConnectionManager:
    def __init__(self):
        # CHANGED: Use a list to store multiple connections
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # CHANGED: Add the new connection to the list
        self.active_connections.append(websocket)
        print(f"Frontend client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        # CHANGED: Remove a specific connection from the list
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"Frontend client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if self.active_connections:
            json_message = json.dumps(message, cls=CustomJSONEncoder)
            
            # Create a copy of the list to iterate over, in case we need to modify it
            for connection in self.active_connections[:]:
                try:
                    await connection.send_text(json_message)
                except Exception:
                    # If sending fails, the client has likely disconnected. Remove them.
                    self.disconnect(connection)

    async def close(self):
        """Forcefully closes all active WebSocket connections."""
        for connection in self.active_connections[:]:
            await connection.close()
            self.disconnect(connection)
        print("All WebSocket connections closed by server.")

manager = ConnectionManager()