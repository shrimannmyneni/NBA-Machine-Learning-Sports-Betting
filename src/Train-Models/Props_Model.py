"""
Trains a binary XGBoost classifier to predict player prop hit probability.

Input:  tmp_data/props_training.csv  (built by Build_Props_Training_Data.py)
Output: Models/Props_Models/Props_{acc}pct_{date}.json
        Models/Props_Models/Props_{acc}pct_{date}_calibration.pkl
        Models/Props_Models/Props_{acc}pct_{date}_meta.json

The model predicts P(OVER hits), i.e., P(actual_stat > line).
For UNDER bets the runner uses 1 - P(OVER).

Usage:
    python -m src.Train-Models.Props_Model
    python -m src.Train-Models.Props_Model --trials 50 --splits 5 --calibration sigmoid
"""

import argparse
import json
from datetime import date
from pathlib import Path

from src.Utils.ts import ts

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

try:
    import mlflow
    import mlflow.xgboost
    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False

BASE_DIR     = Path(__file__).resolve().parents[2]
TRAINING_CSV = BASE_DIR / "tmp_data" / "props_training.csv"
MODEL_DIR    = BASE_DIR / "Models" / "Props_Models"

# Explicit one-hot column names — must match what Build_Props_Training_Data writes
# and what PlayerProps_Runner will construct at inference time.
PROP_ONE_HOT = {
    "Points":     "prop_pts",
    "Rebounds":   "prop_reb",
    "Assists":    "prop_ast",
    "3-Pointers": "prop_3pm",
}

FEATURE_COLS = [
    "stat_avg", "stat_std", "line", "line_over_avg", "opp_def_stat",
    "home", "days_rest",
    "prop_pts", "prop_reb", "prop_ast", "prop_3pm",
]

TARGET_COL = "hit"
DATE_COL   = "game_date"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_and_prepare(csv_path):
    df = pd.read_csv(csv_path)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df = df.dropna(subset=[DATE_COL]).sort_values(DATE_COL).reset_index(drop=True)

    for prop_type, col in PROP_ONE_HOT.items():
        df[col] = (df["prop_type"] == prop_type).astype(int)

    # Impute missing opp_def_stat (fetch failures) with column median.
    def_median = float(df["opp_def_stat"].median())
    df["opp_def_stat"] = df["opp_def_stat"].fillna(def_median)

    # line_over_avg is None when stat_avg was 0; treat as "line equals average".
    df["line_over_avg"] = df["line_over_avg"].fillna(1.0)

    prop_types = sorted(df["prop_type"].dropna().unique().tolist())

    X = df[FEATURE_COLS].astype(float).to_numpy()
    y = df[TARGET_COL].astype(int).to_numpy()

    return X, y, def_median, prop_types


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

def sample_params(rng, seed):
    params = {
        "max_depth":        int(rng.integers(2, 8)),
        "eta":              float(10 ** rng.uniform(np.log10(0.01), np.log10(0.3))),
        "subsample":        float(rng.uniform(0.5, 1.0)),
        "colsample_bytree": float(rng.uniform(0.5, 1.0)),
        "min_child_weight": int(rng.integers(1, 10)),
        "gamma":            float(rng.uniform(0.0, 5.0)),
        "lambda":           float(10 ** rng.uniform(np.log10(0.1), np.log10(10.0))),
        "alpha":            float(10 ** rng.uniform(np.log10(0.01), np.log10(5.0))),
        "objective":        "binary:logistic",
        "eval_metric":      "logloss",
        "seed":             seed,
        "tree_method":      "hist",
    }
    num_boost_round = int(rng.integers(100, 800))
    return params, num_boost_round


def train_model(X_train, y_train, X_val, y_val, params, num_boost_round):
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dval   = xgb.DMatrix(X_val,   label=y_val)
    return xgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=50,
        verbose_eval=False,
    )


def walk_forward_cv_loss(X, y, params, num_boost_round, n_splits):
    tscv   = TimeSeriesSplit(n_splits=n_splits)
    losses = []
    for train_idx, val_idx in tscv.split(X):
        model     = train_model(X[train_idx], y[train_idx], X[val_idx], y[val_idx], params, num_boost_round)
        val_probs = model.predict(xgb.DMatrix(X[val_idx]))
        losses.append(log_loss(y[val_idx], val_probs))
    return float(np.mean(losses)) if losses else None


def split_temporal(X, y, holdout=0.15):
    n = len(X)
    cut = int(n * (1 - holdout))
    return X[:cut], y[:cut], X[cut:], y[cut:]


# ---------------------------------------------------------------------------
# Calibration wrapper (binary:logistic returns 1-D probs, sklearn wants 2-D)
# ---------------------------------------------------------------------------

class _BoosterWrapper:
    def __init__(self, booster):
        self.booster  = booster
        self.classes_ = np.array([0, 1])

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        p1 = self.booster.predict(xgb.DMatrix(X))
        return np.column_stack([1 - p1, p1])


# ---------------------------------------------------------------------------
# MLflow helpers
# ---------------------------------------------------------------------------

def _count_labeled_archives(base_dir):
    count = 0
    for p in (base_dir / "Data" / "prop_archives").glob("*.csv"):
        try:
            df = pd.read_csv(p, usecols=["Hit"])
            if df["Hit"].notna().any():
                count += 1
        except Exception:
            pass
    return count


def _log_to_mlflow(best, accuracy, auc, tl, calib_a, calib_b,
                   best_model, training_csv_path, n_training_rows,
                   hit_rate, prop_types):
    mlflow.set_experiment("props-model")
    with mlflow.start_run():
        mlflow.log_params({
            "n_estimators":     best["num_boost_round"],
            "max_depth":        best["params"]["max_depth"],
            "learning_rate":    round(best["params"]["eta"], 6),
            "subsample":        round(best["params"]["subsample"], 4),
            "colsample_bytree": round(best["params"]["colsample_bytree"], 4),
            "n_training_rows":  n_training_rows,
            "hit_rate":         round(hit_rate, 4),
            "prop_types":       str(prop_types),
        })

        metrics = {
            "val_log_loss":  round(best["val_loss"], 4),
            "test_accuracy": round(accuracy, 4),
            "test_roc_auc":  round(auc, 4),
            "test_log_loss": round(tl, 4),
        }
        if calib_a is not None:
            metrics["calibration_a"] = round(calib_a, 6)
        if calib_b is not None:
            metrics["calibration_b"] = round(calib_b, 6)
        mlflow.log_metrics(metrics)

        mlflow.xgboost.log_model(best_model, name="model")
        mlflow.log_artifact(str(training_csv_path))

        mlflow.set_tags({
            "run_date":           str(date.today()),
            "n_games_in_archive": str(_count_labeled_archives(BASE_DIR)),
        })

    print(ts("[MLflow] Run logged to experiment 'props-model'"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train XGBoost props hit model.")
    parser.add_argument("--csv",         default=str(TRAINING_CSV))
    parser.add_argument("--seed",        type=int,   default=42)
    parser.add_argument("--trials",      type=int,   default=30)
    parser.add_argument("--splits",      type=int,   default=5)
    parser.add_argument("--calibration", default="sigmoid",
                        choices=["sigmoid", "isotonic", "none"])
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if not Path(args.csv).exists():
        print(ts(f"Training CSV not found: {args.csv}"))
        print(ts("Run: python -m src.Process-Data.Build_Props_Training_Data first."))
        return

    X, y, def_median, prop_types = load_and_prepare(args.csv)
    print(ts(f"Loaded {len(X)} training rows, {int(y.sum())} hits ({y.mean()*100:.1f}% hit rate)."))

    X_tv, y_tv, X_test, y_test = split_temporal(X, y)

    rng  = np.random.default_rng(args.seed)
    best = {"val_loss": float("inf"), "params": None, "num_boost_round": None}

    for trial in range(1, args.trials + 1):
        params, nbr = sample_params(rng, seed=args.seed + trial)
        val_loss    = walk_forward_cv_loss(X_tv, y_tv, params, nbr, args.splits)
        if val_loss is None:
            continue
        if val_loss < best["val_loss"]:
            best.update({"val_loss": val_loss, "params": params, "num_boost_round": nbr})
        print(ts(f"  Trial {trial:3d}/{args.trials}: val log loss {val_loss:.4f}"))

    if best["params"] is None:
        print(ts("No valid parameter set found."))
        return

    # Final model on train portion; hold out 10% of train for calibration.
    n_tv   = len(X_tv)
    calib_cut = int(n_tv * 0.9)
    X_train, y_train = X_tv[:calib_cut], y_tv[:calib_cut]
    X_calib, y_calib = X_tv[calib_cut:], y_tv[calib_cut:]

    best_model = train_model(X_train, y_train, X_calib, y_calib,
                             best["params"], best["num_boost_round"])

    if args.calibration == "none":
        test_probs = best_model.predict(xgb.DMatrix(X_test))
        calibrator = None
    else:
        calibrator = CalibratedClassifierCV(
            _BoosterWrapper(best_model), method=args.calibration, cv="prefit"
        )
        calibrator.fit(X_calib, y_calib)
        test_probs = calibrator.predict_proba(X_test)[:, 1]

    y_pred   = (test_probs >= 0.5).astype(int)
    accuracy = accuracy_score(y_test, y_pred)
    auc      = roc_auc_score(y_test, test_probs)
    tl       = log_loss(y_test, test_probs)

    print(ts(f"Best val log loss : {best['val_loss']:.4f}"))
    print(ts(f"Test accuracy     : {accuracy:.4f}  ({accuracy*100:.1f}%)"))
    print(ts(f"Test ROC-AUC      : {auc:.4f}"))
    print(ts(f"Test log loss     : {tl:.4f}"))

    stem = f"Props_{accuracy*100:.1f}pct_{date.today()}"

    model_path = MODEL_DIR / f"{stem}.json"
    best_model.save_model(str(model_path))
    print(ts(f"Saved model       : {model_path}"))

    # Extract Platt scaling coefficients (two floats) instead of pickling the
    # sklearn wrapper — avoids _BoosterWrapper unpickling errors across modules.
    calib_a = calib_b = None
    if calibrator is not None and args.calibration == "sigmoid":
        sig = calibrator.calibrated_classifiers_[0].calibrators[0]
        calib_a = float(sig.a_)
        calib_b = float(sig.b_)
        print(ts(f"Calibration       : sigmoid  a={calib_a:.4f}  b={calib_b:.4f}"))

    meta = {
        "feature_cols":        FEATURE_COLS,
        "prop_one_hot":        PROP_ONE_HOT,
        "opp_def_stat_median": def_median,
        "accuracy":            round(accuracy, 4),
        "roc_auc":             round(auc, 4),
        "trained_on":          str(date.today()),
        "n_training_rows":     len(X),
        "calib_a":             calib_a,
        "calib_b":             calib_b,
    }
    meta_path = MODEL_DIR / f"{stem}_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(ts(f"Saved meta        : {meta_path}"))

    try:
        if _MLFLOW_AVAILABLE:
            _log_to_mlflow(
                best, accuracy, auc, tl, calib_a, calib_b,
                best_model, args.csv,
                n_training_rows=len(X),
                hit_rate=float(y.mean()),
                prop_types=prop_types,
            )
    except Exception as exc:
        print(ts(f"[MLflow] Logging skipped — {exc}"))


if __name__ == "__main__":
    main()
