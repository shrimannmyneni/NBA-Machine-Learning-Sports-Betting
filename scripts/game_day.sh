#!/usr/bin/env bash
# Full game-day automation in one command.
#
# Usage:
#   ./scripts/game_day.sh                                            # all games tonight, auto source
#   ./scripts/game_day.sh --home "San Antonio Spurs" --away "New York Knicks"
#   ./scripts/game_day.sh --dry-run                                  # stop after props pull
#   ./scripts/game_day.sh --source bettingpros                       # force BettingPros
#   ./scripts/game_day.sh --source oddsapi                           # force The Odds API
#   ./scripts/game_day.sh --source manual                            # skip pull, use existing props.csv
#
# Props source priority (--source auto):
#   1. BettingPros  — no API key required, richer data
#   2. The Odds API — requires ODDS_API_KEY env var
#   3. Manual       — prompts you to place tmp_data/props.csv manually
#
# Optional env vars:
#   ODDS_API_KEY   — required only when falling back to The Odds API
#   ODDS_BOOK      — sportsbook for main.py -odds flag (default: betmgm)

set -euo pipefail

HOME_TEAM=""
AWAY_TEAM=""
DRY_RUN=0
SOURCE="auto"          # auto | bettingpros | oddsapi | manual
ODDS_BOOK="${ODDS_BOOK:-betmgm}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --home)    HOME_TEAM="$2"; shift 2 ;;
    --away)    AWAY_TEAM="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --book)    ODDS_BOOK="$2"; shift 2 ;;
    --source)  SOURCE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

ts() { echo "[$(date '+%H:%M:%S')] $*"; }

# Build shared team args used by both providers
TEAM_ARGS=()
[[ -n "$HOME_TEAM" ]] && TEAM_ARGS+=(--home "$HOME_TEAM")
[[ -n "$AWAY_TEAM" ]] && TEAM_ARGS+=(--away "$AWAY_TEAM")

# Returns 0 (success) if tmp_data/props.csv was written with at least one data row
props_csv_ok() {
    [[ -f "tmp_data/props.csv" ]] && [[ $(wc -l < "tmp_data/props.csv") -gt 1 ]]
}

ts "=== game_day.sh start  [source: $SOURCE] ==="

# ── Step 1: pull props ────────────────────────────────────────────────────────
ts "Step 1/4 — Pull props"
rm -f tmp_data/props.csv

PROPS_SOURCE=""

# ── 1a: BettingPros ──────────────────────────────────────────────────────────
if [[ "$SOURCE" == "auto" || "$SOURCE" == "bettingpros" ]]; then
    ts "  Trying BettingPros..."
    DRY_FLAG=""
    [[ $DRY_RUN -eq 1 ]] && DRY_FLAG="--dry-run"

    if python3 -m src.DataProviders.BettingProsProvider \
        "${TEAM_ARGS[@]}" $DRY_FLAG 2>&1 \
        | grep -E 'prop lines|Wrote|No.*events|dry-run|warn|Error'; then
        props_csv_ok && PROPS_SOURCE="bettingpros"
    fi

    [[ $DRY_RUN -eq 1 ]] && { ts "Dry run complete."; exit 0; }

    if [[ -n "$PROPS_SOURCE" ]]; then
        ts "  BettingPros: OK  (${PROPS_SOURCE})"
    else
        ts "  BettingPros: no data returned"
    fi
fi

# ── 1b: The Odds API fallback ─────────────────────────────────────────────────
if [[ -z "$PROPS_SOURCE" && ( "$SOURCE" == "auto" || "$SOURCE" == "oddsapi" ) ]]; then
    if [[ -z "${ODDS_API_KEY:-}" ]]; then
        ts "  Odds API: skipped (ODDS_API_KEY not set)"
    else
        ts "  Trying The Odds API..."
        DRY_FLAG=""
        [[ $DRY_RUN -eq 1 ]] && DRY_FLAG="--dry-run"

        if python3 -m src.DataProviders.OddsAPIProvider \
            "${TEAM_ARGS[@]}" $DRY_FLAG 2>&1 \
            | grep -E 'prop lines|Wrote|No.*events|dry-run|warn|Error'; then
            props_csv_ok && PROPS_SOURCE="oddsapi"
        fi

        [[ $DRY_RUN -eq 1 ]] && { ts "Dry run complete."; exit 0; }

        if [[ -n "$PROPS_SOURCE" ]]; then
            ts "  Odds API: OK"
        else
            ts "  Odds API: no data returned"
        fi
    fi
fi

# ── 1c: Manual fallback ───────────────────────────────────────────────────────
if [[ -z "$PROPS_SOURCE" && ( "$SOURCE" == "auto" || "$SOURCE" == "manual" ) ]]; then
    if props_csv_ok; then
        ts "  Using existing tmp_data/props.csv"
        PROPS_SOURCE="manual"
    else
        echo ""
        echo "  Both BettingPros and The Odds API returned no data."
        echo "  Manual step required:"
        echo "    1. Format your prop lines as CSV"
        echo "    2. Save to: tmp_data/props.csv"
        echo "    3. Re-run: ./scripts/game_day.sh --source manual"
        echo ""
        exit 1
    fi
fi

if [[ -z "$PROPS_SOURCE" ]]; then
    echo "  No props data available. Exiting."
    exit 1
fi

ts "Step 1 done  [source: $PROPS_SOURCE]"

# ── Step 2: archive props ─────────────────────────────────────────────────────
ts "Step 2/4 — Archive props"
./scripts/archive_props.sh --date "$(date '+%Y-%m-%d')"
ts "Step 2 done"

# ── Step 3: train props model ─────────────────────────────────────────────────
ts "Step 3/4 — Train props model"
python -m src.Train-Models.Props_Model \
  2>&1 | grep -E 'rows|hit rate|Best|Test accuracy|Saved|No training'
ts "Step 3 done"

# ── Step 4: run predictions ───────────────────────────────────────────────────
ts "Step 4/4 — Run predictions"
python3 main.py -A -odds "$ODDS_BOOK" -props
ts "Step 4 done"

ts "=== game_day.sh complete ==="
ts "After the game: ./scripts/label_last_game.sh"
