"""
Main polling loop (v2): pulls live tennis events, gets the API's own
match prediction and odds for each, flags value bets / high-confidence
picks / arbitrage opportunities, sends push notifications, and logs
everything for later performance tracking.

Run once:         python main.py --once
Run continuously:  python main.py
(Needs to be hosted somewhere that stays running -- see README.md, section 7,
for the free GitHub Actions setup.)
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


def _extract_best_h2h_odds(pre_match_odds):
    """
    Pulls the best (highest) decimal odds per outcome out of the
    pre-match odds response. Structure varies by market/bookmaker,
    so this defensively walks the response.
    Returns a dict of {outcome_name_or_index: best_price}.
    """
    best = {}
    try:
        markets = pre_match_odds.get("result", {}).get("markets", []) or pre_match_odds.get("markets", [])
        for market in markets:
            if str(market.get("name", "")).lower() not in ("match winner", "h2h", "moneyline"):
                continue
            for outcome in market.get("outcomes", []):
                idx = outcome.get("outcome", outcome.get("name"))
                price = float(outcome.get("odds", outcome.get("price", 0)) or 0)
                if price <= 1.0:
                    continue
                if idx not in best or price > best[idx]:
                    best[idx] = price
    except Exception as e:
        print(f"[main] Could not parse odds response: {e}")
    return best


def _find_events_list(payload):
    """
    The live-events response shape isn't documented precisely, so this
    tries every common wrapper pattern: a bare list, {"result": [...]},
    {"result": {"events": [...]}}, {"data": [...]}, {"events": [...]}, etc.
    Returns the list of events found, or None if nothing matched.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None

    # direct known keys that might hold the list
    for key in ("result", "results", "data", "events", "matches", "live"):
        val = payload.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for inner_key in ("events", "data", "matches", "live", "results"):
                inner_val = val.get(inner_key)
                if isinstance(inner_val, list):
                    return inner_val
    return None


def _fetch_match_stats(event_id, p1, p2, score_hint, status_hint):
    """
    Pulls score, per-player stats, and the match timeline for one live
    match. Tries the live-score endpoint first (keyed by event id, fast);
    falls back to the player+date lookup for richer stats/timeline if
    that fails. Returns a dict for live_stats.json, or None on failure.
    """
    entry = {
        "player": p1,
        "opponent": p2,
        "score": score_hint,
        "status": status_hint,
        "stats": None,
        "timeline": None,
    }

    try:
        details = api.get_event_details(p1, p2, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        result = details.get("result", details) if isinstance(details, dict) else {}
        if isinstance(result, dict):
            entry["score"] = result.get("score", entry["score"])
            entry["status"] = result.get("status", entry["status"])
            entry["stats"] = result.get("stats")
            timeline = result.get("timeline")
            if isinstance(timeline, list):
                entry["timeline"] = [t.get("text") for t in timeline if isinstance(t, dict) and t.get("text")]
        return entry
    except Exception as e:
        print(f"[main] Stats fetch failed for {p1} vs {p2}: {e}")
        # still return the score/status we already had from the live-events list
        return entry


def save_live_stats(stats_by_event):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "matches": stats_by_event,
    }
    with open(config.LIVE_STATS_FILE, "w") as f:
        json.dump(payload, f, indent=2)


def process_live_events():
    try:
        live = api.get_live_events()
    except Exception as e:
        print(f"[main] Failed to fetch live events: {e}")
        return

    events = _find_events_list(live)
    if events is None:
        # Print the raw shape so the next run's logs tell us exactly
        # what to match against, instead of guessing again.
        print("[main] Unexpected live events response shape, skipping this pass.")
        print(f"[main] Raw response (truncated): {str(live)[:1500]}")
        return

    if not events:
        print("[main] No live tennis events right now.")
        save_live_stats({})
        return

    stats_by_event = {}

    for event in events:
        event_id = event.get("matchId") or event.get("id")
        p1 = event.get("participant1")
        p2 = event.get("participant2")
        tour_type = str(event.get("tourType", "atp")).lower()
        if not (event_id and p1 and p2):
            continue

        # 0. Score/stats/timeline for the live match tab
        stats_entry = _fetch_match_stats(event_id, p1, p2, event.get("score"), event.get("status"))
        if stats_entry:
            stats_by_event[event_id] = stats_entry

        # 1. Get the API's own prediction
        try:
            pred = api.get_match_prediction(tour_type, p1, p2)
            prob = pred.get("result", {}).get("probability") or pred.get("probability")
            model_prob = float(prob) / 100.0 if prob and float(prob) > 1 else (float(prob) if prob else None)
        except Exception as e:
            print(f"[main] No prediction for {p1} vs {p2}: {e}")
            model_prob = None

        # 2. Check for arbitrage first -- a guaranteed edge regardless of model confidence
        try:
            arb = api.get_arbitrage_odds(event_id)
            arb_result = arb.get("result", {})
            if arb_result.get("arbitrage"):
                print(f"[ARBITRAGE] {p1} vs {p2}: {arb_result.get('profitPercentage')}% profit")
                notifier.send_notification(
                    title=f"Arbitrage: {p1} vs {p2}",
                    message=f"Guaranteed profit: {arb_result.get('profitPercentage')}%\n"
                            f"{arb_result.get('bestOdds')}",
                    priority="urgent",
                    tags=["rotating_light", "moneybag"],
                )
        except Exception as e:
            print(f"[main] Arbitrage check failed for {event_id}: {e}")

        # 3. Get pre-match / live odds and compare vs model
        try:
            odds_resp = api.get_pre_match_odds(event_id)
            best_odds = _extract_best_h2h_odds(odds_resp)
        except Exception as e:
            print(f"[main] Odds fetch failed for {event_id}: {e}")
            best_odds = {}

        market_odds_p1 = best_odds.get(p1) or (list(best_odds.values())[0] if best_odds else None)
        implied_p1 = (1.0 / market_odds_p1) if market_odds_p1 else None
        edge = (model_prob - implied_p1) if (model_prob and implied_p1) else None

        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "player": p1,
            "opponent": p2,
            "tour_type": tour_type,
            "model_prob": round(model_prob, 4) if model_prob else None,
            "market_odds": market_odds_p1,
            "implied_prob": round(implied_p1, 4) if implied_p1 else None,
            "edge": round(edge, 4) if edge else None,
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
    print("[main] Checking live tennis events ...")
    process_live_events()


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
