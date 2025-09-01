from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# Database file paths
TODAY_DB_PATH = "trading_data_today.db"
ALL_DB_PATH = "trading_data_all.db"

# SQLAlchemy database URLs for SQLite
DATABASE_URL_TODAY = f"sqlite:///{TODAY_DB_PATH}"
DATABASE_URL_ALL = f"sqlite:///{ALL_DB_PATH}"

# Create a shared engine for each database.
# The engine manages a QueuePool of connections by default.
# We explicitly set check_same_thread=False, which is required for SQLite
# when connections are used across different threads (as a pool does).
today_engine = create_engine(
    DATABASE_URL_TODAY,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5, # Number of connections to keep open in the pool
    max_overflow=2 # Number of extra connections allowed
)

all_engine = create_engine(
    DATABASE_URL_ALL,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=2
)

# Export the 'text' function for convenience so other modules don't have to import it
sql_text = text