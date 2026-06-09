import json
import os


def load_manual_lines(path="tmp_data/manual_lines.json"):
    """Loads and validates the manual lines JSON. Returns None if missing/malformed."""
    if not os.path.exists(path):
        print(f"[LinesFormatter] No manual lines file at {path}")
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[LinesFormatter] Could not read {path}: {exc}")
        return None

    if "game" not in data or "markets" not in data:
        print(f"[LinesFormatter] {path} is missing required 'game' or 'markets' keys")
        return None

    return data


def american_to_implied(odds):
    """Converts American odds to implied probability (0-1)."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def american_to_ev(odds, model_prob):
    """Standard EV formula for a $100 stake, given American odds and model win probability."""
    if odds > 0:
        return model_prob * odds - (1 - model_prob) * 100
    return model_prob * (10000 / abs(odds)) - (1 - model_prob) * 100


def kelly_fraction(odds, model_prob):
    """Kelly criterion stake as a percentage of bankroll, floored at 0."""
    if odds > 0:
        b = odds / 100
    else:
        b = 100 / abs(odds)
    f = (b * model_prob - (1 - model_prob)) / b
    return max(0, round(f * 100, 2))


def compute_wbv(ev, confidence, kelly):
    """Weighted bet value: a blend of EV, model confidence, and Kelly stake."""
    return ev * 0.4 + confidence * 0.4 + kelly * 0.2


def enrich_market(market_items, model_prob, confidence):
    """
    Attaches implied_prob, ev, kelly, and wbv to each market item.

    model_prob / confidence accept:
      None              – all items flagged odds_only (no model available)
      float             – same probability applied to every item
      list[float|None]  – per-item probability applied positionally;
                          a None entry in the list flags that item odds_only

    The list form is used for moneyline so each selection gets its own
    team win probability (home_prob vs 1 - home_prob).
    """
    enriched = []
    for i, item in enumerate(market_items):
        mp = model_prob[i] if isinstance(model_prob, list) else model_prob
        cp = confidence[i] if isinstance(confidence, list) else confidence

        out = dict(item)
        odds = out.get("odds")
        out["implied_prob"] = american_to_implied(odds) if odds is not None else None

        if mp is None or odds is None:
            out["model_prob"] = None
            out["ev"] = None
            out["kelly"] = None
            out["wbv"] = None
            out["odds_only"] = True
        else:
            ev = american_to_ev(odds, mp)
            kelly = kelly_fraction(odds, mp)
            out["model_prob"] = mp
            out["ev"] = ev
            out["kelly"] = kelly
            out["wbv"] = compute_wbv(ev, cp if cp is not None else mp, kelly)
            out["odds_only"] = False

        enriched.append(out)
    return enriched
