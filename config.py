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

# How often to poll for new matches while a run is active (seconds)
POLL_INTERVAL_SECONDS = 300  # 5 minutes

# How long a single GitHub Actions run stays active and keeps polling before
# exiting (minutes). Kept under the schedule interval in run_model.yml so
# this session finishes before the next one starts. Lower this (or raise
# POLL_INTERVAL_SECONDS) if you're burning through API quota too fast.
MAX_RUN_MINUTES = 15

# Whether to fetch head-to-head + recent form for each live match (1 extra
# API call per match). Turn off if you're running low on API quota.
ENABLE_H2H = True

# Whether to send push notifications for "value bet" (edge-based) picks.
# Default OFF: a walk-forward backtest against ~2 years of real WTA odds
# (2024-2026) showed this signal loses money overall (-11.9% ROI), and gets
# WORSE at higher edge thresholds -- meaning big disagreements with the
# market are more often the model missing context (injury, form, fatigue)
# than genuine mispricing. High-confidence picks (raw model probability)
# backtested at a legitimate 64% accuracy and are unaffected by this flag.
# Don't flip this on without re-validating -- see backtest/backtest_wta.py.
ENABLE_VALUE_BET_ALERTS = False

# --- Data paths ---
DATA_DIR = "data"
LOG_FILE = f"{DATA_DIR}/predictions_log.csv"
LIVE_STATS_FILE = f"{DATA_DIR}/live_stats.json"
ELO_RATINGS_FILE = f"{DATA_DIR}/elo_ratings.json"
