"""
Configuration for the sports betting model.
Fill in your API keys below (or set as environment variables of the same name).
"""
import os

# --- Tennis API (RapidAPI / matchstat.com) ---
# Subscribe (free tier available) at https://rapidapi.com/jjrm365-kIFr3Nx_odV/api/tennis-api-atp-wta-itf
# Docs: https://tennisapidoc.matchstat.com/
# Provides live events, predictions, pre-match & live odds, and arbitrage detection
# all from one source -- replaces the separate historical-Elo + odds-API approach.
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "YOUR_RAPIDAPI_KEY_HERE")

# --- Notifications (ntfy.sh) ---
# ntfy is free, no signup: pick any unique topic name, install the ntfy app,
# subscribe to that topic name in the app, done.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "your-unique-topic-name-here")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- Model thresholds ---
# Minimum edge (model probability - implied market probability) to trigger a "value bet" ping
EDGE_THRESHOLD = 0.05  # 5 percentage points

# Minimum model win probability to trigger a "high-confidence pick" ping
CONFIDENCE_THRESHOLD = 0.75  # 75%

# How often to poll for new odds (seconds)
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# --- Sports to track (Odds API sport keys) ---
# Full list: https://the-odds-api.com/sports-odds-data/sports-apis.html
SPORT_KEYS = [
    "tennis_atp",
    "tennis_wta",
    # add more once tennis pilot is validated, e.g.:
    # "basketball_nba", "americanfootball_nfl", "soccer_epl", "icehockey_nhl"
]

# --- Data paths ---
DATA_DIR = "data"
HISTORICAL_DIR = f"{DATA_DIR}/historical"
RATINGS_FILE = f"{DATA_DIR}/elo_ratings.json"
LOG_FILE = f"{DATA_DIR}/predictions_log.csv"
LIVE_STATS_FILE = f"{DATA_DIR}/live_stats.json"
