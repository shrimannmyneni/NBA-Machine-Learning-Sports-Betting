import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from src.Utils import Expected_Value
from src.Utils import Kelly_Criterion as kc


BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_DIR = BASE_DIR / "Models" / "XGBoost_Models"
ACCURACY_PATTERN = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")

xgb_ml = None
xgb_uo = None
xgb_ml_calibrator = None
xgb_uo_calibrator = None


def _select_model_path(kind):
    candidates = list(MODEL_DIR.glob(f"*{kind}*.json"))
    if not candidates:
        raise FileNotFoundError(f"No XGBoost {kind} model found in {MODEL_DIR}")

    def score(path):
        match = ACCURACY_PATTERN.search(path.name)
        accuracy = float(match.group(1)) if match else 0.0
        return (path.stat().st_mtime, accuracy)

    return max(candidates, key=score)


def _load_calibrator(model_path):
    calibration_path = model_path.with_name(f"{model_path.stem}_calibration.pkl")
    if not calibration_path.exists():
        return None
    try:
        return joblib.load(calibration_path)
    except Exception:
        return None


def _load_models():
    global xgb_ml, xgb_uo, xgb_ml_calibrator, xgb_uo_calibrator
    if xgb_ml is None:
        ml_path = _select_model_path("ML")
        xgb_ml = xgb.Booster()
        xgb_ml.load_model(str(ml_path))
        xgb_ml_calibrator = _load_calibrator(ml_path)
    if xgb_uo is None:
        uo_path = _select_model_path("UO")
        xgb_uo = xgb.Booster()
        xgb_uo.load_model(str(uo_path))
        xgb_uo_calibrator = _load_calibrator(uo_path)


def _predict_probs(model, data, calibrator=None):
    if calibrator is not None:
        return calibrator.predict_proba(data)
    return model.predict(xgb.DMatrix(data))


def _collect_results(games, ml_predictions_array, ou_predictions_array, todays_games_uo, home_team_odds, away_team_odds):
    results = []
    for idx, game in enumerate(games):
        home_team, away_team = game

        winner = int(np.argmax(ml_predictions_array[idx]))
        under_over = int(np.argmax(ou_predictions_array[idx]))
        winner_confidence = round(ml_predictions_array[idx][winner] * 100, 1)
        ou_confidence = round(ou_predictions_array[idx][under_over] * 100, 1)
        ou_label = "UNDER" if under_over == 0 else "OVER"

        p_home = float(ml_predictions_array[idx][1])
        p_away = float(ml_predictions_array[idx][0])

        ev_home = ev_away = 0.0
        kelly_home = kelly_away = 0.0
        if home_team_odds[idx] and away_team_odds[idx]:
            ev_home = float(Expected_Value.expected_value(p_home, int(home_team_odds[idx])))
            ev_away = float(Expected_Value.expected_value(p_away, int(away_team_odds[idx])))
            kelly_home = kc.calculate_kelly_criterion(home_team_odds[idx], p_home)
            kelly_away = kc.calculate_kelly_criterion(away_team_odds[idx], p_away)

        ou_note = f"{ou_label} {todays_games_uo[idx]} ({ou_confidence}%)"

        results.append({
            "team_or_player": home_team,
            "event": f"ML vs {away_team} | {ou_note}",
            "odds": int(home_team_odds[idx]) if home_team_odds[idx] else None,
            "ev": ev_home,
            "kelly": kelly_home,
            "confidence": p_home,
            "model": "XGBoost",
        })
        results.append({
            "team_or_player": away_team,
            "event": f"ML @ {home_team} | {ou_note}",
            "odds": int(away_team_odds[idx]) if away_team_odds[idx] else None,
            "ev": ev_away,
            "kelly": kelly_away,
            "confidence": p_away,
            "model": "XGBoost",
        })

    return results


def xgb_runner(data, todays_games_uo, frame_ml, games, home_team_odds, away_team_odds, kelly_criterion):
    _load_models()

    frame_uo = frame_ml.copy()
    frame_uo["OU"] = np.asarray(todays_games_uo, dtype=float)

    ml_predictions_array = _predict_probs(xgb_ml, data, xgb_ml_calibrator)
    ou_predictions_array = _predict_probs(
        xgb_uo,
        frame_uo.values.astype(float),
        xgb_uo_calibrator,
    )

    return _collect_results(
        games,
        ml_predictions_array,
        ou_predictions_array,
        todays_games_uo,
        home_team_odds,
        away_team_odds,
    )
