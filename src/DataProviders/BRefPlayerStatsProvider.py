"""
Scrapes Basketball Reference player game logs for the current season.
Caches results in tmp_data/player_stats/ (gitignored).

Usage:
    from src.DataProviders.BRefPlayerStatsProvider import get_rolling_averages, get_player_game_log

    # Rolling averages for tonight's prediction:
    avgs = get_rolling_averages("De'Aaron Fox", year=2026, last_n=10)
    # {"pts_avg": 18.3, "trb_avg": 4.1, ..., "games_in_window": 10}

    # Full season game log for training data:
    log = get_player_game_log("Jalen Brunson", year=2026)
    # [{"date": "2025-10-22", "opp": "BOS", "home": 1, "pts": 22.0, ...}, ...]

Requires: requests, beautifulsoup4
    pip install requests beautifulsoup4
"""

import json
import re
import time
from pathlib import Path

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp_data" / "player_stats"

# BRef player page IDs. Format: first5(lastname) + first2(firstname) + 01.
# Add players here as needed — runner fails gracefully if a player is missing.
PLAYER_TO_BREF_ID = {
    "De'Aaron Fox":       "foxde01",
    "Jalen Brunson":      "brunsja01",
    "Josh Hart":          "hartjo01",
    "Devin Vassell":      "vassede01",
    "Victor Wembanyama":  "wembavi01",
    "Mikal Bridges":      "bridgmi01",
    "Karl-Anthony Towns": "townska01",
    "Julian Champagnie":  "champju01",
    "Stephon Castle":     "castlst01",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_REQUEST_DELAY_SECONDS = 4


def _parse_minutes(mp_str):
    """Converts 'MM:SS' to decimal minutes; returns None for DNP/inactive rows."""
    try:
        parts = str(mp_str).split(":")
        if len(parts) != 2:
            return None
        return int(parts[0]) + int(parts[1]) / 60
    except Exception:
        return None


def _fetch_game_log(player_id, year):
    """
    Scrapes the BRef game log page and returns a list of per-game dicts.
    Skips any game row where the player did not participate.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise ImportError(
            "BRefPlayerStatsProvider requires 'requests' and 'beautifulsoup4'. "
            "Install with: pip install requests beautifulsoup4"
        ) from exc

    url = (
        f"https://www.basketball-reference.com/players/"
        f"{player_id[0]}/{player_id}/gamelog/{year}/"
    )
    time.sleep(_REQUEST_DELAY_SECONDS)
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    if resp.status_code == 404:
        return []  # wrong ID — auto-derivation miss
    resp.raise_for_status()

    from bs4 import BeautifulSoup  # noqa: F811 — needed after lazy import

    soup = BeautifulSoup(resp.text, "html.parser")
    # BRef renamed the table id for the 2025-26 season layout.
    table = soup.find("table", {"id": "player_game_log_reg"})

    # BRef sometimes wraps tables in HTML comments.
    if table is None:
        for comment in re.compile(r"<!--(.*?)-->", re.DOTALL).findall(resp.text):
            if 'id="player_game_log_reg"' in comment:
                table = BeautifulSoup(comment, "html.parser").find(
                    "table", {"id": "player_game_log_reg"}
                )
                break

    if table is None:
        return []

    def _cell_float(row, stat):
        td = row.find(["td", "th"], {"data-stat": stat})
        if td is None:
            return None
        try:
            return float(td.get_text(strip=True))
        except ValueError:
            return None

    games = []
    for row in table.select("tbody tr"):
        # Skip header-repeat rows (Rk cell contains "Rk" text, not a number).
        rk_cell = row.find(["td", "th"], {"data-stat": "ranker"})
        if rk_cell is None or not rk_cell.get_text(strip=True).isdigit():
            continue

        mp_cell = row.find(["td", "th"], {"data-stat": "mp"})
        if mp_cell is None:
            continue
        mp = _parse_minutes(mp_cell.get_text(strip=True))
        if mp is None:
            continue  # DNP / Inactive / Suspended rows

        pts = _cell_float(row, "pts")
        trb = _cell_float(row, "trb")
        ast = _cell_float(row, "ast")
        fg3 = _cell_float(row, "fg3")

        if any(v is None for v in (pts, trb, ast, fg3)):
            continue

        date_cell = row.find(["td", "th"], {"data-stat": "date"})
        date_str = date_cell.get_text(strip=True) if date_cell else ""

        opp_cell = row.find(["td", "th"], {"data-stat": "opp_name_abbr"})
        opp_abbr = opp_cell.get_text(strip=True) if opp_cell else ""

        loc_cell = row.find(["td", "th"], {"data-stat": "game_location"})
        home = 0 if (loc_cell and loc_cell.get_text(strip=True) == "@") else 1

        games.append({
            "date": date_str,
            "opp": opp_abbr,
            "home": home,
            "pts": pts,
            "trb": trb,
            "ast": ast,
            "fg3": fg3,
            "mp": mp,
        })

    return games


def _auto_bref_id(player_name):
    """
    Derives a BRef player ID using the standard convention:
        first5(lastname) + first2(firstname) + '01'

    Handles apostrophes, hyphens, Jr/Sr/II/III suffixes.
    Returns the derived candidate ID (may not be valid — caller handles 404).
    """
    parts = player_name.strip().split()
    if len(parts) < 2:
        return None

    first = parts[0]
    last_parts = parts[1:]
    # Strip common suffixes from last name
    last_parts = [p for p in last_parts
                  if p.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv")]
    if not last_parts:
        return None

    last = "".join(last_parts)
    first_clean = re.sub(r"[^a-z]", "", first.lower())
    last_clean  = re.sub(r"[^a-z]", "", last.lower())

    if not first_clean or not last_clean:
        return None

    return f"{last_clean[:5]}{first_clean[:2]}01"


def get_player_game_log(player_name, year=2026, force_refresh=False):
    """
    Full season game log for a player, sorted chronologically.
    Each element: {date, opp, home, pts, trb, ast, fg3, mp}

    Uses PLAYER_TO_BREF_ID for known players; auto-derives the BRef ID for
    unknown players using the standard naming convention. Returns [] if the
    player cannot be found on BRef (wrong auto-derived ID → 404 cached as []).
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    player_id = PLAYER_TO_BREF_ID.get(player_name) or _auto_bref_id(player_name)
    if player_id is None:
        return []

    cache_path = TMP_DIR / f"{player_id}_{year}.json"
    if cache_path.exists() and not force_refresh:
        with open(cache_path) as f:
            return json.load(f)

    games = _fetch_game_log(player_id, year)

    with open(cache_path, "w") as f:
        json.dump(games, f, indent=2)

    return games


def get_rolling_averages(player_name, year=2026, last_n=10, force_refresh=False):
    """
    Rolling averages over the player's last N games this season.

    Returned keys:
        pts_avg, trb_avg, ast_avg, fg3_avg, mp_avg   — means
        pts_std, trb_std, ast_std, fg3_std            — sample std devs
        games_in_window                               — actual games in window
    """
    games = get_player_game_log(player_name, year=year, force_refresh=force_refresh)
    if not games:
        return {}

    window = games[-last_n:]

    def _avg(col):
        vals = [g[col] for g in window if g.get(col) is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    def _std(col):
        vals = [g[col] for g in window if g.get(col) is not None]
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        return round((sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5, 3)

    return {
        "pts_avg":        _avg("pts"),
        "trb_avg":        _avg("trb"),
        "ast_avg":        _avg("ast"),
        "fg3_avg":        _avg("fg3"),
        "mp_avg":         _avg("mp"),
        "pts_std":        _std("pts"),
        "trb_std":        _std("trb"),
        "ast_std":        _std("ast"),
        "fg3_std":        _std("fg3"),
        "games_in_window": len(window),
    }
