"""
Scrapes Basketball Reference team opponent per-game stats and caches them in
tmp_data/ (gitignored).

Usage:
    from src.DataProviders.BRefDefenseProvider import get_team_defense
    stats = get_team_defense("BOS", year=2026)

Returns a flat dict of opponent per-game averages, e.g.:
    {"opp_pts": 108.4, "opp_fg_pct": 0.452, "opp_reb": 43.1, ...}

Position-specific splits (PG/SG/SF/PF/C) require NBA.com's defense dashboard
and are not available on Basketball Reference. The aggregate stats here serve
as a team-level defensive quality signal for the props model.

Requires: requests, beautifulsoup4
    pip install requests beautifulsoup4
"""

import json
import time
from pathlib import Path

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp_data"

# Maps full team names (as used elsewhere in this codebase) to BRef abbreviations.
TEAM_TO_BREF = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BRK",
    "Charlotte Hornets": "CHO",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHO",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# BRef throttles aggressively; wait between requests.
_REQUEST_DELAY_SECONDS = 4


def _fetch_opp_per_game(abbr, year):
    """
    Fetches the opponent per-game row from the team season page.
    Returns a dict of stat_name -> float, or {} on failure.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "BRefDefenseProvider requires 'requests' and 'beautifulsoup4'. "
            "Install them with: pip install requests beautifulsoup4"
        ) from exc

    url = f"https://www.basketball-reference.com/teams/{abbr}/{year}.html"
    time.sleep(_REQUEST_DELAY_SECONDS)
    response = requests.get(url, headers=_HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # The opponent per-game table is sometimes inside an HTML comment on BRef.
    # Parse raw HTML as a fallback.
    table = soup.find("table", {"id": "per_game-opponent"})
    if table is None:
        import re
        comment_pattern = re.compile(r"<!--(.*?)-->", re.DOTALL)
        comments = comment_pattern.findall(response.text)
        for comment in comments:
            if 'id="per_game-opponent"' in comment:
                table = BeautifulSoup(comment, "html.parser").find(
                    "table", {"id": "per_game-opponent"}
                )
                break

    if table is None:
        return {}

    # Grab the column headers.
    headers = [th.get_text(strip=True) for th in table.select("thead tr th")]

    # Use the last data row (most recent season summary).
    rows = table.select("tbody tr:not(.thead)")
    if not rows:
        return {}

    cells = [td.get_text(strip=True) for td in rows[-1].find_all(["th", "td"])]

    stats = {}
    for header, value in zip(headers, cells):
        if not header or header in ("Season", "Lg", "Tm", ""):
            continue
        try:
            stats[f"opp_{header.lower().replace('%', '_pct').replace('/', '_per_')}"] = float(value)
        except ValueError:
            pass

    return stats


def get_team_defense(team_name_or_abbr, year=2026, force_refresh=False):
    """
    Returns a dict of opponent per-game defensive stats for the given team.

    team_name_or_abbr: Full team name (e.g. "Boston Celtics") or BRef abbreviation ("BOS").
    year: Season end year (e.g. 2026 for the 2025-26 season).
    force_refresh: Bypass the cache and re-scrape.
    """
    TMP_DIR.mkdir(exist_ok=True)

    # Resolve abbreviation.
    if team_name_or_abbr in TEAM_TO_BREF.values():
        abbr = team_name_or_abbr
    else:
        abbr = TEAM_TO_BREF.get(team_name_or_abbr)
        if abbr is None:
            raise ValueError(
                f"Unknown team '{team_name_or_abbr}'. "
                f"Add it to TEAM_TO_BREF or pass the BRef abbreviation directly."
            )

    cache_path = TMP_DIR / f"bref_defense_{abbr}_{year}.json"

    if cache_path.exists() and not force_refresh:
        with open(cache_path) as f:
            return json.load(f)

    stats = _fetch_opp_per_game(abbr, year)

    with open(cache_path, "w") as f:
        json.dump(stats, f, indent=2)

    return stats


def get_defense_for_teams(team_names, year=2026, force_refresh=False):
    """
    Fetches defense stats for multiple teams, respecting BRef's rate limit.
    Returns dict keyed by team name: {team_name: {stat: value, ...}, ...}
    """
    results = {}
    for name in team_names:
        try:
            results[name] = get_team_defense(name, year=year, force_refresh=force_refresh)
        except Exception as exc:
            print(f"[BRefDefenseProvider] Failed to fetch {name}: {exc}")
            results[name] = {}
    return results
