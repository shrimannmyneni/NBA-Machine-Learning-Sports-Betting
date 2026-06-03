def weighted_bet_value(ev, confidence, kelly, ev_weight=0.4, conf_weight=0.4, kelly_weight=0.2):
    """
    ev: Expected value in dollar units per $100 risked
    confidence: Model win probability (0-1)
    kelly: Kelly criterion bankroll fraction (percentage points, e.g. 5.2)
    Returns a composite score. Weights prioritise probability over raw payout.
    """
    return round(ev * ev_weight + confidence * conf_weight + kelly * kelly_weight, 4)
