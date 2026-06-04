#!/usr/bin/env bash
# Full game-day automation in one command.
#
# Usage:
#   ./scripts/game_day.sh                                            # all games tonight
#   ./scripts/game_day.sh --home "San Antonio Spurs" --away "New York Knicks"
#   ./scripts/game_day.sh --dry-run                                  # stop after props pull
#
# Optional env vars:
#   ODDS_API_KEY   — required for props pull (set before running)
#   ODDS_BOOK      — sportsbook for main.py -odds flag (default: betmgm)

set -euo pipefail

HOME_TEAM=""
AWAY_TEAM=""
DRY_RUN=0
ODDS_BOOK="${ODDS_BOOK:-betmgm}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --home)    HOME_TEAM="$2"; shift 2 ;;
    --away)    AWAY_TEAM="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --book)    ODDS_BOOK="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

ts() { echo "[$(date '+%H:%M:%S')] $*"; }

ts "=== game_day.sh start ==="

# ── Step 1: pull props ─────────────────────────────────────────────────────
ts "Step 1/4 — Pull props (The Odds API)"

if [[ -z "${ODDS_API_KEY:-}" ]]; then
  echo "  Error: ODDS_API_KEY is not set. Export it and re-run."
  exit 1
fi

PULL_ARGS=()
[[ -n "$HOME_TEAM" ]] && PULL_ARGS+=(--home "$HOME_TEAM")
[[ -n "$AWAY_TEAM" ]] && PULL_ARGS+=(--away "$AWAY_TEAM")
[[ $DRY_RUN -eq 1 ]] && PULL_ARGS+=(--dry-run)

python3 -m src.DataProviders.OddsAPIProvider "${PULL_ARGS[@]}"

[[ $DRY_RUN -eq 1 ]] && { ts "Dry run complete — stopping before archive/model steps."; exit 0; }

ts "Step 1 done"

# ── Step 2: archive props ──────────────────────────────────────────────────
ts "Step 2/4 — Archive props"

ARCHIVE_ARGS=()
# Pass today's date explicitly so the archive name is always correct.
ARCHIVE_ARGS+=(--date "$(date '+%Y-%m-%d')")

./scripts/archive_props.sh "${ARCHIVE_ARGS[@]}"
ts "Step 2 done"

# ── Step 3: train props model ──────────────────────────────────────────────
ts "Step 3/4 — Train props model"
python -m src.Train-Models.Props_Model \
  2>&1 | grep -E 'rows|hit rate|Best|Test accuracy|Saved|No training'
ts "Step 3 done"

# ── Step 4: run predictions ────────────────────────────────────────────────
ts "Step 4/4 — Run predictions"
python3 main.py -A -odds "$ODDS_BOOK" -props
ts "Step 4 done"

ts "=== game_day.sh complete ==="
ts "After the game: ./scripts/label_last_game.sh"
