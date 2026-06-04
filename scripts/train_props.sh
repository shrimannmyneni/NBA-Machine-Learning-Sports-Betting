#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/train_props.sh          # normal
#   ./scripts/train_props.sh --debug  # verbose Python output + set -x

DEBUG=0
for arg in "$@"; do
  [[ "$arg" == "--debug" ]] && DEBUG=1
done

[[ $DEBUG -eq 1 ]] && set -x

ts() { echo "[$(date '+%H:%M:%S')] $*"; }

ts "=== train_props.sh start ==="

# ── Step 1: scrape game logs + build training CSV ──────────────────────────
ts "Step 1/3 — Build_Props_Training_Data"
if [[ $DEBUG -eq 1 ]]; then
  python -m src.Process-Data.Build_Props_Training_Data --csv tmp_data/props.csv
else
  python -m src.Process-Data.Build_Props_Training_Data --csv tmp_data/props.csv \
    2>&1 | grep -E '^\[|Processing|→|Wrote|No training'
fi
ts "Step 1 done"

# ── Step 2: train XGBoost props model ─────────────────────────────────────
ts "Step 2/3 — Props_Model training"
if [[ $DEBUG -eq 1 ]]; then
  python -m src.Train-Models.Props_Model
else
  python -m src.Train-Models.Props_Model \
    2>&1 | grep -E 'Loaded|rows|hit rate|Best|Test|Saved'
fi
ts "Step 2 done"

# ── Step 3: run full prediction pipeline ──────────────────────────────────
ts "Step 3/3 — main.py"
python3 main.py -A -odds betmgm -props

ts "=== train_props.sh complete ==="
