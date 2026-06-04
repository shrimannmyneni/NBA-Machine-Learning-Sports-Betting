#!/usr/bin/env bash
# Labels the most recently archived props CSV with actual game outcomes.
# Scrapes the BRef box score and writes Actual + Hit columns in place.
#
# Usage:
#   ./scripts/label_last_game.sh                              # most recent archive
#   ./scripts/label_last_game.sh --file data/prop_archives/2026-06-03_New_York_Knicks_vs_San_Antonio_Spurs.csv
#   ./scripts/label_last_game.sh --force                      # re-scrape even if cached

set -euo pipefail

ARCHIVE_DIR="data/prop_archives"
TARGET=""
FORCE_FLAG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --file)  TARGET="$2"; shift 2 ;;
    --force) FORCE_FLAG="--force-refresh"; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  # Pick the most recently dated archive (filenames sort chronologically).
  TARGET=$(ls "$ARCHIVE_DIR"/*.csv 2>/dev/null | sort | tail -1)
  if [[ -z "$TARGET" ]]; then
    echo "No archives found in $ARCHIVE_DIR. Run ./scripts/archive_props.sh first."
    exit 1
  fi
fi

if [[ ! -f "$TARGET" ]]; then
  echo "File not found: $TARGET"
  exit 1
fi

echo "[$(date '+%H:%M:%S')] Labeling: $TARGET"
python3 - "$TARGET" $FORCE_FLAG <<'PYEOF'
import sys
from src.DataProviders.PropOutcomeFetcher import label_archive_csv

force = "--force-refresh" in sys.argv
path  = next(a for a in sys.argv[1:] if not a.startswith("--"))
label_archive_csv(path, force_refresh=force)
PYEOF
echo "[$(date '+%H:%M:%S')] Done. Commit the labeled archive when ready:"
echo "  git add $TARGET && git commit -m 'Label outcomes: $(basename $TARGET .csv)'"
