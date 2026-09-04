"""
Surface-aware Elo rating system built from historical match data.

Two source formats, combined without double-counting:
  - ATP: Sackmann-format CSVs (tourney_date, winner_name, loser_name, surface, ...)
    Full names ("Grigor Dimitrov") normalized to "F. Lastname".
  - WTA: odds-file XLSX (Date, Winner, Loser, Surface, AvgW, AvgL, ...)
    Names come as "Surname Abbrev." (e.g. "Wang Xiy."), normalized to the
    same "F. Lastname" shape by taking the first letter of the abbreviated
    given name.

WTA is sourced from the odds files ONLY (not also from Sackmann's WTA CSVs)
because the two datasets cover a lot of the same real 2024-2025 matches --
feeding both in would double-count those matches and inflate WTA ratings
relative to ATP, which only has one source. ATP keeps using the Sackmann
CSVs since no odds-file equivalent exists for it here.

Both normalized name formats match the live feed's "F. Lastname" style, so
main.py can look up either tour's players the same way. Match isn't
perfect -- two players sharing a first-initial+surname would collide -- but
it degrades safely: unmatched names just return None and main.py falls
back to the ranking-points estimate.

Usage:
    python elo_model.py --build \
        --atp-csv-dir historical \
        --wta-xlsx-dir backtest \
        --out data/elo_ratings.json
    (Run this locally whenever you have new historical files to add --
     GitHub Actions doesn't re-run this; it just loads the JSON output.)
"""
import argparse
import csv
import glob
import json
import math
import os

K_FACTOR = 32
SURFACE_WEIGHT = 0.5  # how much surface-specific rating counts vs overall


def normalize_name(full_name):
    """'Grigor Dimitrov' -> 'G. Dimitrov'. 'Jessica Bouzas Maneiro' -> 'J. Bouzas Maneiro'
    (keeps everything after the first word as the surname, matching how
    api-tennis.com renders multi-word surnames)."""
    if not full_name:
        return None
    parts = full_name.strip().split(" ", 1)
    if len(parts) < 2:
        return full_name.strip()
    first, rest = parts
    return f"{first[0].upper()}. {rest.strip()}"


def normalize_surname_first_name(name):
    """'Wang Xiy.' -> 'X. Wang'. 'Avanesyan E.' -> 'E. Avanesyan'.
    (odds-file format: 'Surname FirstNameAbbrev.' -> live feed's 'F. Lastname')"""
    if not name:
        return None
    name = name.strip().rstrip(".")
    parts = name.rsplit(" ", 1)
    if len(parts) < 2:
        return name
    surname, abbrev = parts
    if not abbrev:
        return None
    return f"{abbrev[0].upper()}. {surname.strip()}"


def _blank_player():
    return {"overall": 1500.0, "hard": 1500.0, "clay": 1500.0, "grass": 1500.0, "matches": 0}


def _expected_score(rating_a, rating_b):
    return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))


def _update(ratings, winner_key, loser_key, surface):
    surface = (surface or "hard").lower()
    if surface not in ("hard", "clay", "grass"):
        surface = "hard"

    for key in (winner_key, loser_key):
        if key not in ratings:
            ratings[key] = _blank_player()

    w, l = ratings[winner_key], ratings[loser_key]
    w_strength = (1 - SURFACE_WEIGHT) * w["overall"] + SURFACE_WEIGHT * w[surface]
    l_strength = (1 - SURFACE_WEIGHT) * l["overall"] + SURFACE_WEIGHT * l[surface]

    exp_w = _expected_score(w_strength, l_strength)
    k_w = K_FACTOR * (1.5 if w["matches"] <= 50 else 1.0)
    k_l = K_FACTOR * (1.5 if l["matches"] <= 50 else 1.0)

    delta_w = k_w * (1.0 - exp_w)
    delta_l = k_l * (0.0 - (1.0 - exp_w))

    for key in ("overall", surface):
        w[key] += delta_w
        l[key] += delta_l

    w["matches"] += 1
    l["matches"] += 1


def _ingest_atp_csvs(ratings, csv_dir):
    files = sorted(glob.glob(os.path.join(csv_dir, "atp_matches*.csv")))
    total = 0
    for filepath in files:
        with open(filepath, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows.sort(key=lambda r: r.get("tourney_date", "0"))
        for row in rows:
            winner = normalize_name(row.get("winner_name"))
            loser = normalize_name(row.get("loser_name"))
            if not winner or not loser:
                continue
            _update(ratings, winner, loser, row.get("surface"))
            total += 1
        print(f"[elo_model] Processed {filepath} ({len(rows)} matches)")
    return total


def _ingest_wta_xlsx(ratings, xlsx_dir):
    import pandas as pd  # only needed for this build step, not at runtime

    files = sorted(glob.glob(os.path.join(xlsx_dir, "*.xlsx")))
    total = 0
    for filepath in files:
        df = pd.read_excel(filepath)
        df = df.dropna(subset=["Winner", "Loser", "Date"]).sort_values("Date")
        for _, row in df.iterrows():
            winner = normalize_surname_first_name(row.get("Winner"))
            loser = normalize_surname_first_name(row.get("Loser"))
            if not winner or not loser:
                continue
            _update(ratings, winner, loser, row.get("Surface"))
            total += 1
        print(f"[elo_model] Processed {filepath} ({len(df)} matches)")
    return total


def build_ratings(atp_csv_dir=None, wta_xlsx_dir=None):
    ratings = {}
    total = 0

    if atp_csv_dir:
        total += _ingest_atp_csvs(ratings, atp_csv_dir)
    if wta_xlsx_dir:
        total += _ingest_wta_xlsx(ratings, wta_xlsx_dir)

    if total == 0:
        raise FileNotFoundError("No matches ingested -- check --atp-csv-dir / --wta-xlsx-dir paths.")

    print(f"[elo_model] Total: {total} matches, {len(ratings)} players rated.")
    return ratings


def win_probability(ratings, name1, name2, surface="hard"):
    """Returns model win probability for name1 over name2. Names should
    already be in 'F. Lastname' form (the live feed's format). Returns
    None if either player isn't in the ratings."""
    p1 = ratings.get(name1)
    p2 = ratings.get(name2)
    if p1 is None or p2 is None:
        return None

    # NOTE: overall and surface-specific ratings are updated on different
    # numbers of matches (overall on every match, hard/clay/grass only on
    # matches of that surface), so blending them directly under-weights
    # players with lopsided surface schedules. Until that's fixed properly,
    # this uses overall rating only -- correct on average, just not
    # surface-adjusted yet.
    return _expected_score(p1["overall"], p2["overall"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="Build ratings from historical files")
    parser.add_argument("--atp-csv-dir", default=None, help="Directory containing Sackmann-format atp_matches*.csv files")
    parser.add_argument("--wta-xlsx-dir", default=None, help="Directory containing the WTA odds-file *.xlsx files")
    parser.add_argument("--out", default="data/elo_ratings.json", help="Where to save the ratings JSON")
    args = parser.parse_args()

    if args.build:
        ratings = build_ratings(atp_csv_dir=args.atp_csv_dir, wta_xlsx_dir=args.wta_xlsx_dir)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(ratings, f, indent=2)
        print(f"[elo_model] Saved {len(ratings)} player ratings to {args.out}")
