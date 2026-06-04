"""
Builds props_dataset.sqlite from:
  - A formatted props CSV (Player, Team, Opponent, PropType, Line, Odds,
    Sportsbook, [Direction], [ModelProb])
  - Basketball Reference opponent defensive stats per team  (def_* columns)
  - Basketball Reference player rolling stats               (player_* columns)

The output table is stored in Data/props_dataset.sqlite and is completely
separate from dataset.sqlite — the team-level pipeline is not touched.

Usage (run from project root):
    python -m src.Process-Data.Create_PlayerProps_Games \\
        --csv tmp_data/props.csv \\
        --year 2026 \\
        --table props_2025_26

Flags:
    --no-defense        skip BRef team defensive stats
    --no-player-stats   skip BRef player rolling stats
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from src.DataProviders.BRefDefenseProvider import get_defense_for_teams
from src.DataProviders.BRefPlayerStatsProvider import PLAYER_TO_BREF_ID, get_rolling_averages
from src.DataProviders.PlayerPropsProvider import parse_props_csv

DATA_DIR = Path(__file__).resolve().parents[2] / "Data"
DB_PATH = DATA_DIR / "props_dataset.sqlite"


def props_to_dataframe(props_dict):
    """Converts the dict returned by parse_props_csv into a flat DataFrame."""
    rows = []
    for key, meta in props_dict.items():
        rows.append({
            "prop_key": key,
            "player": meta["player"],
            "team": meta["team"],
            "opponent": meta["opponent"],
            "prop_type": meta["prop"],
            "direction": meta["direction"],
            "line": meta["line"],
            "odds": meta["odds"],
            "sportsbook": meta["sportsbook"],
            "model_prob": meta.get("model_prob"),
        })
    return pd.DataFrame(rows)


def merge_defense_features(df, year):
    """
    Fetches BRef defensive stats for each unique opponent and joins them onto df.
    New columns are prefixed with 'def_' to avoid collisions.
    """
    opponents = df["opponent"].unique().tolist()
    defense_map = get_defense_for_teams(opponents, year=year)

    defense_rows = []
    for team_name, stats in defense_map.items():
        row = {"opponent": team_name}
        for stat, value in stats.items():
            row[f"def_{stat}"] = value
        defense_rows.append(row)

    if not defense_rows:
        return df

    defense_df = pd.DataFrame(defense_rows)
    return df.merge(defense_df, on="opponent", how="left")


def merge_player_stats_features(df, year):
    """
    Fetches BRef rolling stats for each unique player and joins them onto df.
    New columns are prefixed with 'player_' to avoid collisions with 'def_' columns.
    Players not in PLAYER_TO_BREF_ID are skipped with a warning; their columns are NaN.
    """
    players = df["player"].unique().tolist()
    stats_rows = []

    for player in players:
        if player not in PLAYER_TO_BREF_ID:
            print(f"[PlayerStats] {player} not in PLAYER_TO_BREF_ID — skipping")
            continue
        try:
            rolling = get_rolling_averages(player, year=year)
            if rolling:
                row = {"player": player}
                for stat, value in rolling.items():
                    row[f"player_{stat}"] = value
                stats_rows.append(row)
        except Exception as exc:
            print(f"[PlayerStats] Failed to fetch {player}: {exc}")

    if not stats_rows:
        return df

    stats_df = pd.DataFrame(stats_rows)
    return df.merge(stats_df, on="player", how="left")


def write_to_sqlite(df, table_name):
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    conn.close()
    print(f"Wrote {len(df)} rows to {DB_PATH} (table: {table_name})")


def main():
    parser = argparse.ArgumentParser(description="Build props_dataset.sqlite")
    parser.add_argument("--csv", required=True, help="Path to the formatted props CSV")
    parser.add_argument("--year", type=int, default=2026, help="Season end year for BRef")
    parser.add_argument("--table", default="props_2025_26", help="SQLite table name")
    parser.add_argument(
        "--no-defense",
        action="store_true",
        help="Skip BRef team defensive stats fetch",
    )
    parser.add_argument(
        "--no-player-stats",
        action="store_true",
        help="Skip BRef player rolling stats fetch",
    )
    args = parser.parse_args()

    props = parse_props_csv(args.csv)
    if not props:
        print("No props found in CSV. Check the file format.")
        return

    df = props_to_dataframe(props)

    if not args.no_defense:
        df = merge_defense_features(df, year=args.year)

    if not args.no_player_stats:
        df = merge_player_stats_features(df, year=args.year)

    write_to_sqlite(df, args.table)


if __name__ == "__main__":
    main()
