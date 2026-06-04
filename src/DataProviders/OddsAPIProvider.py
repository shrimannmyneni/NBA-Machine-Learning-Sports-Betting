"""
Pulls NBA player prop lines from The Odds API and writes tmp_data/props.csv.

API key: read from ODDS_API_KEY environment variable — never hardcoded.
Free tier: 500 requests/month — remaining credits printed after every call.

Usage:
    # Dry run — list tonight's games, don't pull props
    python -m src.DataProviders.OddsAPIProvider --dry-run

    # Pull all props for tonight
    python -m src.DataProviders.OddsAPIProvider

    # Pull for a specific matchup
    python -m src.DataProviders.OddsAPIProvider --home "San Antonio Spurs" --away "New York Knicks"
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp_data"

BASE_URL = "https://api.the-odds-api.com/v4"

MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]

MARKET_TO_PROP_TYPE = {
    "player_points":   "Points",
    "player_rebounds": "Rebounds",
    "player_assists":  "Assists",
    "player_threes":   "3-Pointers",
}

BOOK_KEYS    = ["betmgm", "draftkings", "fanduel"]
BOOK_DISPLAY = {
    "betmgm":     "BetMGM",
    "draftkings": "DraftKings",
    "fanduel":    "FanDuel",
}

# Odds API uses full official names; map any that differ from our TEAM_TO_BREF keys.
ODDS_API_TEAM_MAP = {
    "Los Angeles Clippers": "LA Clippers",
}

OUTPUT_COLUMNS = [
    "Player", "Team", "Opponent", "PropType",
    "Line", "Odds", "Sportsbook", "Direction", "ModelProb",
]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api_key():
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "ODDS_API_KEY is not set. "
            "Export it in your shell: export ODDS_API_KEY=your_key_here"
        )
    return key


def _get(session, url, params):
    """GET request with credit reporting. Raises on HTTP error."""
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    remaining = resp.headers.get("x-requests-remaining", "?")
    used      = resp.headers.get("x-requests-used", "?")
    print(f"  [OddsAPI] used={used}  remaining={remaining}")
    return resp.json()


def _normalize_team(name):
    """Maps Odds API team names to our canonical names where they differ."""
    return ODDS_API_TEAM_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Roster lookup  (nba_api, cached in tmp_data/)
# ---------------------------------------------------------------------------

def _get_roster(team_name):
    """
    Returns a set of player full names for a team.
    Caches result in tmp_data/roster_{abbr}.json.
    Returns empty set on any failure — caller handles gracefully.
    """
    from src.DataProviders.BRefDefenseProvider import TEAM_TO_BREF

    abbr       = TEAM_TO_BREF.get(team_name, "UNK")
    cache_path = TMP_DIR / f"roster_{abbr}.json"

    if cache_path.exists():
        with open(cache_path) as f:
            return set(json.load(f))

    try:
        import time
        from nba_api.stats.endpoints import CommonTeamRoster
        from nba_api.stats.static import teams as nba_teams

        team_list = nba_teams.get_teams()
        team_info = next(
            (t for t in team_list if t["full_name"] == team_name), None
        )
        if not team_info:
            print(f"  [warn] nba_api: team not found — {team_name!r}")
            return set()

        time.sleep(1)  # nba.com rate limiting
        roster_df = CommonTeamRoster(team_id=team_info["id"]).get_data_frames()[0]
        players   = set(roster_df["PLAYER"].tolist())

        TMP_DIR.mkdir(exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(list(players), f)

        return players

    except Exception as exc:
        print(f"  [warn] roster fetch failed for {team_name}: {exc}")
        return set()


def _assign_team(player, home_roster, away_roster, home_team, away_team):
    """Returns (team, opponent) for a player. Falls back to ('', '') if unknown."""
    if player in home_roster:
        return home_team, away_team
    if player in away_roster:
        return away_team, home_team
    return "", ""


# ---------------------------------------------------------------------------
# Core API calls
# ---------------------------------------------------------------------------

def get_todays_events(home_team=None, away_team=None):
    """
    Fetches today's NBA events from The Odds API.
    Optionally filters to a specific matchup.
    Returns list of event dicts: [{id, home_team, away_team, commence_time}, ...]
    """
    import requests

    session = requests.Session()
    params  = {"apiKey": _api_key(), "dateFormat": "iso"}
    events  = _get(session, f"{BASE_URL}/sports/basketball_nba/events", params)

    today = datetime.now(timezone.utc).date()
    events = [
        e for e in events
        if datetime.fromisoformat(
            e["commence_time"].replace("Z", "+00:00")
        ).date() == today
    ]

    # Normalize team names
    for e in events:
        e["home_team"] = _normalize_team(e["home_team"])
        e["away_team"] = _normalize_team(e["away_team"])

    if home_team or away_team:
        h = _normalize_team(home_team or "")
        a = _normalize_team(away_team or "")
        events = [
            e for e in events
            if (not h or e["home_team"] == h or e["away_team"] == h)
            and (not a or e["home_team"] == a or e["away_team"] == a)
        ]

    return events


def pull_props_for_event(event, books=None):
    """
    Pulls player props for one event.
    Returns list of row dicts matching the props CSV schema.
    """
    import requests

    books   = books or BOOK_KEYS
    session = requests.Session()
    params  = {
        "apiKey":      _api_key(),
        "regions":     "us",
        "markets":     ",".join(MARKETS),
        "bookmakers":  ",".join(books),
        "oddsFormat":  "american",
    }

    home_team = event["home_team"]
    away_team = event["away_team"]

    print(f"  Fetching props: {away_team} @ {home_team}")
    data = _get(
        session,
        f"{BASE_URL}/sports/basketball_nba/events/{event['id']}/odds",
        params,
    )

    home_roster = _get_roster(home_team)
    away_roster = _get_roster(away_team)

    unknown_players = []
    rows = []

    for bookmaker in data.get("bookmakers", []):
        book_key     = bookmaker["key"]
        book_display = BOOK_DISPLAY.get(book_key, book_key.title())

        for market in bookmaker.get("markets", []):
            prop_type = MARKET_TO_PROP_TYPE.get(market["key"])
            if not prop_type:
                continue

            for outcome in market.get("outcomes", []):
                player = outcome.get("description", "").strip()
                if not player:
                    continue

                line = outcome.get("point")
                odds = outcome.get("price")
                if line is None or odds is None:
                    continue

                direction = "OVER" if outcome["name"].lower() == "over" else "UNDER"
                team, opponent = _assign_team(
                    player, home_roster, away_roster, home_team, away_team
                )

                if not team:
                    unknown_players.append(player)

                rows.append({
                    "Player":    player,
                    "Team":      team,
                    "Opponent":  opponent,
                    "PropType":  prop_type,
                    "Line":      line,
                    "Odds":      int(odds),
                    "Sportsbook": book_display,
                    "Direction": direction,
                    "ModelProb": "",
                })

    if unknown_players:
        unique_unknown = sorted(set(unknown_players))
        print(f"  [warn] Could not assign team for: {', '.join(unique_unknown[:5])}"
              + (f" ... +{len(unique_unknown)-5} more" if len(unique_unknown) > 5 else ""))
        print(f"         Add them to nba_api roster or set Team/Opponent manually.")

    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_props_csv(rows, path=None):
    path = Path(path) if path else TMP_DIR / "props.csv"
    TMP_DIR.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows → {path}")
    return path


def summarize(rows):
    players   = len({r["Player"] for r in rows})
    books     = len({r["Sportsbook"] for r in rows})
    no_team   = sum(1 for r in rows if not r["Team"])
    print(f"\n  {len(rows)} prop lines  |  {books} books  |  {players} players", end="")
    if no_team:
        print(f"  |  {no_team} rows missing team assignment", end="")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(home_team=None, away_team=None, books=None, output_path=None, dry_run=False):
    print("Fetching today's NBA events ...")
    events = get_todays_events(home_team=home_team, away_team=away_team)

    if not events:
        filter_msg = f" matching {home_team or ''} / {away_team or ''}" if (home_team or away_team) else ""
        print(f"No NBA events found today{filter_msg}.")
        return []

    print(f"\nTonight's game(s):")
    for e in events:
        ct    = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        local = ct.astimezone().strftime("%I:%M %p %Z")
        print(f"  {e['away_team']} @ {e['home_team']}  —  {local}")

    if dry_run:
        print("\n[dry-run] Events fetched. Pass --no-dry-run to pull props.")
        return []

    all_rows = []
    for event in events:
        rows = pull_props_for_event(event, books=books)
        all_rows.extend(rows)

    if all_rows:
        write_props_csv(all_rows, path=output_path)
        summarize(all_rows)

    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Pull NBA player props from The Odds API.")
    parser.add_argument("--home",     help="Home team full name")
    parser.add_argument("--away",     help="Away team full name")
    parser.add_argument("--books",    nargs="+", default=BOOK_KEYS,
                        choices=list(BOOK_DISPLAY.keys()),
                        help="Sportsbooks to pull (default: betmgm draftkings fanduel)")
    parser.add_argument("--output",   help="Output CSV path (default: tmp_data/props.csv)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="List tonight's games but don't pull props")
    parser.add_argument("--force-roster-refresh", action="store_true",
                        help="Re-fetch team rosters even if cached")
    args = parser.parse_args()

    if args.force_roster_refresh:
        from src.DataProviders.BRefDefenseProvider import TEAM_TO_BREF
        for team in list(TEAM_TO_BREF.keys()):
            abbr  = TEAM_TO_BREF[team]
            cache = TMP_DIR / f"roster_{abbr}.json"
            if cache.exists():
                cache.unlink()
        print("Roster cache cleared.")

    run(
        home_team=args.home,
        away_team=args.away,
        books=args.books,
        output_path=args.output,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
