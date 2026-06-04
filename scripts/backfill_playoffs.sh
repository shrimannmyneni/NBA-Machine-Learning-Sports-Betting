#!/usr/bin/env bash
# Backfills 2026 NBA playoff prop data into Data/prop_archives/.
#
# For each played game:
#   1. Pull prop lines from BettingPros (cached after first fetch)
#   2. Archive to Data/prop_archives/
#   3. Label with actual outcomes from Basketball Reference box scores
#
# Usage:
#   ./scripts/backfill_playoffs.sh
#   ./scripts/backfill_playoffs.sh --force    # re-process already-labeled games

set -euo pipefail

ARCHIVE_DIR="Data/prop_archives"
FORCE=0

for arg in "$@"; do
  [[ "$arg" == "--force" ]] && FORCE=1
done

ts() { echo "[$(date '+%H:%M:%S')] $*"; }

ts "=== backfill_playoffs.sh start ==="

# ── Step 1: Discover all played 2026 playoff games from BRef ────────────────
ts "Fetching 2026 NBA playoff schedule from Basketball Reference..."

GAME_LIST=$(python3 - <<'PYEOF'
import requests, re, sys, time
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# BRef uses full names; map any that differ from our TEAM_TO_BREF keys.
NAME_FIX = {"Los Angeles Clippers": "LA Clippers"}

url = "https://www.basketball-reference.com/playoffs/NBA_2026_games.html"
time.sleep(4)
r = requests.get(url, headers=HEADERS, timeout=20)

if r.status_code != 200:
    print(f"# BRef returned {r.status_code}", file=sys.stderr)
    sys.exit(0)

soup   = BeautifulSoup(r.text, "html.parser")
tables = soup.find_all("table")

# BRef sometimes wraps tables in HTML comments
if not tables:
    for c in re.compile(r"<!--(.*?)-->", re.DOTALL).findall(r.text):
        if "<table" in c:
            tables.extend(BeautifulSoup(c, "html.parser").find_all("table"))

games = []
seen  = set()

for table in tables:
    for row in table.select("tbody tr"):
        if "thead" in row.get("class", []):
            continue

        date_cell    = row.find(["td","th"], {"data-stat": "date_game"})
        visitor_cell = row.find(["td","th"], {"data-stat": "visitor_team_name"})
        home_cell    = row.find(["td","th"], {"data-stat": "home_team_name"})
        home_pts     = row.find(["td","th"], {"data-stat": "home_pts"})

        if not all([date_cell, visitor_cell, home_cell]):
            continue

        # Only include completed games (pts column is numeric)
        pts = (home_pts.get_text(strip=True) if home_pts else "")
        if not pts.isdigit():
            continue

        date_link = date_cell.find("a")
        if not date_link:
            continue

        m = re.search(r"/(\d{4})(\d{2})(\d{2})", date_link.get("href", ""))
        if not m:
            continue

        date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        home     = NAME_FIX.get(home_cell.get_text(strip=True),  home_cell.get_text(strip=True))
        away     = NAME_FIX.get(visitor_cell.get_text(strip=True), visitor_cell.get_text(strip=True))
        key      = f"{date_str}|{home}|{away}"

        if key not in seen and home and away:
            seen.add(key)
            games.append(key)

for g in games:
    print(g)
PYEOF
)

# Fall back to the one confirmed game if BRef page isn't available yet
if [[ -z "$GAME_LIST" ]]; then
    ts "BRef schedule page unavailable — using known games as fallback"
    GAME_LIST="2026-06-03|San Antonio Spurs|New York Knicks"
fi

TOTAL=$(echo "$GAME_LIST" | grep -c '|' 2>/dev/null || echo 0)
ts "Found $TOTAL game(s) to process"
echo ""

DONE=0
SKIPPED=0
ERRORS=0
GAME_NUM=0

# ── Step 2: Process each game ────────────────────────────────────────────────
while IFS='|' read -r DATE HOME_TEAM AWAY_TEAM; do
    [[ -z "$DATE" ]] && continue
    GAME_NUM=$((GAME_NUM + 1))

    # Expected archive filename (team names sorted alphabetically)
    SLUG=$(python3 -c "
teams = sorted(['${HOME_TEAM}', '${AWAY_TEAM}'])
print('_vs_'.join(t.replace(' ', '_') for t in teams))
")
    ARCHIVE_FILE="${ARCHIVE_DIR}/${DATE}_${SLUG}.csv"

    # Skip if already fully labeled (and not forcing)
    if [[ -f "$ARCHIVE_FILE" && $FORCE -eq 0 ]]; then
        LABELED=$(python3 -c "
import csv
try:
    rows = list(csv.DictReader(open('${ARCHIVE_FILE}')))
    print(sum(1 for r in rows if r.get('Hit','').strip() != ''))
except:
    print(0)
")
        if [[ "$LABELED" -gt 0 ]]; then
            echo "  [$GAME_NUM/$TOTAL] SKIP  $DATE  $AWAY_TEAM @ $HOME_TEAM  ($LABELED props labeled)"
            SKIPPED=$((SKIPPED + 1))
            continue
        fi
    fi

    ts "[$GAME_NUM/$TOTAL] $DATE — $AWAY_TEAM @ $HOME_TEAM"

    # ── 2a: Pull props from BettingPros ─────────────────────────────────
    rm -f tmp_data/props.csv
    python3 -m src.DataProviders.BettingProsProvider \
        --date "$DATE" --home "$HOME_TEAM" --away "$AWAY_TEAM" \
        --output "tmp_data/props.csv" \
        2>&1 | grep -E 'prop lines|Wrote|No.*events|No.*matching|warn|Error' || true

    if [[ ! -f "tmp_data/props.csv" ]] || [[ $(wc -l < "tmp_data/props.csv") -le 1 ]]; then
        echo "  [warn] No props retrieved — skipping"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    PROP_COUNT=$(( $(wc -l < "tmp_data/props.csv") - 1 ))

    # ── 2b: Archive ───────────────────────────────────────────────────────
    ./scripts/archive_props.sh --date "$DATE" \
        2>&1 | grep -E 'Archived|Already archived' || true
    rm -f tmp_data/props.csv

    if [[ ! -f "$ARCHIVE_FILE" ]]; then
        echo "  [warn] Archive file missing after archive step"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    # ── 2c: Label with BRef box score outcomes ────────────────────────────
    python3 -m src.DataProviders.PropOutcomeFetcher "$ARCHIVE_FILE" \
        2>&1 | grep -E 'Box score URL|Players|labeled|not found' || true

    DONE=$((DONE + 1))
    echo "  ✓ $PROP_COUNT props archived and labeled"
    echo ""

done <<< "$GAME_LIST"

# ── Summary ──────────────────────────────────────────────────────────────────
ts "=== Backfill complete ==="
echo ""
printf "  %-22s %d\n" "Games processed:"    $DONE
printf "  %-22s %d\n" "Already labeled:"    $SKIPPED
printf "  %-22s %d\n" "Errors / no data:"   $ERRORS
printf "  %-22s %d\n" "Total in archive:"   $((DONE + SKIPPED))
echo ""

TOTAL_LABELED=$(python3 -c "
import csv, pathlib
total = 0
for f in pathlib.Path('Data/prop_archives').glob('*.csv'):
    try:
        rows = list(csv.DictReader(open(f)))
        total += sum(1 for r in rows if r.get('Hit','').strip() != '')
    except:
        pass
print(total)
" 2>/dev/null || echo "?")
echo "  Total labeled prop rows in archive: $TOTAL_LABELED"
echo ""
echo "Next:"
echo "  python -m src.Process-Data.Build_Props_Training_Data_v2"
echo "  python -m src.Train-Models.Props_Model"
