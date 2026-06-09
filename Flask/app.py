import subprocess
import threading
from datetime import date
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# All subprocesses run from the project root, not from Flask/
PROJECT_ROOT = Path(__file__).parent.parent

ACTIONS = {
    "pull-props":      ["python3", "-m", "src.DataProviders.BettingProsProvider"],
    "run-model":       ["python3", "main.py", "-A", "-odds", "betmgm", "-props"],
    "archive-props":   ["./scripts/archive_props.sh"],
    "label-last-game": ["./scripts/label_last_game.sh"],
    "retrain-model":   ["./scripts/train_props.sh"],
}

# Prevent concurrent processes — one pipeline step at a time.
_process_lock = threading.Lock()

app = Flask(__name__)
app.jinja_env.add_extension("jinja2.ext.loopcontrols")


@app.route("/")
def index():
    teams = sorted(team_abbreviations.keys())
    return render_template("dashboard.html", today=date.today(), teams=teams)


@app.route("/stream/<action>")
def stream(action):
    if action not in ACTIONS:
        return "Unknown action", 404

    cmd = list(ACTIONS[action])  # copy so we don't mutate the dict

    # pull-props: optional date / home / away from the inline form
    if action == "pull-props":
        d    = request.args.get("date", "").strip()
        home = request.args.get("home", "").strip()
        away = request.args.get("away", "").strip()
        if d:    cmd += ["--date", d]
        if home: cmd += ["--home", home]
        if away: cmd += ["--away", away]

    # run-model: optional date override + always point at the default props CSV
    if action == "run-model":
        d = request.args.get("date", "").strip()
        if d:
            cmd += ["--date", d]
        cmd += ["-props-csv", "tmp_data/props.csv"]

    # Return a 200 SSE error event rather than HTTP 409 so the browser
    # EventSource receives it cleanly.
    if not _process_lock.acquire(blocking=False):
        def _busy():
            yield "data: [error] Another process is already running — wait for it to finish.\n\n"
        return Response(stream_with_context(_busy()), mimetype="text/event-stream")

    def generate():
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                yield f"data: {line.rstrip()}\n\n"
            proc.wait()
            yield f"data: [EXIT:{proc.returncode}]\n\n"
        except Exception as exc:
            yield f"data: [error] {exc}\n\n"
        finally:
            _process_lock.release()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Existing player/team data routes — untouched ─────────────────────────────

def get_player_data(team_abv):
    url = "https://tank01-fantasy-stats.p.rapidapi.com/getNBATeamRoster"
    headers = {
        "x-rapidapi-key": "a0f0cd0b5cmshfef96ed37a9cda6p1f67bajsnfcdd16f37df8",
        "x-rapidapi-host": "tank01-fantasy-stats.p.rapidapi.com",
    }
    try:
        response = requests.get(url, headers=headers, params={"teamAbv": team_abv})
        data = response.json()
        if data.get("statusCode") == 200:
            formatted_players = []
            for player in data.get("body", {}).get("roster", []):
                injury_status = "Healthy"
                if player.get("injury"):
                    info = player["injury"]
                    if info.get("designation"):
                        injury_status = info["designation"]
                        if info.get("description"):
                            injury_status += f" - {info['description']}"
                formatted_players.append({
                    "name": player.get("longName"),
                    "shortName": player.get("shortName"),
                    "headshot": player.get("nbaComHeadshot"),
                    "injury": injury_status,
                    "position": player.get("pos"),
                    "height": player.get("height"),
                    "weight": player.get("weight"),
                    "college": player.get("college"),
                    "experience": player.get("exp"),
                    "jerseyNum": player.get("jerseyNum"),
                    "playerId": player.get("playerID"),
                    "birthDate": player.get("bDay"),
                })
            return {"success": True, "players": formatted_players}
        return {"success": False, "error": "Failed to fetch team data"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.route("/team-data/<team_name>")
def team_data(team_name):
    team_abv = team_abbreviations.get(team_name)
    if not team_abv:
        return jsonify({"success": False, "error": f"Team abbreviation not found for {team_name}"})
    return jsonify(get_player_data(team_abv))


@app.route("/player-stats/<player_id>")
def player_stats(player_id):
    headers = {
        "x-rapidapi-key": "a0f0cd0b5cmshfef96ed37a9cda6p1f67bajsnfcdd16f37df8",
        "x-rapidapi-host": "tank01-fantasy-stats.p.rapidapi.com",
    }
    try:
        info_r  = requests.get(
            "https://tank01-fantasy-stats.p.rapidapi.com/getNBAPlayerInfo",
            headers=headers, params={"playerID": player_id},
        )
        games_r = requests.get(
            "https://tank01-fantasy-stats.p.rapidapi.com/getNBAGamesForPlayer",
            headers=headers, params={"playerID": player_id, "season": "2024"},
        )
        info_d  = info_r.json()
        games_d = games_r.json()
        if info_d.get("statusCode") == 200 and games_d.get("statusCode") == 200:
            games = list(games_d["body"].values())
            games.sort(key=lambda x: x["gameID"], reverse=True)
            pi = info_d["body"]
            return jsonify({
                "success": True,
                "games": games[:10],
                "player": {
                    "name": pi.get("longName"), "position": pi.get("pos"),
                    "number": pi.get("jerseyNum"), "height": pi.get("height"),
                    "weight": pi.get("weight"), "team": pi.get("team"),
                    "college": pi.get("college"), "experience": pi.get("exp"),
                    "headshot": pi.get("nbaComHeadshot"),
                    "injury": pi.get("injury", "Healthy"),
                },
            })
        return jsonify({"success": False, "error": "Failed to fetch player data"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


team_abbreviations = {
    "Orlando Magic": "ORL", "Minnesota Timberwolves": "MIN", "Miami Heat": "MIA",
    "Boston Celtics": "BOS", "LA Clippers": "LAC", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Atlanta Hawks": "ATL", "Cleveland Cavaliers": "CLE",
    "Toronto Raptors": "TOR", "Washington Wizards": "WAS", "Phoenix Suns": "PHO",
    "San Antonio Spurs": "SA", "Chicago Bulls": "CHI", "Charlotte Hornets": "CHA",
    "Philadelphia 76ers": "PHI", "New Orleans Pelicans": "NO", "Sacramento Kings": "SAC",
    "Dallas Mavericks": "DAL", "Houston Rockets": "HOU", "Brooklyn Nets": "BKN",
    "New York Knicks": "NY", "Utah Jazz": "UTA", "Oklahoma City Thunder": "OKC",
    "Portland Trail Blazers": "POR", "Indiana Pacers": "IND", "Milwaukee Bucks": "MIL",
    "Golden State Warriors": "GS", "Memphis Grizzlies": "MEM", "Los Angeles Lakers": "LAL",
}


# ── New: Lines analysis dashboard (/dashboard/lines) ─────────────────────────
# Self-contained addition — does not touch the SSE pipeline, ACTIONS dict, or
# any existing route/template logic above.

import re
import sys
from datetime import datetime

try:
    # Flask is conventionally launched from inside Flask/ (see scripts/run-flask.sh),
    # so the project root — and therefore the `src` package — isn't on sys.path yet.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.Utils import LinesFormatter
except ImportError:
    LinesFormatter = None

MANUAL_LINES_PATH = PROJECT_ROOT / "tmp_data" / "manual_lines.json"

_LINES_MARKET_KEYS = (
    "moneyline", "spread", "halftime_fulltime", "matchbet_total",
    "overtime", "winning_margin_home", "odd_even", "race_to_x_home",
)

_TABLE_HEADER_MARKER = "Player/Team"
_TABLE_DIVIDER_RE = re.compile(r"^-{5,}$")

# Matches XGBoost/NN moneyline rows so we can extract team win probability.
_ML_EVENT_RE = re.compile(r"^\[[^\]]+\]\s+ML\s")

# Per-token validators used by _split_table_row to detect 7-col vs 4-col format.
_T_ODDS  = re.compile(r"^(N/A|[+-]?\d+)$")
_T_EV    = re.compile(r"^(—|[+-]?\d+\.\d+)$")
_T_CONF  = re.compile(r"^(—|\d+\.\d+)$")
_T_KELLY = re.compile(r"^(—|\d+\.\d+%)$")
_T_WBV   = re.compile(r"^-?\d+\.\d+$")


def _split_table_row(line):
    """
    Splits an Output_Formatter row on ' | ' and validates the trailing tokens
    so that event fields containing ' | ' (e.g. team ML rows) parse correctly.

    7-column: team | <event> | odds | ev | conf | kelly | wbv  (last 5 fixed)
    4-column: team | <event> | odds | wbv                      (last 2 fixed)
    """
    tokens = [t.strip() for t in line.split(" | ")]
    n = len(tokens)

    if n >= 7:
        odds_raw, ev_raw, conf_raw, kelly_raw, wbv_raw = (
            tokens[-5], tokens[-4], tokens[-3], tokens[-2], tokens[-1]
        )
        if (_T_ODDS.match(odds_raw) and _T_EV.match(ev_raw)
                and _T_CONF.match(conf_raw) and _T_KELLY.match(kelly_raw)
                and _T_WBV.match(wbv_raw)):
            return {
                "team_or_player": tokens[0],
                "event":          " | ".join(tokens[1:-5]),
                "odds":           None if odds_raw == "N/A" else int(odds_raw),
                "ev":             _parse_dash_float(ev_raw),
                "confidence":     _parse_dash_float(conf_raw),
                "kelly":          _parse_dash_percent(kelly_raw),
                "wbv":            float(wbv_raw),
            }

    if n >= 4:
        odds_raw, wbv_raw = tokens[-2], tokens[-1]
        if _T_ODDS.match(odds_raw) and _T_WBV.match(wbv_raw):
            return {
                "team_or_player": tokens[0],
                "event":          " | ".join(tokens[1:-2]),
                "odds":           None if odds_raw == "N/A" else int(odds_raw),
                "ev":             None,
                "confidence":     None,
                "kelly":          None,
                "wbv":            float(wbv_raw),
            }

    return None


def _parse_dash_float(raw):
    return None if raw is None or raw.strip() == "—" else float(raw.strip())


def _parse_dash_percent(raw):
    if raw is None or raw.strip() == "—":
        return None
    return float(raw.strip().rstrip("%"))


def _wbv_class(wbv):
    if wbv is None:
        return "wbv-na"
    if wbv >= 5.5:
        return "wbv-high"
    if wbv >= 4:
        return "wbv-mid"
    return "wbv-low"


app.jinja_env.globals["wbv_class"] = _wbv_class


def _parse_ranked_bets(stdout):
    """
    Parses the ranked-bets table from Output_Formatter.print_ranked_table stdout.
    Uses _split_table_row (split on ' | ', validate tail tokens) so event fields
    that contain ' | ' — e.g. team ML rows — are handled without regex backtracking.
    Supports both the current 7-column format and the legacy 4-column format.
    Malformed lines are silently skipped.
    """
    lines = stdout.splitlines()
    header_idx = next((i for i, line in enumerate(lines) if _TABLE_HEADER_MARKER in line), None)
    if header_idx is None:
        return []

    rows = []
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if _TABLE_DIVIDER_RE.match(stripped):
            if rows:
                break
            continue
        result = _split_table_row(line.rstrip())
        if result:
            rows.append(result)
    return rows


def _run_ranked_bets():
    """Shells out to main.py exactly like the 'run-model' SSE action, synchronously."""
    cmd = ["python3", "main.py", "-A", "-odds", "betmgm", "-props", "-props-csv", "tmp_data/props.csv"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return _parse_ranked_bets(proc.stdout)


@app.route("/dashboard/lines")
def lines_dashboard():
    lines_data = LinesFormatter.load_manual_lines(str(MANUAL_LINES_PATH)) if LinesFormatter else None
    game = (lines_data or {}).get("game", {})
    raw_markets = (lines_data or {}).get("markets", {})

    model_results = _run_ranked_bets() if LinesFormatter else []
    model_available = bool(model_results)

    # Extract home-team win probability from ML rows in the top-10.
    # Either team's ML row works — if it's the away team row, flip 1-p to get
    # home win probability. Falls back to None when no ML row ranks in the top 10.
    home_team = game.get("home")
    away_team = game.get("away")
    model_prob = confidence = None
    if model_results and (home_team or away_team):
        ml_rows = [
            r for r in model_results
            if r.get("confidence") is not None
            and _ML_EVENT_RE.match(r.get("event", ""))
            and r.get("team_or_player") in (home_team, away_team)
        ]
        if ml_rows:
            best = max(ml_rows, key=lambda r: r.get("wbv", 0.0))
            raw_conf = best["confidence"]
            if best["team_or_player"] == home_team:
                model_prob = confidence = raw_conf
            else:
                model_prob = confidence = 1.0 - raw_conf

    if LinesFormatter:
        # Build per-item probability list for moneyline: home selection gets
        # home_prob, away selection gets (1 - home_prob). None when no model.
        ml_items = raw_markets.get("moneyline", [])
        if model_prob is not None:
            ml_probs = [
                model_prob if item.get("label") == home_team else (1.0 - model_prob)
                for item in ml_items
            ]
        else:
            ml_probs = None

        markets = {
            "moneyline":          LinesFormatter.enrich_market(ml_items,                                  ml_probs,   ml_probs),
            "spread":             LinesFormatter.enrich_market(raw_markets.get("spread", []),             None, None),
            "halftime_fulltime":  LinesFormatter.enrich_market(raw_markets.get("halftime_fulltime", []),  None, None),
            "matchbet_total":     LinesFormatter.enrich_market(raw_markets.get("matchbet_total", []),     None, None),
            "overtime":           LinesFormatter.enrich_market(raw_markets.get("overtime", []),           None, None),
            "winning_margin_home":LinesFormatter.enrich_market(raw_markets.get("winning_margin_home", []),None, None),
            "odd_even":           LinesFormatter.enrich_market(raw_markets.get("odd_even", []),           None, None),
            "race_to_x_home":     LinesFormatter.enrich_market(raw_markets.get("race_to_x_home", []),    None, None),
        }
    else:
        markets = {key: [] for key in _LINES_MARKET_KEYS}

    return render_template(
        "lines_dashboard.html",
        game=game,
        markets=markets,
        model_results=model_results,
        model_available=model_available,
        lines_loaded=lines_data is not None,
        generated_at=datetime.now(),
    )
