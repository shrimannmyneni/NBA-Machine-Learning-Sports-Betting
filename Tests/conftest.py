from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ARCHIVE_CSV = PROJECT_ROOT / "Data/prop_archives/2026-06-03_New_York_Knicks_vs_San_Antonio_Spurs.csv"


@pytest.fixture(scope="session")
def archive_csv():
    return pd.read_csv(ARCHIVE_CSV)


@pytest.fixture
def props_csv():
    path = PROJECT_ROOT / "tmp_data/props.csv"
    if not path.exists():
        pytest.skip("tmp_data/props.csv not present — pull props first")
    return pd.read_csv(path)


@pytest.fixture
def sample_bets():
    return [
        {"team_or_player": "Victor Wembanyama", "event": "OVER 27.5 Points", "odds": -115, "ev":  5.0, "kelly": 3.0, "confidence": 0.60},
        {"team_or_player": "Jalen Brunson",     "event": "OVER 25.5 Points", "odds": -110, "ev":  3.0, "kelly": 2.0, "confidence": 0.55},
        {"team_or_player": "Josh Hart",         "event": "OVER 11.5 Points", "odds": -105, "ev":  1.0, "kelly": 1.0, "confidence": 0.52},
        {"team_or_player": "De'Aaron Fox",      "event": "OVER 15.5 Points", "odds": -115, "ev": -2.0, "kelly": 0.0, "confidence": 0.45},
        {"team_or_player": "Mikal Bridges",     "event": "OVER 15.5 Points", "odds": -115, "ev": -5.0, "kelly": 0.0, "confidence": 0.40},
    ]
