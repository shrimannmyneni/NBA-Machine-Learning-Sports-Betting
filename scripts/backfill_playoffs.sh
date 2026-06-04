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

# Fall back to hardcoded 2026 playoff schedule if BRef page isn't available
if [[ -z "$GAME_LIST" ]]; then
    ts "BRef schedule page unavailable — using hardcoded 2026 playoff schedule"
    GAME_LIST=$(cat <<'GAMES'
2026-04-14|Portland Trail Blazers|Phoenix Suns
2026-04-14|Miami Heat|Charlotte Hornets
2026-04-15|Philadelphia 76ers|Orlando Magic
2026-04-15|Los Angeles Clippers|Golden State Warriors
2026-04-17|Orlando Magic|Charlotte Hornets
2026-04-17|Phoenix Suns|Golden State Warriors
2026-04-18|Cleveland Cavaliers|Toronto Raptors
2026-04-18|Denver Nuggets|Minnesota Timberwolves
2026-04-18|New York Knicks|Atlanta Hawks
2026-04-18|Los Angeles Lakers|Houston Rockets
2026-04-19|Boston Celtics|Philadelphia 76ers
2026-04-19|Oklahoma City Thunder|Phoenix Suns
2026-04-19|Detroit Pistons|Orlando Magic
2026-04-19|San Antonio Spurs|Portland Trail Blazers
2026-04-20|Cleveland Cavaliers|Toronto Raptors
2026-04-20|New York Knicks|Atlanta Hawks
2026-04-20|Denver Nuggets|Minnesota Timberwolves
2026-04-21|Boston Celtics|Philadelphia 76ers
2026-04-21|San Antonio Spurs|Portland Trail Blazers
2026-04-21|Los Angeles Lakers|Houston Rockets
2026-04-22|Detroit Pistons|Orlando Magic
2026-04-22|Oklahoma City Thunder|Phoenix Suns
2026-04-23|New York Knicks|Atlanta Hawks
2026-04-23|Cleveland Cavaliers|Toronto Raptors
2026-04-23|Denver Nuggets|Minnesota Timberwolves
2026-04-24|Boston Celtics|Philadelphia 76ers
2026-04-24|Los Angeles Lakers|Houston Rockets
2026-04-24|San Antonio Spurs|Portland Trail Blazers
2026-04-25|Detroit Pistons|Orlando Magic
2026-04-25|Oklahoma City Thunder|Phoenix Suns
2026-04-25|New York Knicks|Atlanta Hawks
2026-04-25|Denver Nuggets|Minnesota Timberwolves
2026-04-26|Cleveland Cavaliers|Toronto Raptors
2026-04-26|San Antonio Spurs|Portland Trail Blazers
2026-04-26|Boston Celtics|Philadelphia 76ers
2026-04-26|Los Angeles Lakers|Houston Rockets
2026-04-27|Detroit Pistons|Orlando Magic
2026-04-27|Oklahoma City Thunder|Phoenix Suns
2026-04-27|Denver Nuggets|Minnesota Timberwolves
2026-04-28|Boston Celtics|Philadelphia 76ers
2026-04-28|Atlanta Hawks|New York Knicks
2026-04-28|Portland Trail Blazers|San Antonio Spurs
2026-04-29|Orlando Magic|Detroit Pistons
2026-04-29|Toronto Raptors|Cleveland Cavaliers
2026-04-29|Houston Rockets|Los Angeles Lakers
2026-04-30|Atlanta Hawks|New York Knicks
2026-04-30|Boston Celtics|Philadelphia 76ers
2026-04-30|Denver Nuggets|Minnesota Timberwolves
2026-05-01|Orlando Magic|Detroit Pistons
2026-05-01|Cleveland Cavaliers|Toronto Raptors
2026-05-01|Houston Rockets|Los Angeles Lakers
2026-05-02|Boston Celtics|Philadelphia 76ers
2026-05-03|Orlando Magic|Detroit Pistons
2026-05-03|Toronto Raptors|Cleveland Cavaliers
2026-05-04|Philadelphia 76ers|New York Knicks
2026-05-04|Minnesota Timberwolves|San Antonio Spurs
2026-05-05|Cleveland Cavaliers|Detroit Pistons
2026-05-05|Los Angeles Lakers|Oklahoma City Thunder
2026-05-06|New York Knicks|Philadelphia 76ers
2026-05-06|San Antonio Spurs|Minnesota Timberwolves
2026-05-07|Cleveland Cavaliers|Detroit Pistons
2026-05-07|Los Angeles Lakers|Oklahoma City Thunder
2026-05-08|New York Knicks|Philadelphia 76ers
2026-05-08|San Antonio Spurs|Minnesota Timberwolves
2026-05-09|Detroit Pistons|Cleveland Cavaliers
2026-05-09|Los Angeles Lakers|Oklahoma City Thunder
2026-05-10|Philadelphia 76ers|New York Knicks
2026-05-10|Minnesota Timberwolves|San Antonio Spurs
2026-05-11|Detroit Pistons|Cleveland Cavaliers
2026-05-11|Los Angeles Lakers|Oklahoma City Thunder
2026-05-12|Minnesota Timberwolves|San Antonio Spurs
2026-05-13|Detroit Pistons|Cleveland Cavaliers
2026-05-15|Cleveland Cavaliers|Detroit Pistons
2026-05-15|Minnesota Timberwolves|San Antonio Spurs
2026-05-17|Detroit Pistons|Cleveland Cavaliers
2026-05-18|Oklahoma City Thunder|San Antonio Spurs
2026-05-19|Cleveland Cavaliers|New York Knicks
2026-05-20|San Antonio Spurs|Oklahoma City Thunder
2026-05-21|Cleveland Cavaliers|New York Knicks
2026-05-22|Oklahoma City Thunder|San Antonio Spurs
2026-05-23|New York Knicks|Cleveland Cavaliers
2026-05-24|San Antonio Spurs|Oklahoma City Thunder
2026-05-25|New York Knicks|Cleveland Cavaliers
2026-05-26|Oklahoma City Thunder|San Antonio Spurs
2026-05-28|San Antonio Spurs|Oklahoma City Thunder
2026-05-30|Oklahoma City Thunder|San Antonio Spurs
2026-06-03|San Antonio Spurs|New York Knicks
GAMES
)
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
