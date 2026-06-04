#!/usr/bin/env bash
# Archives tmp_data/props.csv with date + matchup in the filename.
# Run this before each game after pulling lines.
#
# Usage:
#   ./scripts/archive_props.sh                    # today's date
#   ./scripts/archive_props.sh --date 2026-06-03  # backfill a specific date

set -euo pipefail

DATE=$(date +%Y-%m-%d)
PROPS="tmp_data/props.csv"

while [[ $# -gt 0 ]]; do
  case $1 in
    --date) DATE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ ! -f "$PROPS" ]]; then
  echo "Error: $PROPS not found. Prepare the props CSV first."
  exit 1
fi

# Extract sorted team names from CSV and build a filename slug.
SLUG=$(python3 - "$PROPS" <<'PYEOF'
import csv, sys

teams = set()
with open(sys.argv[1]) as f:
    for row in csv.DictReader(f):
        teams.add(row["Team"].strip())

teams = sorted(teams)
print("_vs_".join(t.replace(" ", "_") for t in teams))
PYEOF
)

ARCHIVE_DIR="Data/prop_archives"
mkdir -p "$ARCHIVE_DIR"

DEST="${ARCHIVE_DIR}/${DATE}_${SLUG}.csv"

if [[ -f "$DEST" ]]; then
  echo "Already archived: $DEST"
  echo "Remove it first if you want to overwrite, or use --date to pick a different date."
  exit 0
fi

cp "$PROPS" "$DEST"
echo "Archived → $DEST"
echo "After the game: ./scripts/label_last_game.sh"
