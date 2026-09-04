"""
Walk-forward backtest: builds Elo ratings incrementally match-by-match
(chronological order, no lookahead) using this WTA dataset's own naming
convention throughout, and at each match -- before updating with its
result -- checks the model's pre-match probability against the market's
pre-match odds. This answers "would this approach have actually worked"
using real historical bookmaker prices, with zero risk of the name-matching
issues that would come from mixing this dataset with the other two.
"""
import glob
import math

import pandas as pd

K_FACTOR = 32
MIN_MATCHES_TO_GRADE = 10  # skip predictions until a player has enough history to mean something
EDGE_THRESHOLD = 0.05


def load_matches():
    files = sorted(glob.glob("2*.xlsx"))
    frames = [pd.read_excel(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["Winner", "Loser", "Date", "AvgW", "AvgL"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def expected_score(ra, rb):
    return 1.0 / (1.0 + math.pow(10, (rb - ra) / 400.0))


def run_backtest():
    df = load_matches()
    print(f"Loaded {len(df)} matches with complete odds, {df['Date'].min().date()} to {df['Date'].max().date()}")

    ratings = {}   # name -> elo rating
    played = {}    # name -> match count so far

    graded = 0
    correct = 0
    value_bets = 0
    value_bet_wins = 0
    total_staked = 0.0
    total_returned = 0.0

    for _, row in df.iterrows():
        winner, loser = row["Winner"], row["Loser"]
        avg_w, avg_l = row["AvgW"], row["AvgL"]
        if avg_w <= 1.0 or avg_l <= 1.0:
            continue

        r_w = ratings.get(winner, 1500.0)
        r_l = ratings.get(loser, 1500.0)
        n_w = played.get(winner, 0)
        n_l = played.get(loser, 0)

        if n_w >= MIN_MATCHES_TO_GRADE and n_l >= MIN_MATCHES_TO_GRADE:
            model_prob_winner = expected_score(r_w, r_l)

            # market's pre-match implied probability, de-vigged
            implied_w_raw = 1.0 / avg_w
            implied_l_raw = 1.0 / avg_l
            overround = implied_w_raw + implied_l_raw
            implied_winner = implied_w_raw / overround
            implied_loser = implied_l_raw / overround
            model_prob_loser = 1.0 - model_prob_winner

            graded += 1
            if model_prob_winner >= 0.5:
                correct += 1

            edge_winner = model_prob_winner - implied_winner
            edge_loser = model_prob_loser - implied_loser

            if edge_winner >= EDGE_THRESHOLD:
                value_bets += 1
                value_bet_wins += 1  # backed the winner
                total_staked += 1
                total_returned += avg_w
            elif edge_loser >= EDGE_THRESHOLD:
                value_bets += 1
                # backed the loser -- lost the stake
                total_staked += 1
                total_returned += 0

        # update Elo with this match's real result (walk-forward, after grading)
        k_w = K_FACTOR * (1.5 if n_w < 50 else 1.0)
        k_l = K_FACTOR * (1.5 if n_l < 50 else 1.0)
        exp_w = expected_score(r_w, r_l)
        ratings[winner] = r_w + k_w * (1 - exp_w)
        ratings[loser] = r_l + k_l * (0 - (1 - exp_w))
        played[winner] = n_w + 1
        played[loser] = n_l + 1

    print()
    print("=== Baseline predictive accuracy (all graded matches) ===")
    print(f"Graded matches:   {graded}")
    print(f"Correct (model favored actual winner): {correct} ({correct/graded:.1%})")
    print()
    print(f"=== Value-bet simulation (edge >= {EDGE_THRESHOLD:.0%}, flat $1 stakes) ===")
    print(f"Value bets flagged: {value_bets}")
    if value_bets:
        print(f"Of those, won (backed eventual winner): {value_bet_wins} ({value_bet_wins/value_bets:.1%})")
        print(f"Total staked: ${total_staked:.0f}")
        print(f"Total returned: ${total_returned:.2f}")
        roi = (total_returned - total_staked) / total_staked
        print(f"ROI: {roi:+.1%}")
    print()
    print(f"Final rated player pool: {len(ratings)} players")


if __name__ == "__main__":
    run_backtest()
