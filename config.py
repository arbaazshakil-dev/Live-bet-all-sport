"""
Configuration for the sports betting model.
Fill in your API keys below (or set as environment variables of the same name).
"""
import os

# --- Tennis API (api-tennis.com) ---
# Register / get your key at https://api-tennis.com/register
# Docs: https://api-tennis.com/documentation
# Provides live scores (with inline stats/point-by-point), odds, live odds,
# standings, H2H, and fixtures. No prediction endpoint -- our own MODEL
# probability is estimated from current ATP/WTA ranking points (see main.py).
APITENNIS_KEY = os.environ.get("APITENNIS_KEY", "YOUR_APITENNIS_KEY_HERE").strip()

# --- Notifications (ntfy.sh) ---
# ntfy is free, no signup: pick any unique topic name, install the ntfy app,
# subscribe to that topic name in the app, done.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "your-unique-topic-name-here").strip()
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- Model thresholds ---
# Minimum edge (model probability - implied market probability) to trigger a "value bet" ping
EDGE_THRESHOLD = 0.05  # 5 percentage points

# Minimum model win probability to trigger a "high-confidence pick" ping
CONFIDENCE_THRESHOLD = 0.75  # 75%

# How often to poll for new odds (seconds) -- only used by main.py's --loop mode;
# the GitHub Actions schedule (run_model.yml) controls the real cadence.
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# --- Data paths ---
DATA_DIR = "data"
LOG_FILE = f"{DATA_DIR}/predictions_log.csv"
LIVE_STATS_FILE = f"{DATA_DIR}/live_stats.json"
