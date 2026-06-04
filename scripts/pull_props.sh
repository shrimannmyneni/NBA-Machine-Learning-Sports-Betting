#!/usr/bin/env bash
# Pulls tonight's NBA player prop lines from The Odds API → tmp_data/props.csv
#
# Usage:
#   ./scripts/pull_props.sh                                          # all games tonight
#   ./scripts/pull_props.sh --home "San Antonio Spurs" --away "New York Knicks"
#   ./scripts/pull_props.sh --dry-run                               # list games, no props pull
#   ./scripts/pull_props.sh --books betmgm draftkings               # specific books only

set -euo pipefail

if [[ -z "${ODDS_API_KEY:-}" ]]; then
  echo "Error: ODDS_API_KEY is not set."
  echo "  export ODDS_API_KEY=your_key_here"
  exit 1
fi

echo "[$(date '+%H:%M:%S')] Pulling props from The Odds API ..."
python3 -m src.DataProviders.OddsAPIProvider "$@"
echo "[$(date '+%H:%M:%S')] Done."
