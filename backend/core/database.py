import os
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# --- THIS IS THE FIX: Use the parent directory of 'core' ---
# Get the directory where this script ('database.py') is located, which is the 'core' folder
CORE_DIR = os.path.dirname(os.path.abspath(__file__))

# Get the parent directory of 'core', which is the 'backend' root folder
BASE_DIR = os.path.dirname(CORE_DIR)

# Define the database file names
TODAY_DB_NAME = "trading_data_today.db"
ALL_DB_NAME = "trading_data_all.db"

# Create the full, absolute paths to the database files
# os.path.join will now place them in the 'backend' root directory
TODAY_DB_PATH = os.path.join(BASE_DIR, TODAY_DB_NAME)
ALL_DB_PATH = os.path.join(BASE_DIR, ALL_DB_NAME)

# SQLAlchemy database URLs for SQLite using the absolute paths
DATABASE_URL_TODAY = f"sqlite:///{TODAY_DB_PATH}"
DATABASE_URL_ALL = f"sqlite:///{ALL_DB_PATH}"

# Create a shared engine for each database.
today_engine = create_engine(
    DATABASE_URL_TODAY,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=2
)

all_engine = create_engine(
    DATABASE_URL_ALL,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=2
)

# Export the 'text' function for convenience
sql_text = text

class Database:
    """Database wrapper class for trading bot database operations"""
    
    def __init__(self):
        self.today_engine = today_engine
        self.all_engine = all_engine
        self.sql_text = sql_text
    
    def get_today_engine(self):
        """Get today's database engine"""
        return self.today_engine
    
    def get_all_engine(self):
        """Get all data database engine"""
        return self.all_engine
    
    def execute_query(self, query, engine_type="today", **params):
        """Execute a query on specified database"""
        engine = self.today_engine if engine_type == "today" else self.all_engine
        with engine.connect() as connection:
            return connection.execute(self.sql_text(query), params)
    
    def create_tables_if_not_exists(self):
        """V47.14 Enhanced: Create enhanced tables with all V47.14 features"""
        # Today's database tables - Enhanced for V47.14
        with self.today_engine.connect() as conn:
            # Enhanced trades table with V47.14 features
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    action TEXT,
                    quantity INTEGER,
                    price REAL,
                    strategy TEXT,
                    pnl REAL DEFAULT 0,
                    -- V47.14 Enhanced Fields
                    trigger_type TEXT,
                    signal_strength REAL DEFAULT 1.0,
                    volatility_factor REAL DEFAULT 1.0,
                    atr_value REAL,
                    stop_loss_price REAL,
                    stop_loss_type TEXT,
                    trailing_sl_updates INTEGER DEFAULT 0,
                    execution_time_ms INTEGER,
                    order_type TEXT,
                    fill_type TEXT,
                    avg_fill_price REAL,
                    market_conditions TEXT,
                    risk_metrics TEXT,
                    exit_reason TEXT,
                    holding_time_minutes INTEGER,
                    max_profit REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0
                )
            """))
            
            # V47.14 Enhanced: Volatility breakout signals table
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS volatility_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    atr_value REAL,
                    atr_squeeze_detected BOOLEAN DEFAULT 0,
                    squeeze_range_high REAL,
                    squeeze_range_low REAL,
                    breakout_side TEXT,
                    breakout_price REAL,
                    signal_taken BOOLEAN DEFAULT 0,
                    trade_id INTEGER,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """))
            
            # V47.14 Enhanced: Enhanced crossover tracking
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS crossover_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    signal_type TEXT,
                    side TEXT,
                    signal_strength REAL,
                    momentum_score REAL,
                    tracking_window_minutes INTEGER DEFAULT 5,
                    signals_in_window INTEGER,
                    signal_taken BOOLEAN DEFAULT 0,
                    trade_id INTEGER,
                    expiry_time DATETIME,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """))
            
            # V47.14 Enhanced: Persistent trend tracking
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS trend_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    trend_state TEXT,
                    trend_duration_minutes INTEGER,
                    continuation_signals INTEGER,
                    trend_strength REAL,
                    signal_taken BOOLEAN DEFAULT 0,
                    trade_id INTEGER,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """))
            
            # V47.14 Enhanced: Risk management tracking
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT,
                    description TEXT,
                    daily_pnl REAL,
                    consecutive_losses INTEGER,
                    risk_reduction_factor REAL,
                    position_size_adjustment REAL,
                    trade_id INTEGER,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """))
            
            conn.commit()
        
        # All data database tables - Enhanced for V47.14
        with self.all_engine.connect() as conn:
            # Enhanced historical trades with V47.14 features
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS historical_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT,
                    action TEXT,
                    quantity INTEGER,
                    price REAL,
                    strategy TEXT,
                    pnl REAL DEFAULT 0,
                    date TEXT,
                    -- V47.14 Enhanced Historical Fields
                    trigger_type TEXT,
                    signal_strength REAL DEFAULT 1.0,
                    volatility_factor REAL DEFAULT 1.0,
                    atr_value REAL,
                    stop_loss_price REAL,
                    stop_loss_type TEXT,
                    execution_time_ms INTEGER,
                    order_type TEXT,
                    fill_type TEXT,
                    avg_fill_price REAL,
                    market_conditions TEXT,
                    risk_metrics TEXT,
                    exit_reason TEXT,
                    holding_time_minutes INTEGER,
                    max_profit REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0
                )
            """))
            
            # V47.14 Enhanced: Daily performance summary
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS daily_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    max_daily_drawdown REAL DEFAULT 0,
                    volatility_breakout_trades INTEGER DEFAULT 0,
                    crossover_trades INTEGER DEFAULT 0,
                    trend_continuation_trades INTEGER DEFAULT 0,
                    avg_execution_time_ms REAL DEFAULT 0,
                    risk_events INTEGER DEFAULT 0,
                    max_consecutive_losses INTEGER DEFAULT 0
                )
            """))
            
            # V47.14 Enhanced: Strategy performance analytics
            conn.execute(self.sql_text("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    strategy_type TEXT,
                    trigger_type TEXT,
                    total_signals INTEGER DEFAULT 0,
                    signals_taken INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0,
                    avg_pnl REAL DEFAULT 0,
                    avg_execution_time_ms REAL DEFAULT 0,
                    avg_holding_time_minutes REAL DEFAULT 0,
                    UNIQUE(date, strategy_type, trigger_type)
                )
            """))
            
            conn.commit()

    # =================================================================
    # V47.14 ENHANCED DATABASE METHODS
    # =================================================================
    
    def log_enhanced_trade(self, symbol, action, quantity, price, strategy, trigger_type="",
                          signal_strength=1.0, volatility_factor=1.0, atr_value=None,
                          stop_loss_price=None, stop_loss_type="", execution_time_ms=None,
                          order_type="", fill_type="", avg_fill_price=None, 
                          market_conditions="", risk_metrics=""):
        """V47.14 Enhanced: Log trade with enhanced V47.14 features"""
        with self.today_engine.connect() as conn:
            conn.execute(self.sql_text("""
                INSERT INTO trades (
                    symbol, action, quantity, price, strategy, trigger_type,
                    signal_strength, volatility_factor, atr_value, stop_loss_price,
                    stop_loss_type, execution_time_ms, order_type, fill_type,
                    avg_fill_price, market_conditions, risk_metrics
                ) VALUES (
                    :symbol, :action, :quantity, :price, :strategy, :trigger_type,
                    :signal_strength, :volatility_factor, :atr_value, :stop_loss_price,
                    :stop_loss_type, :execution_time_ms, :order_type, :fill_type,
                    :avg_fill_price, :market_conditions, :risk_metrics
                )
            """), {
                'symbol': symbol, 'action': action, 'quantity': quantity, 'price': price,
                'strategy': strategy, 'trigger_type': trigger_type,
                'signal_strength': signal_strength, 'volatility_factor': volatility_factor,
                'atr_value': atr_value, 'stop_loss_price': stop_loss_price,
                'stop_loss_type': stop_loss_type, 'execution_time_ms': execution_time_ms,
                'order_type': order_type, 'fill_type': fill_type,
                'avg_fill_price': avg_fill_price or price, 'market_conditions': market_conditions,
                'risk_metrics': risk_metrics
            })
            conn.commit()
            # Get the inserted trade ID
            result = conn.execute(self.sql_text("SELECT last_insert_rowid()"))
            return result.fetchone()[0]
    
    def log_volatility_signal(self, symbol, atr_value, atr_squeeze_detected=False,
                             squeeze_range_high=None, squeeze_range_low=None,
                             breakout_side="", breakout_price=None, signal_taken=False, trade_id=None):
        """V47.14 Enhanced: Log volatility breakout signals"""
        with self.today_engine.connect() as conn:
            conn.execute(self.sql_text("""
                INSERT INTO volatility_signals (
                    symbol, atr_value, atr_squeeze_detected, squeeze_range_high,
                    squeeze_range_low, breakout_side, breakout_price, signal_taken, trade_id
                ) VALUES (
                    :symbol, :atr_value, :atr_squeeze_detected, :squeeze_range_high,
                    :squeeze_range_low, :breakout_side, :breakout_price, :signal_taken, :trade_id
                )
            """), {
                'symbol': symbol, 'atr_value': atr_value, 'atr_squeeze_detected': atr_squeeze_detected,
                'squeeze_range_high': squeeze_range_high, 'squeeze_range_low': squeeze_range_low,
                'breakout_side': breakout_side, 'breakout_price': breakout_price,
                'signal_taken': signal_taken, 'trade_id': trade_id
            })
            conn.commit()
    
    def update_trade_exit(self, trade_id, pnl, exit_reason="", holding_time_minutes=0,
                         max_profit=0.0, max_drawdown=0.0, trailing_sl_updates=0):
        """V47.14 Enhanced: Update trade with exit information"""
        with self.today_engine.connect() as conn:
            conn.execute(self.sql_text("""
                UPDATE trades SET 
                    pnl = :pnl,
                    exit_reason = :exit_reason,
                    holding_time_minutes = :holding_time_minutes,
                    max_profit = :max_profit,
                    max_drawdown = :max_drawdown,
                    trailing_sl_updates = :trailing_sl_updates
                WHERE id = :trade_id
            """), {
                'trade_id': trade_id, 'pnl': pnl, 'exit_reason': exit_reason,
                'holding_time_minutes': holding_time_minutes, 'max_profit': max_profit,
                'max_drawdown': max_drawdown, 'trailing_sl_updates': trailing_sl_updates
            })
            conn.commit()
    
    def get_todays_enhanced_summary(self):
        """V47.14 Enhanced: Get today's enhanced performance summary"""
        with self.today_engine.connect() as conn:
            result = conn.execute(self.sql_text("""
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN pnl > 0 THEN 1 END) as winning_trades,
                    COUNT(CASE WHEN pnl < 0 THEN 1 END) as losing_trades,
                    COALESCE(SUM(pnl), 0) as total_pnl,
                    COALESCE(MIN(pnl), 0) as max_loss,
                    COALESCE(MAX(pnl), 0) as max_profit,
                    COALESCE(AVG(execution_time_ms), 0) as avg_execution_time,
                    COUNT(CASE WHEN trigger_type LIKE '%Volatility%' THEN 1 END) as volatility_trades,
                    COUNT(CASE WHEN trigger_type LIKE '%Crossover%' THEN 1 END) as crossover_trades,
                    COUNT(CASE WHEN trigger_type LIKE '%Trend%' THEN 1 END) as trend_trades,
                    COALESCE(AVG(volatility_factor), 1.0) as avg_volatility_factor,
                    COALESCE(AVG(signal_strength), 1.0) as avg_signal_strength
                FROM trades
            """))
            return result.fetchone()