"""
Push notifications via ntfy.sh (free, no signup).
Install the ntfy app (iOS/Android), subscribe to config.NTFY_TOPIC, done.
"""
import requests

import config


def send_notification(title, message, priority="default", tags=None):
    """
    priority: "min", "low", "default", "high", "urgent"
    tags: list of ntfy emoji-shortcode tags, e.g. ["tennis", "moneybag"]
    """
    headers = {
        "Title": title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    resp = requests.post(config.NTFY_URL, data=message.encode("utf-8"), headers=headers, timeout=10)
    resp.raise_for_status()
    return resp


def notify_value_bet(player, opponent, model_prob, market_odds, edge, bookmaker):
    send_notification(
        title=f"Value bet: {player}",
        message=(
            f"{player} vs {opponent}\n"
            f"Model win prob: {model_prob:.1%}\n"
            f"Market odds: {market_odds} ({bookmaker}) -> implied {1/market_odds:.1%}\n"
            f"Edge: +{edge:.1%}"
        ),
        priority="high",
        tags=["moneybag", "tennis"],
    )


def notify_high_confidence(player, opponent, model_prob):
    send_notification(
        title=f"High-confidence pick: {player}",
        message=f"{player} vs {opponent}\nModel win prob: {model_prob:.1%}",
        priority="default",
        tags=["dart", "tennis"],
    )
