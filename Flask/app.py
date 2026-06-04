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
