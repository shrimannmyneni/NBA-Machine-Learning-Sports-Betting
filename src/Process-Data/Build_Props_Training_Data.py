"""
Builds tmp_data/props_training.csv for Props_Model.py.

For each (player, prop_type) in the props CSV, scrapes the player's full
season game log and generates one training row per historical game (after a
10-game warm-up window). The target Hit = 1 if the player exceeded the line
that night, 0 if not.

Tonight's line is used as the threshold for all historical games. This is an
approximation — actual book lines moved throughout the season — but it teaches
the model "does this player typically beat THIS specific line against THIS
defensive profile," which is the prediction we actually want tonight.

Usage:
    python -m src.Process-Data.Build_Props_Training_Data \\
        --csv tmp_data/props.csv --year 2026
"""

import argparse
import csv
from pathlib import Path

import pandas as pd

from src.DataProviders.BRefDefenseProvider import get_team_defense
from src.DataProviders.BRefPlayerStatsProvider import PLAYER_TO_BREF_ID, get_player_game_log

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp_data"
OUTPUT_CSV = TMP_DIR / "props_training.csv"

PROP_TO_STAT = {
    "Points":     "pts",
    "Rebounds":   "trb",
    "Assists":    "ast",
    "3-Pointers": "fg3",
}

# Defensive stat keys produced by BRefDefenseProvider for each prop type.
PROP_TO_DEF = {
    "Points":     "opp_pts",
    "Rebounds":   "opp_trb",
    "Assists":    "opp_ast",
    "3-Pointers": "opp_3p",
}

OUTPUT_COLUMNS = [
    "player", "prop_type", "game_date", "opponent",
    "home", "days_rest",
    "stat_avg", "stat_std", "line", "line_over_avg",
    "opp_def_stat",
    "actual_stat", "hit",
]


def load_prop_lines(csv_path):
    """
    Extracts one (player, prop_type, line) entry per unique combination.
    OVER and UNDER share the same line, so we deduplicate and keep the first row.
    """
    seen = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            player = row["Player"].strip()
            prop_type = row["PropType"].strip()
            key = (player, prop_type)
            if key not in seen:
                seen[key] = {
                    "player":    player,
                    "prop_type": prop_type,
                    "line":      float(row["Line"]),
                }
    return list(seen.values())


def build_rows_for_prop(prop_meta, year, defense_cache):
    """
    Generates training rows for one (player, prop_type, line) combination.
    Returns a list of dicts with features and the Hit target.
    """
    player    = prop_meta["player"]
    prop_type = prop_meta["prop_type"]
    line      = prop_meta["line"]

    stat_col = PROP_TO_STAT.get(prop_type)
    def_col  = PROP_TO_DEF.get(prop_type)
    if stat_col is None:
        print(f"  [skip] Unknown prop type '{prop_type}' for {player}")
        return []

    if player not in PLAYER_TO_BREF_ID:
        print(f"  [skip] {player} not in PLAYER_TO_BREF_ID — add to BRefPlayerStatsProvider.py")
        return []

    try:
        raw_games = get_player_game_log(player, year=year)
    except Exception as exc:
        print(f"  [skip] {player}: {exc}")
        return []

    if len(raw_games) < 11:
        print(f"  [skip] {player} — only {len(raw_games)} games, need ≥11 for rolling window")
        return []

    df = pd.DataFrame(raw_games)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    # shift(1) ensures rolling stats are computed from games BEFORE the target game.
    df["stat_avg"] = df[stat_col].shift(1).rolling(10, min_periods=5).mean()
    df["stat_std"] = (
        df[stat_col].shift(1).rolling(10, min_periods=5).std().fillna(0.0)
    )
    df["days_rest"] = df["date"].diff().dt.days.clip(upper=7).fillna(2).astype(int)
    df["hit"] = (df[stat_col] > line).astype(int)

    df = df.dropna(subset=["stat_avg"]).reset_index(drop=True)
    if df.empty:
        return []

    rows = []
    for _, row in df.iterrows():
        opp_abbr = row["opp"]

        if opp_abbr not in defense_cache:
            try:
                defense_cache[opp_abbr] = get_team_defense(opp_abbr, year=year)
            except Exception as exc:
                print(f"  [warn] Defense fetch failed for {opp_abbr}: {exc}")
                defense_cache[opp_abbr] = {}

        def_stat  = defense_cache[opp_abbr].get(def_col)
        stat_avg  = float(row["stat_avg"])
        line_over = round(line / stat_avg, 3) if stat_avg > 0 else None

        rows.append({
            "player":        player,
            "prop_type":     prop_type,
            "game_date":     row["date"].strftime("%Y-%m-%d"),
            "opponent":      opp_abbr,
            "home":          int(row["home"]),
            "days_rest":     int(row["days_rest"]),
            "stat_avg":      round(stat_avg, 3),
            "stat_std":      round(float(row["stat_std"]), 3),
            "line":          line,
            "line_over_avg": line_over,
            "opp_def_stat":  round(def_stat, 3) if def_stat is not None else None,
            "actual_stat":   row[stat_col],
            "hit":           int(row["hit"]),
        })

    return rows


def main():
    parser = argparse.ArgumentParser(description="Build props_training.csv")
    parser.add_argument("--csv", default="tmp_data/props.csv")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-scrape even if BRef cache exists")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)

    prop_lines = load_prop_lines(args.csv)
    print(f"Found {len(prop_lines)} unique (player, prop_type) combinations.\n")

    defense_cache = {}
    all_rows = []

    for meta in prop_lines:
        print(f"Processing  {meta['player']} — {meta['prop_type']} (line: {meta['line']})")
        rows = build_rows_for_prop(meta, year=args.year, defense_cache=defense_cache)
        print(f"  → {len(rows)} training rows")
        all_rows.extend(rows)

    if not all_rows:
        print("\nNo training rows generated. Check player IDs and game log availability.")
        return

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows → {OUTPUT_CSV}")
    print("Next step: python -m src.Train-Models.Props_Model")


if __name__ == "__main__":
    main()
