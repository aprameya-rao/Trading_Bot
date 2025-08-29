import asyncio
import sqlite3
from datetime import datetime

class TradeLogger:
    """Handles all database interactions for logging trades."""
    def __init__(self, db_lock, today_db_path="trading_data_today.db", all_db_path="trading_data_all.db"):
        self.db_lock = db_lock
        self.today_db_path = today_db_path
        self.all_db_path = all_db_path

    async def log_trade(self, trade_info):
        """Asynchronously logs a completed trade to the databases."""
        def db_call():
            columns = ", ".join(trade_info.keys())
            placeholders = ", ".join("?" * len(trade_info))
            sql = f"INSERT INTO trades ({columns}) VALUES ({placeholders})"
            values = tuple(trade_info.values())
            
            for db_path in [self.today_db_path, self.all_db_path]:
                try:
                    with sqlite3.connect(db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(sql, values)
                        conn.commit()
                except Exception as e:
                    print(f"CRITICAL DB ERROR writing to {db_path}: {e}")

        async with self.db_lock:
            await asyncio.to_thread(db_call)

    @staticmethod
    def setup_databases():
        """
        Creates both database files if they don't exist and clears the 'today'
        database if it's a new day. (Static method as it runs once on startup).
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
            with open("last_run_date.txt", "r") as f: last_run_date = f.read()
        except FileNotFoundError: last_run_date = ""

        today_date = datetime.now().strftime("%Y-%m-%d")
        if last_run_date != today_date:
            print(f"New day detected. Clearing today's trade log ({db_paths[0]})...")
            conn = sqlite3.connect(db_paths[0])
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades")
            conn.commit()
            conn.close()
            with open("last_run_date.txt", "w") as f: f.write(today_date)
            print("Today's trade log cleared.")

        print("Databases setup complete.")
