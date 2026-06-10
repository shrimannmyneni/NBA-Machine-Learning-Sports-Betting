from src.Utils.Weighted_Bet_Value import safe_pick_value, weighted_bet_value


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
    ranked = sorted(bets, key=lambda x: x["weighted_value"], reverse=True)
    return ranked if top_n == 0 else ranked[:top_n]


def rank_safe_picks(bets, top_n=10):
    """
    Filters to favored bets (odds < -100) where the model gives >55% confidence,
    scores them with safe_pick_value (confidence-weighted), and returns the top N
    sorted descending. Mutates the matching dicts in-place with safe_pick_value.
    """
    favored = [
        bet for bet in bets
        if bet.get("odds") is not None and bet["odds"] < -100
        and bet.get("confidence") is not None and bet["confidence"] > 0.55
    ]
    for bet in favored:
        bet["safe_pick_value"] = safe_pick_value(
            bet.get("ev", 0.0),
            bet.get("confidence", 0.0),
            bet.get("kelly", 0.0),
        )
    ranked = sorted(favored, key=lambda x: x["safe_pick_value"], reverse=True)
    return ranked if top_n == 0 else ranked[:top_n]
