"""
Builds tmp_data/props_training.csv from labeled prop archive CSVs.

Improvements over Build_Props_Training_Data.py (v1):
  - Uses the actual historical line from each archive, not tonight's fixed line
  - Uses actual game outcomes (Hit column) instead of back-applying tonight's line
  - Rolling features use games strictly BEFORE each archive date — no look-ahead bias

After each game:
  1. ./scripts/archive_props.sh     (already done before the game)
  2. ./scripts/label_last_game.sh   (runs PropOutcomeFetcher, writes Actual + Hit)
  3. python -m src.Process-Data.Build_Props_Training_Data_v2
  4. python -m src.Train-Models.Props_Model

Usage:
    python -m src.Process-Data.Build_Props_Training_Data_v2
    python -m src.Process-Data.Build_Props_Training_Data_v2 --archives data/prop_archives
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path

from src.DataProviders.BRefDefenseProvider import get_team_defense
from src.DataProviders.BRefPlayerStatsProvider import get_player_game_log

ARCHIVE_DIR = Path(__file__).resolve().parents[2] / "Data" / "prop_archives"
TMP_DIR     = Path(__file__).resolve().parents[2] / "tmp_data"
OUTPUT_CSV  = TMP_DIR / "props_training.csv"

PROP_TO_STAT = {
    "Points":     "pts",
    "Rebounds":   "trb",
    "Assists":    "ast",
    "3-Pointers": "fg3",
}
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


def _season_year(date_str):
    """BRef season end-year for a date. Oct–Dec of year N → season N+1."""
    year, month = int(date_str[:4]), int(date_str[5:7])
    return year + 1 if month >= 10 else year


def _rolling_before(game_log, before_date, stat_col, last_n=10, min_games=5):
    """
    Rolling avg and std of stat_col using the last N games strictly before before_date.
    Returns (None, None) if fewer than min_games are available.
    """
    prior  = [g for g in game_log if g["date"] < before_date]
    window = prior[-last_n:]
    if len(window) < min_games:
        return None, None
    vals = [g[stat_col] for g in window if g.get(stat_col) is not None]
    if not vals:
        return None, None
    avg = sum(vals) / len(vals)
    std = (sum((v - avg) ** 2 for v in vals) / max(len(vals) - 1, 1)) ** 0.5
    return round(avg, 3), round(std, 3)


def _days_rest_before(game_log, game_date_str):
    """Days between the player's last game before game_date_str and game_date_str."""
    prior = [g for g in game_log if g["date"] < game_date_str]
    if not prior:
        return 3
    last_dt   = datetime.strptime(prior[-1]["date"], "%Y-%m-%d").date()
    target_dt = datetime.strptime(game_date_str, "%Y-%m-%d").date()
    return min((target_dt - last_dt).days, 7)


def load_labeled_archives(archive_dir):
    """
    Reads all archive CSVs that have a populated Hit column.

    Deduplicates by (player, prop_type, game_date): for each unique prop-game
    combination we keep only the first row seen and convert Hit to the P(OVER)
    model target regardless of bet direction:
        OVER row: model_target = Hit          (Hit=1 means OVER won = OVER hit)
        UNDER row: model_target = 1 − Hit     (Hit=1 means UNDER won = OVER missed)
    """
    seen     = set()
    all_rows = []

    for csv_path in sorted(Path(archive_dir).glob("*.csv")):
        date_str = csv_path.stem[:10]
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                if "Hit" not in (reader.fieldnames or []):
                    print(f"  [skip] {csv_path.name} — not yet labeled (run label_last_game.sh)")
                    continue
                n = 0
                for row in reader:
                    hit_raw = row.get("Hit", "").strip()
                    if hit_raw == "":
                        continue  # player not found in box score

                    player    = row["Player"].strip()
                    prop_type = row["PropType"].strip()
                    direction = row.get("Direction", "OVER").strip().upper()
                    key       = (player, prop_type, date_str)

                    if key in seen:
                        continue  # already have a row for this prop-game
                    seen.add(key)

                    archive_hit  = int(hit_raw)
                    model_target = archive_hit if direction == "OVER" else (1 - archive_hit)

                    all_rows.append({
                        "player":    player,
                        "prop_type": prop_type,
                        "game_date": date_str,
                        "opponent":  row["Opponent"].strip(),
                        "line":      float(row["Line"]),
                        "actual":    float(row.get("Actual") or 0),
                        "hit":       model_target,
                    })
                    n += 1
                print(f"  {csv_path.name}: {n} props loaded")
        except Exception as exc:
            print(f"  [error] {csv_path.name}: {exc}")

    return all_rows


def build_feature_rows(archive_rows, defense_cache, game_log_cache):
    """
    Attaches rolling player stats and opponent defense features to each archive row.
    Skips rows with insufficient prior games or unknown players.
    """
    out = []

    for row in archive_rows:
        player    = row["player"]
        prop_type = row["prop_type"]
        game_date = row["game_date"]
        opponent  = row["opponent"]
        line      = row["line"]

        stat_col = PROP_TO_STAT.get(prop_type)
        def_col  = PROP_TO_DEF.get(prop_type)
        if not stat_col:
            continue

        # Game log cached in memory — one BRef fetch (or cache read) per player.
        if player not in game_log_cache:
            year = _season_year(game_date)
            game_log_cache[player] = get_player_game_log(player, year=year)

        game_log = game_log_cache[player]
        if not game_log:
            continue

        stat_avg, stat_std = _rolling_before(game_log, game_date, stat_col)
        if stat_avg is None:
            continue  # fewer than 5 games before this date

        year      = _season_year(game_date)
        cache_key = (opponent, year)
        if cache_key not in defense_cache:
            try:
                defense_cache[cache_key] = get_team_defense(opponent, year=year)
            except Exception as exc:
                print(f"  [warn] defense fetch failed for {opponent}: {exc}")
                defense_cache[cache_key] = {}

        opp_def_stat  = defense_cache[cache_key].get(def_col)
        line_over_avg = round(line / stat_avg, 3) if stat_avg > 0 else 1.0
        rest          = _days_rest_before(game_log, game_date)

        out.append({
            "player":        player,
            "prop_type":     prop_type,
            "game_date":     game_date,
            "opponent":      opponent,
            "home":          0,  # unknown from archive; future improvement
            "days_rest":     rest,
            "stat_avg":      stat_avg,
            "stat_std":      stat_std if stat_std is not None else 0.0,
            "line":          line,
            "line_over_avg": line_over_avg,
            "opp_def_stat":  round(opp_def_stat, 3) if opp_def_stat is not None else None,
            "actual_stat":   row["actual"],
            "hit":           row["hit"],
        })

    return out


def main():
    parser = argparse.ArgumentParser(
        description="Build props_training.csv from labeled game archives."
    )
    parser.add_argument("--archives", default=str(ARCHIVE_DIR),
                        help="Directory containing labeled archive CSVs")
    args = parser.parse_args()

    TMP_DIR.mkdir(exist_ok=True)

    print(f"Loading labeled archives from {args.archives} ...")
    archive_rows = load_labeled_archives(args.archives)
    print(f"  Total labeled props: {len(archive_rows)}")

    if not archive_rows:
        print("\nNo labeled data yet. After each game run:")
        print("  ./scripts/label_last_game.sh")
        return

    print("\nBuilding features ...")
    defense_cache  = {}
    game_log_cache = {}
    feature_rows   = build_feature_rows(archive_rows, defense_cache, game_log_cache)
    print(f"  Feature rows: {len(feature_rows)}")

    if not feature_rows:
        print("No feature rows generated. Check player IDs.")
        return

    hits = sum(1 for r in feature_rows if r["hit"] == 1)
    print(f"  Hit rate (P(OVER)): {hits/len(feature_rows)*100:.1f}%  ({hits}/{len(feature_rows)})")

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(feature_rows)

    print(f"\nWrote {len(feature_rows)} rows → {OUTPUT_CSV}")
    print("Next: python -m src.Train-Models.Props_Model")


if __name__ == "__main__":
    main()