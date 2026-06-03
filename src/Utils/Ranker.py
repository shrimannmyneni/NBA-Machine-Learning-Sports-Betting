from src.Utils.Weighted_Bet_Value import weighted_bet_value


def rank_bets(bets, top_n=10):
    """
    Attaches a weighted_value to each bet dict and returns the top N sorted descending.
    Mutates the dicts in-place so callers can inspect the score.
    """
    for bet in bets:
        bet["weighted_value"] = weighted_bet_value(
            bet.get("ev", 0.0),
            bet.get("confidence", 0.0),
            bet.get("kelly", 0.0),
        )
    return sorted(bets, key=lambda x: x["weighted_value"], reverse=True)[:top_n]
