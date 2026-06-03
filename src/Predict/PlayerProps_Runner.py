"""
Computes EV for player prop bets parsed from a CSV and returns a list of dicts
in the same shape as XGBoost_Runner / NN_Runner, so they can all be fed into
Ranker.rank_bets together.

When a ModelProb column is present in the CSV (set by the Perplexity→Claude
pipeline), that probability is used directly. Otherwise the runner falls back
to the implied probability derived from the American odds — which bakes in the
vig and will produce slightly negative EV for most bets, as expected.
"""

from src.DataProviders.PlayerPropsProvider import parse_props_csv
from src.Utils import Expected_Value
from src.Utils import Kelly_Criterion as kc


def _implied_prob(american_odds):
    """Market-implied win probability (includes vig)."""
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def props_runner(csv_source):
    """
    csv_source: path string, Path object, or raw CSV text.
    Returns a list of bet dicts (same shape as XGBoost_Runner / NN_Runner).
    """
    props = parse_props_csv(csv_source)
    results = []

    for key, meta in props.items():
        odds = meta["odds"]
        model_prob = meta.get("model_prob")

        if model_prob is None:
            # No model probability supplied: fall back to implied probability.
            # EV will be ≤ 0 (vig-adjusted) — useful as a relative ranking
            # signal until a trained props model is available.
            model_prob = _implied_prob(odds)

        ev = float(Expected_Value.expected_value(model_prob, odds))
        kelly = kc.calculate_kelly_criterion(odds, model_prob)

        results.append({
            "team_or_player": meta["player"],
            "event": (
                f"{meta['direction']} {meta['line']} {meta['prop']} "
                f"vs {meta['opponent']}"
            ),
            "odds": odds,
            "ev": ev,
            "kelly": kelly,
            "confidence": model_prob,
            "model": "Props",
        })

    return results
