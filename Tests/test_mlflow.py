from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ── Basic availability ────────────────────────────────────────────────────────

def test_mlflow_importable():
    import mlflow
    assert hasattr(mlflow, "search_runs"), "mlflow.search_runs not found — unexpected version"


def test_mlflow_db_exists():
    db = PROJECT_ROOT / "mlflow.db"
    assert db.exists(), (
        "mlflow.db not found in project root — no training run has been logged yet. "
        "Run: python -m src.Train-Models.Props_Model"
    )


# ── Experiment and run existence ──────────────────────────────────────────────

def test_props_experiment_has_runs():
    import mlflow
    mlflow.set_tracking_uri(f"sqlite:///{PROJECT_ROOT}/mlflow.db")
    runs = mlflow.search_runs(experiment_names=["props-model"])
    finished = runs[runs["status"] == "FINISHED"]
    assert not finished.empty, (
        "No completed runs in 'props-model' experiment — "
        "run: python -m src.Train-Models.Props_Model"
    )


# ── Latest run field checks (use latest_mlflow_run fixture) ──────────────────

def test_latest_run_has_required_metrics(latest_mlflow_run):
    required = [
        "val_log_loss", "test_accuracy", "test_roc_auc",
        "test_log_loss", "calibration_a", "calibration_b",
    ]
    missing = [m for m in required if pd.isna(latest_mlflow_run.get(f"metrics.{m}"))]
    assert not missing, (
        f"Latest props-model run is missing metrics: {missing}. "
        "Retrain with updated Props_Model.py to populate all 6 metrics."
    )


def test_latest_run_has_required_params(latest_mlflow_run):
    required = [
        "n_estimators", "max_depth", "learning_rate",
        "subsample", "colsample_bytree", "n_training_rows", "hit_rate",
    ]
    missing = [p for p in required if pd.isna(latest_mlflow_run.get(f"params.{p}"))]
    assert not missing, (
        f"Latest props-model run is missing params: {missing}. "
        "Retrain with updated Props_Model.py to populate all 7 params."
    )


def test_latest_run_has_archive_tag(latest_mlflow_run):
    tag = latest_mlflow_run.get("tags.n_games_in_archive")
    assert pd.notna(tag), "n_games_in_archive tag missing from latest MLflow run"
    assert int(tag) > 0, (
        f"n_games_in_archive tag is '{tag}' — expected a positive count of labeled archives"
    )


def test_latest_run_training_rows_above_threshold(latest_mlflow_run):
    raw = latest_mlflow_run.get("params.n_training_rows")
    assert pd.notna(raw), "params.n_training_rows missing from latest MLflow run"
    n = int(raw)
    assert n > 2000, (
        f"n_training_rows={n} is below 2000 — "
        "model may have been trained on v1/contaminated data (expected > 2000 rows from v2 pipeline)"
    )


def test_latest_run_auc_above_threshold(latest_mlflow_run):
    auc = latest_mlflow_run.get("metrics.test_roc_auc")
    assert pd.notna(auc), "metrics.test_roc_auc missing from latest MLflow run"
    assert float(auc) > 0.52, (
        f"test_roc_auc={auc:.4f} is at or below 0.52 — "
        "model may have regressed to random noise (AUC ≈ 0.5)"
    )
