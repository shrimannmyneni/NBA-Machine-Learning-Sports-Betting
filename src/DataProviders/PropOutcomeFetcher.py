"""
Fetches actual player stat outcomes from Basketball Reference box scores
and labels archived prop CSV files with Actual and Hit columns.

Hit = 1 if this specific bet won (direction-aware):
    OVER bet: actual > line  → Hit=1
    UNDER bet: actual < line → Hit=1

Usage:
    python -m src.DataProviders.PropOutcomeFetcher data/prop_archives/2026-06-03_New_York_Knicks_vs_San_Antonio_Spurs.csv

Cache: tmp_data/boxscores/{YYYYMMDD}_{HOME_ABBR}.json

Requires: requests, beautifulsoup4
"""

import csv
import json
import re
import time
from pathlib import Path

from src.DataProviders.BRefDefenseProvider import TEAM_TO_BREF

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp_data" / "boxscores"

PROP_TO_STAT = {
    "Points":     "pts",
    "Rebounds":   "trb",
    "Assists":    "ast",
    "3-Pointers": "fg3",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY_SECONDS = 4


def _norm(name):
    """Normalize player name for fuzzy matching (lowercase, alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _parse_box_table(table):
    """
    Parses one team's basic box score table.
    Returns {normalized_name: {name, dnp, pts, trb, ast, fg3}}.
    DNP players get 0 for all stats.
    """
    players = {}
    for row in table.select("tbody tr"):
        player_cell = row.find(["td", "th"], {"data-stat": "player"})
        if player_cell is None:
            continue
        name = player_cell.get_text(strip=True)
        if not name or name in ("Team Totals", "Reserves", "Starters"):
            continue

        mp_cell = row.find(["td", "th"], {"data-stat": "mp"})
        mp_text = mp_cell.get_text(strip=True) if mp_cell else ""
        is_dnp = not bool(re.match(r"^\d+:\d+$", mp_text))

        def _float(stat):
            td = row.find(["td", "th"], {"data-stat": stat})
            if td is None:
                return 0.0
            try:
                return float(td.get_text(strip=True))
            except ValueError:
                return 0.0

        players[_norm(name)] = {
            "name": name,
            "dnp":  is_dnp,
            "pts":  _float("pts"),
            "trb":  _float("trb"),
            "ast":  _float("ast"),
            "fg3":  _float("fg3"),
        }
    return players


def fetch_box_score(date_str, team1, team2, force_refresh=False):
    """
    Returns {normalized_player_name: {name, dnp, pts, trb, ast, fg3}} for
    all players in the game. Auto-detects home team by trying both abbreviations.

    Caches result in tmp_data/boxscores/{YYYYMMDD}_{HOME_ABBR}.json.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "PropOutcomeFetcher requires 'requests' and 'beautifulsoup4'."
        ) from exc

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    date_compact = date_str.replace("-", "")
    abbr1 = TEAM_TO_BREF.get(team1)
    abbr2 = TEAM_TO_BREF.get(team2)

    if not abbr1 or not abbr2:
        raise ValueError(
            f"Unknown team name(s): {team1!r}, {team2!r}. Check TEAM_TO_BREF."
        )

    # Serve from cache if available.
    for abbr in (abbr1, abbr2):
        cache_path = TMP_DIR / f"{date_compact}_{abbr}.json"
        if cache_path.exists() and not force_refresh:
            with open(cache_path) as f:
                return json.load(f)

    # Try each team as home; first 200 wins.
    raw_html = home_abbr = None
    for abbr in (abbr1, abbr2):
        url = (
            f"https://www.basketball-reference.com/boxscores/"
            f"{date_compact}0{abbr}.html"
        )
        time.sleep(_REQUEST_DELAY_SECONDS)
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        if resp.status_code == 200:
            raw_html = resp.text
            home_abbr = abbr
            print(f"  Box score URL: {url}")
            break

    if raw_html is None:
        raise RuntimeError(
            f"Could not find BRef box score for {date_str} — "
            f"tried {abbr1} and {abbr2} as home team."
        )

    soup     = BeautifulSoup(raw_html, "html.parser")
    comments = re.compile(r"<!--(.*?)-->", re.DOTALL).findall(raw_html)

    all_players = {}
    for abbr in (abbr1, abbr2):
        tid   = f"box-{abbr}-game-basic"
        table = soup.find("table", {"id": tid})
        if table is None:
            for c in comments:
                if f'id="{tid}"' in c:
                    table = BeautifulSoup(c, "html.parser").find("table", {"id": tid})
                    break
        if table:
            all_players.update(_parse_box_table(table))
        else:
            print(f"  [warn] Could not find box score table for {abbr}")

    cache_path = TMP_DIR / f"{date_compact}_{home_abbr}.json"
    with open(cache_path, "w") as f:
        json.dump(all_players, f, indent=2)

    return all_players


def label_archive_csv(csv_path, force_refresh=False):
    """
    Adds Actual and Hit columns to a prop archive CSV in-place.
    Derives game date and teams from the filename.

    Hit is direction-aware:
        OVER bet: Hit=1 if actual > line
        UNDER bet: Hit=1 if actual < line

    Returns summary dict.
    """
    csv_path = Path(csv_path)
    stem     = csv_path.stem   # e.g. 2026-06-03_New_York_Knicks_vs_San_Antonio_Spurs

    date_str = stem[:10]
    rest     = stem[11:]
    parts    = rest.split("_vs_")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse teams from filename: {csv_path.name}")

    team1 = parts[0].replace("_", " ")
    team2 = parts[1].replace("_", " ")

    print(f"Labeling: {csv_path.name}")
    box = fetch_box_score(date_str, team1, team2, force_refresh=force_refresh)
    print(f"  Players in box score: {len(box)}")

    rows      = []
    summary   = {"total": 0, "labeled": 0, "hits": 0, "misses": 0, "dnp": 0, "not_found": 0}
    new_fields = ["Actual", "Hit"]

    with open(csv_path, newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for nf in new_fields:
            if nf not in fieldnames:
                fieldnames.append(nf)

        for row in reader:
            summary["total"] += 1
            prop_type = row["PropType"].strip()
            stat_col  = PROP_TO_STAT.get(prop_type)
            line      = float(row["Line"])
            direction = row.get("Direction", "OVER").strip().upper()
            key       = _norm(row["Player"].strip())

            player_data = box.get(key)

            if player_data is None:
                row["Actual"] = ""
                row["Hit"]    = ""
                summary["not_found"] += 1
            else:
                actual   = player_data.get(stat_col, 0.0)
                bet_wins = (actual > line) if direction == "OVER" else (actual < line)
                hit      = 1 if bet_wins else 0

                row["Actual"] = actual
                row["Hit"]    = hit
                summary["labeled"] += 1

                if player_data.get("dnp"):
                    summary["dnp"] += 1
                elif hit:
                    summary["hits"] += 1
                else:
                    summary["misses"] += 1

            rows.append(row)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n = summary["labeled"]
    h = summary["hits"]
    rate = f"{h/n*100:.1f}%" if n else "N/A"
    print(f"  {n}/{summary['total']} labeled  |  {h} hits / {summary['misses']} misses  "
          f"|  hit rate: {rate}  |  {summary['dnp']} DNP  |  {summary['not_found']} not found")
    return summary


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.DataProviders.PropOutcomeFetcher <archive_csv>")
        sys.exit(1)
    label_archive_csv(sys.argv[1])
