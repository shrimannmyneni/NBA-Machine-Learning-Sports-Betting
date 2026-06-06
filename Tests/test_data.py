from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
REQUIRED_PROPS_COLS = {"Player", "Team", "Opponent", "PropType", "Line", "Odds", "Direction", "Sportsbook"}


# ── Archive (June 3rd) ────────────────────────────────────────────────────────

def test_archive_has_hit_column(archive_csv):
    assert "Hit" in archive_csv.columns


def test_archive_hit_rate_reasonable(archive_csv):
    labeled = archive_csv.dropna(subset=["Hit"])
    hit_rate = labeled["Hit"].mean()
    assert 0.35 <= hit_rate <= 0.65, f"Hit rate {hit_rate:.2%} outside expected 35–65% band"


def test_archive_no_empty_lines(archive_csv):
    assert archive_csv["Line"].notna().all(), "Null values found in Line column"


def test_archive_no_empty_odds(archive_csv):
    assert archive_csv["Odds"].notna().all(), "Null values found in Odds column"


# ── tmp_data/props.csv ────────────────────────────────────────────────────────

def test_props_csv_has_required_columns(props_csv):
    missing = REQUIRED_PROPS_COLS - set(props_csv.columns)
    assert not missing, f"props.csv missing columns: {missing}"


def test_props_csv_has_rows(props_csv):
    assert len(props_csv) >= 1


# ── tmp_data/props_training.csv ───────────────────────────────────────────────

def test_training_csv_exists():
    training_csv = PROJECT_ROOT / "tmp_data" / "props_training.csv"
    assert training_csv.exists(), "tmp_data/props_training.csv not found — run Build_Props_Training_Data_v2"


def test_training_csv_hit_rate():
    training_csv = PROJECT_ROOT / "tmp_data" / "props_training.csv"
    if not training_csv.exists():
        pytest.skip("props_training.csv not present")
    df = pd.read_csv(training_csv)
    hit_rate = df["hit"].mean()
    assert 0.35 <= hit_rate <= 0.65, f"Training hit rate {hit_rate:.2%} outside expected 35–65% band"


# ── All archives labeled ──────────────────────────────────────────────────────

def test_all_archives_labeled():
    archive_dir = PROJECT_ROOT / "Data" / "prop_archives"
    unlabeled = []
    for csv_path in sorted(archive_dir.glob("*.csv")):
        df = pd.read_csv(csv_path)
        if "Hit" not in df.columns:
            continue
        if df["Hit"].notna().sum() == 0:
            unlabeled.append(csv_path.name)
    assert not unlabeled, f"Archives with Hit column but no labeled rows: {unlabeled}"
