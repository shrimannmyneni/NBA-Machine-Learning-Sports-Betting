"""
Computes EV for player prop bets parsed from a CSV and returns a list of dicts
in the same shape as XGBoost_Runner / NN_Runner.

Model priority per prop:
  1. ModelProb column in the CSV  (manual override / Perplexity pipeline)
  2. Trained XGBoost props model from Models/Props_Models/  (if present)
  3. Implied probability from the American odds  (vig-adjusted fallback)

The trained model always predicts P(OVER hits). For UNDER bets the runner
flips to 1 - P(OVER) before computing EV, so the EV/Kelly/confidence numbers
are always "probability this specific bet wins."
"""

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from src.DataProviders.BRefDefenseProvider import get_team_defense
from src.DataProviders.BRefPlayerStatsProvider import (
    PLAYER_TO_BREF_ID,
    get_player_game_log,
    get_rolling_averages,
)
from src.DataProviders.PlayerPropsProvider import parse_props_csv
from src.Utils import Expected_Value
from src.Utils import Kelly_Criterion as kc

_SEASON_YEAR = 2026
_MODEL_DIR   = Path(__file__).resolve().parents[2] / "Models" / "Props_Models"

PROP_TO_AVG = {
    "Points":     "pts_avg",
    "Rebounds":   "trb_avg",
    "Assists":    "ast_avg",
    "3-Pointers": "fg3_avg",
}
PROP_TO_STD = {
    "Points":     "pts_std",
    "Rebounds":   "trb_std",
    "Assists":    "ast_std",
    "3-Pointers": "fg3_std",
}
PROP_TO_DEF = {
    "Points":     "opp_pts",
    "Rebounds":   "opp_trb",
    "Assists":    "opp_ast",
    "3-Pointers": "opp_3p",
}

# Module-level cache — model loads once per process.
_model_state = None
_model_tried = False


def _implied_prob(american_odds):
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def _days_since_last_game(player_name):
    try:
        games = get_player_game_log(player_name, year=_SEASON_YEAR)
        if not games:
            return 3
        last_date = datetime.strptime(games[-1]["date"], "%Y-%m-%d").date()
        return min((date.today() - last_date).days, 7)
    except Exception:
        return 3


def _load_model():
    """
    Finds the most recently saved model in Models/Props_Models/ and loads it.
    Returns a state dict on success, None if no model exists yet.
    Loads only once per process.
    """
    global _model_state, _model_tried
    if _model_tried:
        return _model_state
    _model_tried = True

    if not _MODEL_DIR.exists():
        return None

    candidates = [
        f for f in _MODEL_DIR.glob("Props_*.json")
        if "_calibration" not in f.name and "_meta" not in f.name
    ]
    if not candidates:
        return None

    model_path = max(candidates, key=lambda p: p.stat().st_mtime)
    meta_path  = model_path.with_name(model_path.stem + "_meta.json")

    if not meta_path.exists():
        print(f"[Props] Missing meta for {model_path.name} — falling back to implied probability.")
        return None

    with open(meta_path) as f:
        meta = json.load(f)

    try:
        import xgboost as xgb
        booster = xgb.Booster()
        booster.load_model(str(model_path))
    except Exception as exc:
        print(f"[Props] Could not load model ({exc}) — falling back to implied probability.")
        return None

    _model_state = {
        "booster":      booster,
        "feature_cols": meta["feature_cols"],
        "prop_one_hot": meta["prop_one_hot"],
        "def_median":   meta["opp_def_stat_median"],
        "calib_a":      meta.get("calib_a"),
        "calib_b":      meta.get("calib_b"),
    }
    print(f"[Props] Model: {model_path.name}  accuracy={meta.get('accuracy', '?')}  auc={meta.get('roc_auc', '?')}")
    return _model_state


def _predict_p_over(meta, model_state):
    """
    Returns P(OVER hits) from the trained model, or None on any failure.
    Failures are silent — the caller falls through to implied probability.
    """
    import xgboost as xgb

    player    = meta["player"]
    prop_type = meta["prop"]

    avg_key = PROP_TO_AVG.get(prop_type)
    std_key = PROP_TO_STD.get(prop_type)
    def_col = PROP_TO_DEF.get(prop_type)
    if not all([avg_key, std_key, def_col]):
        return None

    if player not in PLAYER_TO_BREF_ID:
        return None

    try:
        rolling = get_rolling_averages(player, year=_SEASON_YEAR)
    except Exception:
        return None

    if not rolling:
        return None

    stat_avg = rolling.get(avg_key) or 0.0
    stat_std = rolling.get(std_key) or 0.0

    try:
        def_stats    = get_team_defense(meta["opponent"], year=_SEASON_YEAR)
        opp_def_stat = def_stats.get(def_col, model_state["def_median"])
    except Exception:
        opp_def_stat = model_state["def_median"]

    if opp_def_stat is None:
        opp_def_stat = model_state["def_median"]

    line          = meta["line"]
    line_over_avg = (line / stat_avg) if stat_avg > 0 else 1.0
    days_rest     = _days_since_last_game(player)

    # One-hot encode prop type using the same mapping saved in meta.
    prop_one_hot = {v: 0 for v in model_state["prop_one_hot"].values()}
    col = model_state["prop_one_hot"].get(prop_type)
    if col:
        prop_one_hot[col] = 1

    row = {
        "stat_avg":      stat_avg,
        "stat_std":      stat_std,
        "line":          line,
        "line_over_avg": line_over_avg,
        "opp_def_stat":  opp_def_stat,
        "home":          0,   # unknown at inference time; neutral default
        "days_rest":     days_rest,
        **prop_one_hot,
    }

    feat = np.array([[row[c] for c in model_state["feature_cols"]]], dtype=float)

    try:
        p_raw = float(model_state["booster"].predict(xgb.DMatrix(feat))[0])
        a = model_state.get("calib_a")
        b = model_state.get("calib_b")
        if a is not None and b is not None:
            # Platt scaling: 1 / (1 + exp(a * p + b))
            return float(1.0 / (1.0 + np.exp(np.clip(a * p_raw + b, -500, 500))))
        return p_raw
    except Exception:
        return None


def props_runner(csv_source):
    """
    csv_source: path string, Path object, or raw CSV text.
    Returns a list of bet dicts (same shape as XGBoost_Runner / NN_Runner).
    """
    props       = parse_props_csv(csv_source)
    model_state = _load_model()
    results     = []

    for key, meta in props.items():
        odds      = meta["odds"]
        direction = meta["direction"]

        # Priority 1: CSV ModelProb override — already P(this bet wins).
        model_prob = meta.get("model_prob")

        # Priority 2: trained model predicts P(OVER); flip for UNDER bets.
        if model_prob is None and model_state is not None:
            p_over = _predict_p_over(meta, model_state)
            if p_over is not None:
                model_prob = p_over if direction == "OVER" else (1.0 - p_over)

        # Priority 3: implied probability from the market odds.
        if model_prob is None:
            model_prob = _implied_prob(odds)

        ev    = float(Expected_Value.expected_value(model_prob, odds))
        kelly = kc.calculate_kelly_criterion(odds, model_prob)

        results.append({
            "team_or_player": meta["player"],
            "event": (
                f"{direction} {meta['line']} {meta['prop']} "
                f"vs {meta['opponent']}"
            ),
            "odds":       odds,
            "ev":         ev,
            "kelly":      kelly,
            "confidence": model_prob,
            "model":      "Props",
        })

    return results
