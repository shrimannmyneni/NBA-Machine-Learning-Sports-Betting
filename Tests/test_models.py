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


# ── Model file existence ──────────────────────────────────────────────────────

def test_xgboost_model_exists():
    xgb_dir = PROJECT_ROOT / "Models" / "XGBoost_Models"
    assert xgb_dir.exists(), "Models/XGBoost_Models/ not found"
    json_files = list(xgb_dir.glob("*.json"))
    assert json_files, f"No .json model files in {xgb_dir}"


def test_nn_model_exists():
    nn_dir = PROJECT_ROOT / "Models" / "NN_Models"
    if not nn_dir.exists():
        pytest.skip("Models/NN_Models/ directory not present")
    keras_files = list(nn_dir.glob("*.keras")) + list(nn_dir.glob("*.h5"))
    assert keras_files, f"No .keras or .h5 files found in {nn_dir}"


def test_props_model_exists():
    models_dir = PROJECT_ROOT / "Models" / "Props_Models"
    assert models_dir.exists(), "Models/Props_Models/ not found"
    all_files = list(models_dir.glob("Props_53.9pct*.json"))
    meta_files = [f for f in all_files if "_meta" in f.name]
    model_files = [f for f in all_files if "_meta" not in f.name]
    assert model_files, "Props_53.9pct model .json not found in Models/Props_Models/"
    assert meta_files, "Props_53.9pct _meta.json not found in Models/Props_Models/"


# ── props_runner output shape ─────────────────────────────────────────────────

def test_props_runner_output_shape(mocker):
    mocker.patch("src.Predict.PlayerProps_Runner.get_rolling_averages", return_value=_MOCK_ROLLING_AVGS)
    mocker.patch("src.Predict.PlayerProps_Runner.get_team_defense",     return_value=_MOCK_TEAM_DEFENSE)
    mocker.patch("src.Predict.PlayerProps_Runner.get_player_game_log",  return_value=_MOCK_GAME_LOG)

    from src.Predict.PlayerProps_Runner import props_runner

    result = props_runner(ARCHIVE_CSV)

    assert isinstance(result, list)
    assert len(result) > 0
    required_keys = {"team_or_player", "event", "odds", "ev", "kelly", "confidence"}
    for bet in result:
        missing = required_keys - set(bet.keys())
        assert not missing, f"Bet dict missing keys: {missing} — got {list(bet.keys())}"


def test_props_runner_no_crash_empty_csv(tmp_path, mocker):
    mocker.patch("src.Predict.PlayerProps_Runner.get_rolling_averages", return_value=_MOCK_ROLLING_AVGS)
    mocker.patch("src.Predict.PlayerProps_Runner.get_team_defense",     return_value=_MOCK_TEAM_DEFENSE)
    mocker.patch("src.Predict.PlayerProps_Runner.get_player_game_log",  return_value=_MOCK_GAME_LOG)

    from src.Predict.PlayerProps_Runner import props_runner

    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("Player,Team,Opponent,PropType,Line,Odds,Sportsbook,Direction\n")
    result = props_runner(empty_csv)
    assert result == []
