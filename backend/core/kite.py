import os
import json
from datetime import datetime
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

kite = KiteConnect(api_key=API_KEY)
access_token = None

DEV_MODE_ENABLED = False
DEV_ACCESS_TOKEN = "PASTE_YOUR_VALID_ACCESS_TOKEN_HERE" 

def save_access_token(token):
    if DEV_MODE_ENABLED: return
    with open("access_token.json", "w") as f:
        json.dump({"access_token": token, "date": datetime.now().strftime("%Y-%m-%d")}, f)

def load_access_token():
    try:
        with open("access_token.json", "r") as f:
            data = json.load(f)
            if data["date"] == datetime.now().strftime("%Y-%m-%d"): return data["access_token"]
    except Exception: return None
    return None

def set_access_token(token):
    global access_token
    if not token: 
        access_token = None
        return False, "Token is null or empty."
    try:
        kite.set_access_token(token)
        profile = kite.profile()
        access_token = token
        print(f"Kite connection verified for user: {profile['user_id']}")
        return True, profile
    except Exception as e:
        error_message = f"Error setting access token: {e}"
        print(error_message)
        access_token = None
        return False, str(e)

def generate_session_and_set_token(request_token):
    try:
        session = kite.generate_session(request_token, api_secret=API_SECRET)
        token = session["access_token"]
        save_access_token(token)
        return set_access_token(token)
    except Exception as e:
        error_message = f"Authentication failed: {e}"
        print(error_message)
        # --- FIX: Added the missing return statement here ---
        return False, str(e)

# --- Startup Check ---
if DEV_MODE_ENABLED and DEV_ACCESS_TOKEN != "PASTE_YOUR_VALID_ACCESS_TOKEN_HERE":
    print("--- DEVELOPMENT MODE ENABLED: Using hardcoded access token. ---")
    set_access_token(DEV_ACCESS_TOKEN)
else:
    print("--- PRODUCTION MODE: Attempting to load token from file. ---")
    saved_token = load_access_token()
    if saved_token:
        set_access_token(saved_token)