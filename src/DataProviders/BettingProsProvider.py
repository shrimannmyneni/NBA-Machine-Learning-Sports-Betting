"""
Pulls NBA player prop lines from BettingPros and writes tmp_data/props.csv.

No external API key needed — uses a key extracted from BettingPros' public JS bundle.
The key auto-refreshes on 403 responses by re-scraping the bundle.

How it works:
  1. Fetch the BettingPros player-props page (HTML, 200 OK)
  2. Extract numeric event ID from the 997KB inline JSON blob
  3. Hit api.bettingpros.com/v3/offers for each prop market
  4. Parse player name, team, line, odds per sportsbook

Usage:
    python -m src.DataProviders.BettingProsProvider --date 2026-06-03
    python -m src.DataProviders.BettingProsProvider --date 2026-06-03 \\
        --home "San Antonio Spurs" --away "New York Knicks"
    python -m src.DataProviders.BettingProsProvider --dry-run
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path

from src.DataProviders.BRefDefenseProvider import TEAM_TO_BREF

TMP_DIR   = Path(__file__).resolve().parents[2] / "tmp_data"
CACHE_DIR = TMP_DIR / "bettingpros_cache"
KEY_FILE  = TMP_DIR / "bettingpros_key.txt"

_PAGE_BASE = "https://www.bettingpros.com"
_API_BASE  = "https://api.bettingpros.com"

# BettingPros internal market IDs
_MARKETS = {
    "Points":     156,
    "Rebounds":   157,
    "Assists":    151,
    "3-Pointers": 162,
}

# BettingPros internal book IDs → display names
_BOOKS = {18: "BetMGM", 12: "DraftKings", 10: "FanDuel"}
_BOOK_IDS = "18:12:10"

# BettingPros abbreviations that differ from BRef
_BP_TO_BREF = {
    "BKN": "BRK",
    "CHA": "CHO",
    "PHX": "PHO",
    "GS":  "GSW",
    "NOR": "NOP",
    "SA":  "SAS",
    "NY":  "NYK",
    "NO":  "NOP",
    "GS":  "GSW",
}

# Reverse map: BRef abbr → full team name
_BREF_TO_TEAM = {v: k for k, v in TEAM_TO_BREF.items()}

_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_REQUEST_DELAY = 2  # seconds between API calls


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

def _normalize_abbr(abbr):
    return _BP_TO_BREF.get(abbr.upper(), abbr.upper())


def _full_team(abbr):
    """BettingPros/BRef abbreviation → full team name."""
    return _BREF_TO_TEAM.get(_normalize_abbr(abbr), abbr)


def _load_cached_key():
    try:
        return KEY_FILE.read_text().strip() if KEY_FILE.exists() else None
    except Exception:
        return None


def _save_key(key):
    TMP_DIR.mkdir(exist_ok=True)
    KEY_FILE.write_text(key)


def _refresh_api_key():
    """
    Extracts the current x-api-key from BettingPros' JS bundles.

    The key lives in api-{hash}.js, which is not a direct page script tag.
    Chain: page → global_init-{hash}.js (import statement) → api-{hash}.js → key.
    """
    import requests
    from bs4 import BeautifulSoup

    # 1. Find the global_init bundle URL on the page.
    r = requests.get(
        f"{_PAGE_BASE}/nba/odds/player-props/",
        headers=_PAGE_HEADERS, timeout=15
    )
    soup = BeautifulSoup(r.text, "html.parser")

    global_init_src = next(
        (s["src"] for s in soup.find_all("script", src=True)
         if "global_init" in s.get("src", "")),
        None
    )
    if not global_init_src:
        return None

    # 2. Fetch global_init and find the api-*.js side-effect import.
    time.sleep(0.5)
    r2 = requests.get(f"{_PAGE_BASE}{global_init_src}", headers=_PAGE_HEADERS, timeout=10)
    m  = re.search(r'import[^"]*"\./(api-[^"]+\.js)"', r2.text)
    if not m:
        return None

    api_bundle = m.group(1)

    # 3. Fetch the api bundle and extract the key.
    time.sleep(0.5)
    r3  = requests.get(
        f"{_PAGE_BASE}/dist/assets/{api_bundle}", headers=_PAGE_HEADERS, timeout=10
    )
    key_m = re.search(
        r'(?:x-api-key|apiKey|API_KEY)["\s:=,]+["\`]([A-Za-z0-9_\-]{30,60})["\`]',
        r3.text, re.IGNORECASE
    )
    if key_m:
        key = key_m.group(1)
        _save_key(key)
        print(f"  [BettingPros] API key refreshed from {api_bundle}")
        return key

    return None


def _get_api_key(force_refresh=False):
    if not force_refresh:
        cached = _load_cached_key()
        if cached:
            return cached
    key = _refresh_api_key()
    if not key:
        raise RuntimeError(
            "Could not extract BettingPros API key from JS bundles. "
            "The bundle URL may have changed."
        )
    return key


# ---------------------------------------------------------------------------
# Page + API fetching
# ---------------------------------------------------------------------------

def _extract_events_from_page(date_str, force_refresh=False):
    """
    Parses the BettingPros player-props page for a date and returns a list of
    event dicts: [{id, home_abbr, away_abbr, home_team, away_team}, ...]
    """
    import requests
    from bs4 import BeautifulSoup

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{date_str}_events.json"

    if cache_path.exists() and not force_refresh:
        with open(cache_path) as f:
            return json.load(f)

    url = f"{_PAGE_BASE}/nba/odds/player-props/?date={date_str}"
    time.sleep(_REQUEST_DELAY)
    r = requests.get(url, headers=_PAGE_HEADERS, timeout=15)
    r.raise_for_status()

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")

    big = sorted(
        [s for s in soup.find_all("script") if s.string and len(s.string) > 10000],
        key=lambda s: len(s.string), reverse=True
    )
    if not big:
        return []

    data = json.loads(big[0].string)
    raw_events = data.get("events", {}).get("events", [])

    events = []
    for e in raw_events:
        home_abbr = _normalize_abbr(e.get("home", ""))
        away_abbr = _normalize_abbr(e.get("visitor", ""))
        events.append({
            "id":        e["id"],
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
            "home_team": _full_team(home_abbr),
            "away_team": _full_team(away_abbr),
        })

    with open(cache_path, "w") as f:
        json.dump(events, f, indent=2)

    return events


def _fetch_offers(event_id, market_id, date_str, force_refresh=False):
    """
    Hits api.bettingpros.com/v3/offers for one market.
    Returns raw list of offer dicts. Auto-refreshes API key on 403.
    """
    import requests

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{date_str}_{event_id}_{market_id}.json"

    if cache_path.exists() and not force_refresh:
        with open(cache_path) as f:
            return json.load(f)

    url    = f"{_API_BASE}/v3/offers"
    params = {
        "sport":     "NBA",
        "market_id": market_id,
        "event_id":  event_id,
        "book_id":   _BOOK_IDS,
    }

    for attempt in range(2):
        api_key = _get_api_key(force_refresh=(attempt > 0))
        headers = {**_PAGE_HEADERS, "x-api-key": api_key}
        time.sleep(_REQUEST_DELAY)
        resp = requests.get(url, params=params, headers=headers, timeout=15)

        if resp.status_code == 403 and attempt == 0:
            print("  [BettingPros] 403 — refreshing API key and retrying ...")
            continue

        resp.raise_for_status()
        offers = resp.json().get("offers", [])

        with open(cache_path, "w") as f:
            json.dump(offers, f, indent=2)

        return offers

    return []


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_offers(offers, prop_type, event):
    """
    Converts raw API offers into CSV row dicts.
    event: {home_abbr, away_abbr, home_team, away_team}
    """
    rows = []
    home_abbr = event["home_abbr"]

    for offer in offers:
        if not offer.get("active", True):
            continue

        participants = offer.get("participants", [])
        if not participants:
            continue

        p0          = participants[0]
        player_name = p0.get("name") or (
            p0.get("player", {}).get("first_name", "") + " " +
            p0.get("player", {}).get("last_name", "")
        ).strip()
        player_info     = p0.get("player", {})
        player_abbr     = _normalize_abbr(player_info.get("team", ""))
        player_team     = _full_team(player_abbr)
        opponent_abbr   = event["away_abbr"] if player_abbr == home_abbr else event["home_abbr"]
        opponent        = _full_team(opponent_abbr)

        if not player_name or not player_team:
            continue

        for selection in offer.get("selections", []):
            if not selection.get("active", True):
                continue
            direction = "OVER" if selection.get("selection", "").lower() == "over" else "UNDER"

            for book in selection.get("books", []):
                book_id = book.get("id")
                if book_id not in _BOOKS:
                    continue

                lines = book.get("lines", [])
                # Prefer the line marked main=True and not pulled (is_off=False)
                active_lines = [l for l in lines if not l.get("is_off", False)]
                main_lines   = [l for l in active_lines if l.get("main", False)]
                line_data    = (main_lines or active_lines or [None])[0]

                if not line_data:
                    continue

                line = line_data.get("line")
                cost = line_data.get("cost")
                if line is None or cost is None:
                    continue

                rows.append({
                    "Player":    player_name,
                    "Team":      player_team,
                    "Opponent":  opponent,
                    "PropType":  prop_type,
                    "Line":      line,
                    "Odds":      int(cost),
                    "Sportsbook": _BOOKS[book_id],
                    "Direction": direction,
                    "ModelProb": "",
                })

    return rows


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "Player", "Team", "Opponent", "PropType",
    "Line", "Odds", "Sportsbook", "Direction", "ModelProb",
]


def pull_props(date_str, home_team=None, away_team=None, force_refresh=False):
    """
    Pulls all player props for a given date (and optional team filter).
    Returns list of row dicts matching the props CSV schema.
    """
    events = _extract_events_from_page(date_str, force_refresh=force_refresh)

    if not events:
        print(f"  [BettingPros] No events found for {date_str}.")
        return []

    # Filter by team names if provided
    if home_team or away_team:
        def _matches(e):
            teams = {e["home_team"].lower(), e["away_team"].lower()}
            if home_team and home_team.lower() not in teams:
                return False
            if away_team and away_team.lower() not in teams:
                return False
            return True
        events = [e for e in events if _matches(e)]

    if not events:
        teams_msg = f" for {home_team or '?'} vs {away_team or '?'}"
        print(f"  [BettingPros] No matching events on {date_str}{teams_msg}.")
        return []

    all_rows = []
    for event in events:
        print(f"  [{event['away_team']} @ {event['home_team']}]  event_id={event['id']}")
        for prop_type, market_id in _MARKETS.items():
            offers = _fetch_offers(
                event["id"], market_id, date_str, force_refresh=force_refresh
            )
            rows = _parse_offers(offers, prop_type, event)
            all_rows.extend(rows)

        n_players = len({r["Player"] for r in all_rows})
        n_books   = len({r["Sportsbook"] for r in all_rows})
        print(f"  → {len(all_rows)} prop lines  |  {n_books} books  |  {n_players} players")

    return all_rows


def write_props_csv(rows, path=None):
    path = Path(path) if path else TMP_DIR / "props.csv"
    TMP_DIR.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows → {path}")
    return path


def run(date_str, home_team=None, away_team=None,
        output_path=None, dry_run=False, force_refresh=False):
    print(f"BettingPros props pull — {date_str}")
    events = _extract_events_from_page(date_str, force_refresh=force_refresh)

    if not events:
        print(f"  No NBA events found on {date_str}.")
        return []

    print(f"  {len(events)} event(s) on {date_str}:")
    for e in events:
        print(f"    {e['away_team']} @ {e['home_team']}")

    if dry_run:
        print("  [dry-run] Stopping before props pull.")
        return []

    rows = pull_props(date_str, home_team=home_team, away_team=away_team,
                      force_refresh=force_refresh)
    if rows:
        write_props_csv(rows, path=output_path)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Pull NBA player props from BettingPros.")
    parser.add_argument("--date",    default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--home",    help="Home team full name")
    parser.add_argument("--away",    help="Away team full name")
    parser.add_argument("--output",  help="Output CSV path (default: tmp_data/props.csv)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List events without pulling props")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Bypass all caches and re-fetch")
    args = parser.parse_args()

    from datetime import date
    date_str = args.date or str(date.today())

    run(
        date_str      = date_str,
        home_team     = args.home,
        away_team     = args.away,
        output_path   = args.output,
        dry_run       = args.dry_run,
        force_refresh = args.force_refresh,
    )


if __name__ == "__main__":
    main()
