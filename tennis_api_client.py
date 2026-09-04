"""
Client for api-tennis.com (switched from the RapidAPI Tennis API).
Docs: https://api-tennis.com/documentation
"""
import requests

import config

BASE = "https://api.api-tennis.com/tennis/"


def _get(method, params=None):
    query = {"method": method, "APIkey": config.APITENNIS_KEY}
    if params:
        query.update({k: v for k, v in params.items() if v is not None})
    resp = requests.get(BASE, params=query, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") != 1:
        raise RuntimeError(f"api-tennis.com returned success={data.get('success')}: {str(data)[:300]}")
    return data.get("result")


def get_livescore():
    """Currently live matches. Each match includes scores, statistics, and
    pointbypoint inline -- no separate stats call needed."""
    return _get("get_livescore") or []


def get_fixtures(date_start, date_stop, **kwargs):
    return _get("get_fixtures", {"date_start": date_start, "date_stop": date_stop, **kwargs}) or []


def get_odds(match_key):
    """Returns {"<match_key>": {"Home/Away": {"Home": {bookmaker: price, ...}, "Away": {...}}, ...other markets}}"""
    return _get("get_odds", {"match_key": match_key}) or {}


def get_live_odds():
    return _get("get_live_odds") or {}


def get_standings(event_type):
    """event_type: 'ATP' or 'WTA'. Returns ranking list with player_key and points."""
    return _get("get_standings", {"event_type": event_type}) or []


def get_h2h(first_player_key, second_player_key):
    return _get("get_H2H", {"first_player_key": first_player_key, "second_player_key": second_player_key}) or {}


def get_players(player_key):
    return _get("get_players", {"player_key": player_key}) or []
