# backend/core/websocket_manager.py
from fastapi import WebSocket
import json

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
                await self.active_connection.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error broadcasting message: {e}")
                self.disconnect()

manager = ConnectionManager()