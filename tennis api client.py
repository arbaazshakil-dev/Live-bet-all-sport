"""
Client for the Tennis API (ATP/WTA/ITF) via RapidAPI.
Docs: https://tennisapidoc.matchstat.com/
"""
import requests

import config

HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
BASE = f"https://{HOST}/tennis/v2"

HEADERS = {
    "X-RapidAPI-Key": config.RAPIDAPI_KEY,
    "X-RapidAPI-Host": HOST,
}


def _get(path, params=None):
    resp = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_live_events():
    """All currently live matches (ATP/WTA/ITF)."""
    return _get("/extend/api/events/live")


def get_upcoming_matches(tour_type="atp", limit=20, page=1):
    """Upcoming scheduled matches. tour_type: 'atp' or 'wta'."""
    return _get(f"/upcoming/matches/{tour_type}", params={"limit": limit, "page": page})


def get_match_prediction(tour_type, player1, player2):
    """Data-driven win prediction for an upcoming match between two named players."""
    return _get(f"/upcoming/match-prediction/{tour_type}/{player1}/{player2}")


def get_pre_match_odds(event_id, market_ids=None):
    """Pre-match odds across bookmakers for a given event id."""
    params = {"market_ids": market_ids} if market_ids else None
    return _get(f"/extend/api/odds/pre-match/{event_id}", params=params)


def get_arbitrage_odds(event_id, market_id=1):
    """Checks whether an arbitrage opportunity currently exists for this event/market."""
    return _get(f"/extend/api/odds/arbitrage/{event_id}", params={"market_id": market_id})


def get_recent_odds(event_id):
    return _get(f"/extend/api/event/recent-odds/get/{event_id}")


def get_live_score(event_id):
    return _get(f"/extend/api/event/live-score/get/{event_id}")
