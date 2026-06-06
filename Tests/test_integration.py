import importlib.util
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ARCHIVE_CSV = PROJECT_ROOT / "Data/prop_archives/2026-06-03_New_York_Knicks_vs_San_Antonio_Spurs.csv"

_MOCK_ROLLING_AVGS = {
    "pts_avg": 25.0, "pts_std": 5.0,
    "trb_avg": 5.0,  "trb_std": 2.0,
    "ast_avg": 3.0,  "ast_std": 1.0,
    "fg3_avg": 2.0,  "fg3_std": 1.0,
    "games_in_window": 10,
}
_MOCK_TEAM_DEFENSE = {"opp_pts": 110.0, "opp_trb": 42.0, "opp_ast": 24.0, "opp_3p": 12.0}
_MOCK_GAME_LOG = [
    {"date": "2026-05-30", "opp": "NYK", "home": 0, "pts": 20, "trb": 5, "ast": 3, "fg3": 2, "mp": 32}
] * 10


def test_archive_readable_by_provider():
    from src.DataProviders.PlayerPropsProvider import parse_props_csv

    result = parse_props_csv(ARCHIVE_CSV)
    assert isinstance(result, dict)
    assert len(result) > 0, "parse_props_csv returned empty dict for June 3rd archive"


@pytest.mark.skipif(
    len(list((PROJECT_ROOT / "tmp_data" / "player_stats").glob("*.json"))) == 0
    if (PROJECT_ROOT / "tmp_data" / "player_stats").exists() else True,
    reason="BRef player_stats cache empty — running this test would make live HTTP calls",
)
def test_build_training_data_v2_produces_rows():
    import os
    script = PROJECT_ROOT / "src/Process-Data/Build_Props_Training_Data_v2.py"
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    result = subprocess.run(
        ["venv/bin/python3", str(script)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"Build_Props_Training_Data_v2 failed:\n{result.stderr}"
    training_csv = PROJECT_ROOT / "tmp_data" / "props_training.csv"
    assert training_csv.exists(), "props_training.csv was not created"
    import pandas as pd
    df = pd.read_csv(training_csv)
    assert len(df) > 0, "props_training.csv is empty after rebuild"


def test_flask_app_importable():
    spec = importlib.util.spec_from_file_location("flask_app", str(PROJECT_ROOT / "Flask/app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "app"), "Flask/app.py has no 'app' object"

    from flask import Flask as FlaskClass
    assert isinstance(module.app, FlaskClass)

    assert hasattr(module, "ACTIONS"), "Flask/app.py has no ACTIONS dict"
    expected_keys = {"pull-props", "run-model", "archive-props", "label-last-game", "retrain-model"}
    assert set(module.ACTIONS.keys()) == expected_keys, (
        f"ACTIONS keys mismatch: {set(module.ACTIONS.keys())} != {expected_keys}"
    )


def test_full_props_pipeline(mocker):
    mocker.patch("src.Predict.PlayerProps_Runner.get_rolling_averages", return_value=_MOCK_ROLLING_AVGS)
    mocker.patch("src.Predict.PlayerProps_Runner.get_team_defense",     return_value=_MOCK_TEAM_DEFENSE)
    mocker.patch("src.Predict.PlayerProps_Runner.get_player_game_log",  return_value=_MOCK_GAME_LOG)

    from src.DataProviders.PlayerPropsProvider import parse_props_csv
    from src.Predict.PlayerProps_Runner import props_runner
    from src.Utils.Ranker import rank_bets

    parsed = parse_props_csv(ARCHIVE_CSV)
    assert len(parsed) > 0, "parse_props_csv returned empty dict"

    bets = props_runner(ARCHIVE_CSV)
    assert isinstance(bets, list) and len(bets) > 0, "props_runner returned no bets"

    top_bets = rank_bets(bets, top_n=5)
    assert len(top_bets) > 0, "rank_bets returned empty list"

    scores = [b["weighted_value"] for b in top_bets]
    assert scores == sorted(scores, reverse=True), "rank_bets result is not sorted descending"
