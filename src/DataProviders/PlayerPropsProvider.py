"""
Parses a CSV produced by the Perplexity → Claude formatting pipeline.

Required CSV columns:
    Player, Team, Opponent, PropType, Line, Odds, Sportsbook

Optional CSV columns:
    Direction  — "OVER" or "UNDER" (defaults to "OVER" if absent)
    ModelProb  — float 0-1 model win probability for this prop (used by
                 PlayerProps_Runner to compute EV without a trained model)

Returns a dict keyed as "{Player} {Direction} {Line} {PropType}", e.g.:
    "Wemby OVER 21.5 Points": {
        "odds": 100, "line": 21.5, "player": "Wemby", "prop": "Points",
        "team": "Spurs", "opponent": "Knicks", "direction": "OVER",
        "sportsbook": "FanDuel", "model_prob": None
    }
"""

import csv
import io
from pathlib import Path


def parse_props_csv(source):
    """
    source: CSV string, file-like object, or path-like object pointing to a CSV file.
    Returns dict as described in the module docstring.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.exists():
            text = path.read_text()
        else:
            text = source
    else:
        text = source.read()

    result = {}
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        player = row["Player"].strip()
        team = row["Team"].strip()
        opponent = row["Opponent"].strip()
        prop_type = row["PropType"].strip()
        line = float(row["Line"])
        odds = int(row["Odds"])
        sportsbook = row["Sportsbook"].strip()
        direction = row.get("Direction", "OVER").strip().upper() or "OVER"
        raw_prob = row.get("ModelProb", "").strip()
        model_prob = float(raw_prob) if raw_prob else None

        key = f"{player} {direction} {line} {prop_type}"
        result[key] = {
            "odds": odds,
            "line": line,
            "player": player,
            "prop": prop_type,
            "team": team,
            "opponent": opponent,
            "direction": direction,
            "sportsbook": sportsbook,
            "model_prob": model_prob,
        }

    return result
