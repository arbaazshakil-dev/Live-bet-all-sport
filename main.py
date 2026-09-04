"""
Main polling loop (v4, api-tennis.com): pulls live tennis matches (which
already include score/stats/point-by-point inline), estimates a MODEL win
probability from each player's current ATP/WTA ranking points, pulls market
odds, flags value bets and high-confidence picks, sends push notifications,
and logs everything.

Each run also SETTLES past predictions: any prior row whose match has since
finished gets checked against the real result, so predictions_log.csv builds
a running accuracy record over time instead of just being a one-shot log.

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

FIELDNAMES = [
    "timestamp", "event_id", "player", "opponent", "tour_type",
    "model_prob", "market_odds", "implied_prob", "edge",
    "correct", "actual_winner", "settled_at",
]


def load_predictions():
    if not os.path.exists(config.LOG_FILE):
        return []
    with open(config.LOG_FILE, newline="") as f:
        return list(csv.DictReader(f))


def save_predictions(rows):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            # normalize so every row has every column, in order
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def settle_predictions(rows):
    """For every row that has a model prediction but no recorded outcome yet,
    check whether that match has finished and, if so, record whether the
    model's favored player actually won."""
    settled_count = 0
    for row in rows:
        if row.get("correct") not in (None, ""):
            continue  # already settled
        if not row.get("model_prob"):
            continue  # nothing to grade -- we made no call on this match
        event_id = row.get("event_id")
        if not event_id:
            continue

        match_date = (row.get("timestamp") or "")[:10]
        if not match_date:
            continue

        try:
            fixtures = api.get_fixtures(match_date, match_date, match_key=event_id)
        except Exception as e:
            print(f"[main] Settlement check failed for {row.get('player')} vs {row.get('opponent')}: {e}")
            continue

        if not fixtures:
            continue
        fixture = fixtures[0]
        winner = fixture.get("event_winner")
        if winner not in ("First Player", "Second Player"):
            continue  # not finished yet

        model_favors_p1 = float(row["model_prob"]) >= 0.5
        actual_p1_won = winner == "First Player"
        row["correct"] = "1" if (model_favors_p1 == actual_p1_won) else "0"
        row["actual_winner"] = row["player"] if actual_p1_won else row["opponent"]
        row["settled_at"] = datetime.now(timezone.utc).isoformat()
        settled_count += 1

    if settled_count:
        graded = [r for r in rows if r.get("correct") in ("0", "1")]
        correct = sum(1 for r in graded if r.get("correct") == "1")
        print(f"[main] Settled {settled_count} prediction(s) this run. "
              f"Running accuracy: {correct}/{len(graded)} ({correct / len(graded):.1%})")
    return rows


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


def _build_h2h_entry(p1_key, p2_key):
    """Head-to-head record between these two players, plus each player's
    last 5 results (from the same H2H call -- no extra API cost)."""
    try:
        h2h = api.get_h2h(p1_key, p2_key)
    except Exception as e:
        print(f"[main] H2H fetch failed: {e}")
        return None

    p1_wins = p2_wins = 0
    for m in (h2h.get("H2H") or []):
        winner = m.get("event_winner")
        if str(m.get("first_player_key")) == str(p1_key):
            if winner == "First Player":
                p1_wins += 1
            elif winner == "Second Player":
                p2_wins += 1
        elif str(m.get("first_player_key")) == str(p2_key):
            if winner == "First Player":
                p2_wins += 1
            elif winner == "Second Player":
                p1_wins += 1

    def _form(results, player_key):
        out = []
        for m in (results or [])[:5]:
            winner = m.get("event_winner")
            if winner not in ("First Player", "Second Player"):
                continue
            is_p1_slot = str(m.get("first_player_key")) == str(player_key)
            won = (winner == "First Player") == is_p1_slot
            opp = m.get("event_second_player") if is_p1_slot else m.get("event_first_player")
            out.append({"result": "W" if won else "L", "opponent": opp, "score": m.get("event_final_result")})
        return out

    return {
        "h2h_record": f"{p1_wins}-{p2_wins}",
        "p1_form": _form(h2h.get("firstPlayerResults"), p1_key),
        "p2_form": _form(h2h.get("secondPlayerResults"), p2_key),
    }


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

    name_lookup = {
        "aces": "aces",
        "double faults": "double_faults",
        "1st serve points won": "win_1st_serve",
        "break points won": "break_point_conversions",
    }
    pairs = {k: [None, None] for k in ("aces", "double_faults", "win_1st_serve", "break_point_conversions")}
    for stat in (match.get("statistics") or []):
        key = name_lookup.get(str(stat.get("stat_name", "")).strip().lower())
        if not key:
            continue
        idx = 0 if str(stat.get("player_key")) == p1_key else (1 if str(stat.get("player_key")) == p2_key else None)
        if idx is not None:
            pairs[key][idx] = stat.get("stat_value")

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


def process_live_matches(existing_rows):
    new_rows = []

    try:
        live = api.get_livescore()
    except Exception as e:
        print(f"[main] Failed to fetch live matches: {e}")
        return new_rows

    if not live:
        print("[main] No live tennis matches right now.")
        save_live_stats({})
        return new_rows

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
        if config.ENABLE_H2H:
            h2h_entry = _build_h2h_entry(p1_key, p2_key)
            if h2h_entry:
                stats_by_event[str(event_id)]["h2h"] = h2h_entry

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
            "model_prob": round(model_prob, 4) if model_prob is not None else "",
            "market_odds": market_odds_p1 if market_odds_p1 is not None else "",
            "implied_prob": round(implied_p1, 4) if implied_p1 is not None else "",
            "edge": round(edge, 4) if edge is not None else "",
            "correct": "",
            "actual_winner": "",
            "settled_at": "",
        }
        new_rows.append(row)

        if edge is not None and edge >= config.EDGE_THRESHOLD:
            print(f"[VALUE BET] {p1} vs {p2}: edge={edge:.1%}")
            notifier.notify_value_bet(p1, p2, model_prob, market_odds_p1, edge, "best available")
        elif model_prob is not None and model_prob >= config.CONFIDENCE_THRESHOLD:
            print(f"[HIGH CONFIDENCE] {p1} vs {p2}: prob={model_prob:.1%}")
            notifier.notify_high_confidence(p1, p2, model_prob)

    save_live_stats(stats_by_event)
    return new_rows


def run_once():
    existing_rows = load_predictions()

    print("[main] Settling past predictions ...")
    existing_rows = settle_predictions(existing_rows)

    print("[main] Checking live tennis matches ...")
    new_rows = process_live_matches(existing_rows)

    save_predictions(existing_rows + new_rows)


def run_bounded_loop(max_minutes):
    """Keeps polling every POLL_INTERVAL_SECONDS until max_minutes have
    elapsed, then exits. Used inside a single GitHub Actions run so it stays
    active and catches matches mid-session instead of taking one snapshot
    and quitting -- while still finishing before the next scheduled run
    starts (see run_model.yml)."""
    deadline = time.monotonic() + max_minutes * 60
    pass_num = 0
    while True:
        pass_num += 1
        print(f"[main] --- Pass {pass_num} ---")
        run_once()
        remaining = deadline - time.monotonic()
        if remaining <= config.POLL_INTERVAL_SECONDS:
            print(f"[main] {remaining:.0f}s left in this run's window -- stopping here.")
            break
        print(f"[main] Sleeping {config.POLL_INTERVAL_SECONDS}s ...")
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single pass and exit immediately")
    parser.add_argument("--minutes", type=int, default=None,
                         help="Override how long to keep polling before exiting (default: config.MAX_RUN_MINUTES)")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_bounded_loop(args.minutes if args.minutes is not None else config.MAX_RUN_MINUTES)
