import asyncio
from datetime import datetime
# --- CHANGE: Import the engines and sql_text function ---
from .database import today_engine, all_engine, sql_text

class TradeLogger:
    """Handles all database interactions for logging trades using a connection pool."""
    def __init__(self, db_lock):
        self.db_lock = db_lock
        self.engines = [today_engine, all_engine]

    async def log_trade(self, trade_info):
        """Asynchronously logs a completed trade to the databases using the pool."""
        def db_call():
            columns = ", ".join(trade_info.keys())
            # Use named placeholders for SQLAlchemy
            placeholders = ", ".join(f":{key}" for key in trade_info.keys())
            sql = f"INSERT INTO trades ({columns}) VALUES ({placeholders})"
            
            for engine in self.engines:
                try:
                    # Get a connection from the pool and automatically commit/rollback
                    with engine.begin() as conn:
                        conn.execute(sql_text(sql), trade_info)
                except Exception as e:
                    db_name = engine.url.database
                    print(f"CRITICAL DB ERROR writing to {db_name}: {e}")

        async with self.db_lock:
            await asyncio.to_thread(db_call)

    @staticmethod
    def setup_databases():
        """
        Creates tables if they don't exist and clears the 'today'
        database if it's a new day. Uses the shared engines.
        """
        create_table_sql = sql_text('''
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
        
        # Ensure tables exist in both databases
        with today_engine.connect() as conn:
            conn.execute(create_table_sql)
        with all_engine.connect() as conn:
            conn.execute(create_table_sql)
        
        try:
            with open("last_run_date.txt", "r") as f: last_run_date = f.read()
        except FileNotFoundError: last_run_date = ""

        today_date = datetime.now().strftime("%Y-%m-%d")
        if last_run_date != today_date:
            print(f"New day detected. Clearing today's trade log...")
            with today_engine.begin() as conn: # .begin() will auto-commit
                conn.execute(sql_text("DELETE FROM trades"))
            with open("last_run_date.txt", "w") as f: f.write(today_date)
            print("Today's trade log cleared.")

        print("Databases setup complete.")