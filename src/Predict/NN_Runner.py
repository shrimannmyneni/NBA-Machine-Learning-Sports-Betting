import copy
import re
from pathlib import Path

import numpy as np
import tensorflow as tf
from keras.models import load_model
from src.Utils import Expected_Value
from src.Utils import Kelly_Criterion as kc

BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_DIR = BASE_DIR / "Models"
LEGACY_MODEL_DIR = MODEL_DIR / "NN_Models"
ML_PATTERN = re.compile(r"Trained-Model-ML-(\d+(?:\.\d+)?)")
OU_PATTERN = re.compile(r"Trained-Model-OU-(\d+(?:\.\d+)?)")

_model = None
_ou_model = None


def _list_model_candidates(prefix):
    candidates = []
    for base in (MODEL_DIR, LEGACY_MODEL_DIR):
        if not base.exists():
            continue
        for path in base.glob(f"{prefix}*"):
            if path.is_dir():
                candidates.append(path)
                continue
            if path.suffix in {".keras", ".h5"}:
                candidates.append(path)
    return candidates


def _select_best_model(prefix, pattern):
    candidates = _list_model_candidates(prefix)
    if not candidates:
        raise FileNotFoundError(f"No model found for prefix {prefix} in {MODEL_DIR}")

    def score(path):
        match = pattern.search(path.name)
        accuracy = float(match.group(1)) if match else 0.0
        if not (0.0 <= accuracy <= 100.0):
            accuracy = 0.0
        return (accuracy, path.stat().st_mtime)

    return max(candidates, key=score)


def _load_models():
    global _model, _ou_model
    if _model is None:
        ml_path = _select_best_model("Trained-Model-ML-", ML_PATTERN)
        _model = load_model(str(ml_path), compile=False)
    if _ou_model is None:
        ou_path = _select_best_model("Trained-Model-OU-", OU_PATTERN)
        _ou_model = load_model(str(ou_path), compile=False)


def nn_runner(data, todays_games_uo, frame_ml, games, home_team_odds, away_team_odds, kelly_criterion):
    _load_models()

    ml_predictions_array = []
    for row in data:
        ml_predictions_array.append(_model.predict(np.array([row])))

    frame_uo = copy.deepcopy(frame_ml)
    frame_uo['OU'] = np.asarray(todays_games_uo)
    uo_data = frame_uo.values.astype(float)
    uo_data = tf.keras.utils.normalize(uo_data, axis=1)

    ou_predictions_array = []
    for row in uo_data:
        ou_predictions_array.append(_ou_model.predict(np.array([row])))

    results = []
    for idx, game in enumerate(games):
        home_team, away_team = game

        # ml_predictions_array[idx] has shape (1, 2): [[p_away, p_home]]
        p_home = float(ml_predictions_array[idx][0][1])
        p_away = float(ml_predictions_array[idx][0][0])

        winner = int(np.argmax(ml_predictions_array[idx]))
        under_over = int(np.argmax(ou_predictions_array[idx]))
        winner_confidence = round(ml_predictions_array[idx][0][winner] * 100, 1)
        ou_confidence = round(ou_predictions_array[idx][0][under_over] * 100, 1)
        ou_label = "UNDER" if under_over == 0 else "OVER"

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
            "model": "NN",
        })
        results.append({
            "team_or_player": away_team,
            "event": f"ML @ {home_team} | {ou_note}",
            "odds": int(away_team_odds[idx]) if away_team_odds[idx] else None,
            "ev": ev_away,
            "kelly": kelly_away,
            "confidence": p_away,
            "model": "NN",
        })

    return results
