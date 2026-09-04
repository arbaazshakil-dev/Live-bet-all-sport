"""
Main polling loop (v3, api-tennis.com): pulls live tennis matches (which
already include score/stats/point-by-point inline -- one call covers
everything), estimates a MODEL win probability from each player's current
ATP/WTA ranking points, pulls market odds, flags value bets and
high-confidence picks, sends push notifications, and logs everything.

Run once:         python main.py --once
Run continuously:  python main.py
(Needs to be hosted somewhere that stays running -- see README.md for the
free GitHub Actions setup.)
"""
import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone

import config
import notifier
import tennis_api_client as api


def log_prediction(row):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(config.LOG_FILE)
    with open(config.LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def save_live_stats(stats_by_event):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "matches": stats_by_event,
    }
    with open(config.LIVE_STATS_FILE, "w") as f:
        json.dump(payload, f, indent=2)


def load_standings_points():
    """Builds {player_key: points} from current ATP + WTA standings.
    Used as a simple strength estimate since this API has no prediction
    endpoint of its own."""
    points = {}
    for tour in ("ATP", "WTA"):
        try:
            rows = api.get_standings(tour)
            for row in rows:
                key = row.get("player_key")
                pts = row.get("points")
                if key and pts is not None:
                    try:
                        points[str(key)] = float(str(pts).replace(",", ""))
                    except ValueError:
                        pass
        except Exception as e:
            print(f"[main] Could not load {tour} standings: {e}")
    return points


def estimate_model_prob(p1_key, p2_key, points):
    """Simple strength-share estimate: player's share of combined ranking
    points. Returns None if either player isn't in the current top rankings
    (common for lower-tier ITF/Challenger matches -- no coverage there)."""
    p1 = points.get(str(p1_key))
    p2 = points.get(str(p2_key))
    if p1 is None or p2 is None or (p1 + p2) == 0:
        return None
    return p1 / (p1 + p2)


def _best_home_away_odds(odds_result, match_key):
    """Pulls the best (highest) decimal price for each side from the
    Home/Away market. Returns (home_price, away_price), either possibly None."""
    match_odds = odds_result.get(str(match_key)) or odds_result.get(match_key) or {}
    market = match_odds.get("Home/Away", {})
    home_prices = [float(v) for v in market.get("Home", {}).values() if _is_number(v)]
    away_prices = [float(v) for v in market.get("Away", {}).values() if _is_number(v)]
    return (max(home_prices) if home_prices else None, max(away_prices) if away_prices else None)


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _build_stats_entry(match):
    """Converts one api-tennis.com match object (already containing scores,
    statistics, pointbypoint) into the shape live_stats.json / the dashboard
    expects."""
    p1 = match.get("event_first_player")
    p2 = match.get("event_second_player")
    p1_key = str(match.get("first_player_key"))
    p2_key = str(match.get("second_player_key"))

    scores = match.get("scores") or []
    score_str = ", ".join(f"{s.get('score_first')}-{s.get('score_second')}" for s in scores) or match.get("event_final_result")

    # map api-tennis.com's statistics list (one row per player per stat)
    # into the [p1_value, p2_value] pairs the dashboard renders.
    stat_map = {"aces": None, "double_faults": None, "win_1st_serve": None, "break_point_conversions": None}
    name_lookup = {
        "aces": "aces",
        "double faults": "double_faults",
        "1st serve points won": "win_1st_serve",
        "break points won": "break_point_conversions",
    }
    pairs = {k: [None, None] for k in stat_map}
    for stat in (match.get("statistics") or []):
        key = name_lookup.get(str(stat.get("stat_name", "")).strip().lower())
        if not key:
            continue
        idx = 0 if str(stat.get("player_key")) == p1_key else (1 if str(stat.get("player_key")) == p2_key else None)
        if idx is not None:
            val = stat.get("stat_value")
            pairs[key][idx] = val

    # simple timeline from the game-by-game log, if present
    timeline = []
    for game in (match.get("pointbypoint") or [])[-15:]:
        server = game.get("player_served")
        server_name = p1 if server == "First Player" else (p2 if server == "Second Player" else server)
        timeline.append(f"{game.get('set_number')} Game {game.get('number_game')}: {server_name} served — {game.get('score')}")

    return {
        "player": p1,
        "opponent": p2,
        "score": score_str,
        "status": match.get("event_status"),
        "stats": {k: v for k, v in pairs.items() if any(x is not None for x in v)} or None,
        "timeline": timeline or None,
    }


def process_live_matches():
    try:
        live = api.get_livescore()
    except Exception as e:
        print(f"[main] Failed to fetch live matches: {e}")
        return

    if not live:
        print("[main] No live tennis matches right now.")
        save_live_stats({})
        return

    print(f"[main] {len(live)} live match(es) found.")
    points = load_standings_points()

    stats_by_event = {}

    for match in live:
        event_id = match.get("event_key")
        p1 = match.get("event_first_player")
        p2 = match.get("event_second_player")
        p1_key = match.get("first_player_key")
        p2_key = match.get("second_player_key")
        if not (event_id and p1 and p2):
            continue

        stats_by_event[str(event_id)] = _build_stats_entry(match)

        model_prob = estimate_model_prob(p1_key, p2_key, points)

        market_odds_p1 = None
        implied_p1 = None
        try:
            odds_result = api.get_odds(event_id)
            home_price, _away_price = _best_home_away_odds(odds_result, event_id)
            market_odds_p1 = home_price
            implied_p1 = (1.0 / home_price) if home_price else None
        except Exception as e:
            print(f"[main] Odds fetch failed for {p1} vs {p2}: {e}")

        edge = (model_prob - implied_p1) if (model_prob is not None and implied_p1 is not None) else None

        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "player": p1,
            "opponent": p2,
            "tour_type": match.get("event_type_type"),
            "model_prob": round(model_prob, 4) if model_prob is not None else None,
            "market_odds": market_odds_p1,
            "implied_prob": round(implied_p1, 4) if implied_p1 is not None else None,
            "edge": round(edge, 4) if edge is not None else None,
        }
        log_prediction(row)

        if edge is not None and edge >= config.EDGE_THRESHOLD:
            print(f"[VALUE BET] {p1} vs {p2}: edge={edge:.1%}")
            notifier.notify_value_bet(p1, p2, model_prob, market_odds_p1, edge, "best available")
        elif model_prob is not None and model_prob >= config.CONFIDENCE_THRESHOLD:
            print(f"[HIGH CONFIDENCE] {p1} vs {p2}: prob={model_prob:.1%}")
            notifier.notify_high_confidence(p1, p2, model_prob)

    save_live_stats(stats_by_event)


def run_once():
    print("[main] Checking live tennis matches ...")
    process_live_matches()


def run_forever():
    while True:
        run_once()
        print(f"[main] Sleeping {config.POLL_INTERVAL_SECONDS}s ...")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single pass instead of looping forever")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_forever()
