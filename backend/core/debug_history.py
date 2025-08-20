# backend/debug_history.py
import os
import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect
from datetime import datetime, timedelta

print("--- Testing Kite Historical API Access ---")

# --- Configuration ---
# 1. Manually paste the access token from your access_token.json file
ACCESS_TOKEN = "33OX7yOz2H76W4gdM1t6FeJQCjMNZJeG"

# 2. Set the token for the index you are testing
# SENSEX = 265, NIFTY 50 = 256265
INSTRUMENT_TOKEN = 265
# -------------------

load_dotenv()
API_KEY = os.getenv("API_KEY")

if not API_KEY or not ACCESS_TOKEN or "PASTE" in ACCESS_TOKEN:
    print("\nERROR: Please set API_KEY in .env and paste your ACCESS_TOKEN in this script.")
else:
    try:
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(ACCESS_TOKEN)
        print("Kite connection successful.")

        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        print(f"Fetching data for token {INSTRUMENT_TOKEN} from {from_date} to {to_date}...")

        records = kite.historical_data(INSTRUMENT_TOKEN, from_date, to_date, "minute")

        print("\n--- API Response ---")
        if records:
            print(f"SUCCESS: Received {len(records)} candles.")
            df = pd.DataFrame(records)
            print("Last 5 records received:")
            print(df.tail())
        else:
            print("FAILURE: The API call succeeded but returned an empty list. No data is available for this instrument/period for your account.")

    except Exception as e:
        print("\n--- API Call FAILED ---")
        print(f"An error occurred: {e}")
        print("\nThis likely means your API subscription does not grant access to historical data.")