_COL_TEAM = 26
_COL_EVENT = 50
_COL_ODDS = 8
_COL_EV = 9
_COL_CONF = 10
_COL_KELLY = 8
_COL_WBV = 18


def _odds_str(odds):
    if odds is None:
        return "N/A"
    return f"+{odds}" if odds > 0 else str(odds)


def _ev_str(ev):
    return f"{ev:+.2f}" if ev is not None else "—"


def _confidence_str(confidence):
    return f"{confidence:.3f}" if confidence is not None else "—"


def _kelly_str(kelly):
    return f"{kelly:.2f}%" if kelly is not None else "—"


def print_ranked_table(bets):
    header = (
        f"{'Player/Team':<{_COL_TEAM}} | "
        f"{'Event':<{_COL_EVENT}} | "
        f"{'Odds':>{_COL_ODDS}} | "
        f"{'EV':>{_COL_EV}} | "
        f"{'Confidence':>{_COL_CONF}} | "
        f"{'Kelly':>{_COL_KELLY}} | "
        f"{'Weighted Value':>{_COL_WBV}}"
    )
    divider = "-" * len(header)
    print(divider)
    print(header)
    print(divider)
    for rank, bet in enumerate(bets, start=1):
        model_tag = f"[{bet['model']}] " if bet.get("model") else ""
        event = model_tag + bet.get("event", "")
        print(
            f"{bet['team_or_player']:<{_COL_TEAM}} | "
            f"{event:<{_COL_EVENT}} | "
            f"{_odds_str(bet.get('odds')):>{_COL_ODDS}} | "
            f"{_ev_str(bet.get('ev')):>{_COL_EV}} | "
            f"{_confidence_str(bet.get('confidence')):>{_COL_CONF}} | "
            f"{_kelly_str(bet.get('kelly')):>{_COL_KELLY}} | "
            f"{bet.get('weighted_value', 0.0):>{_COL_WBV}.4f}"
        )
    print(divider)


def print_safe_picks_table(bets):
    print("--- Safe Picks (High Confidence Favored Bets) ---")
    header = (
        f"{'Player/Team':<{_COL_TEAM}} | "
        f"{'Event':<{_COL_EVENT}} | "
        f"{'Odds':>{_COL_ODDS}} | "
        f"{'Safe Pick Value':>{_COL_WBV}}"
    )
    divider = "-" * len(header)
    print(divider)
    print(header)
    print(divider)
    for bet in bets:
        model_tag = f"[{bet['model']}] " if bet.get("model") else ""
        event = model_tag + bet.get("event", "")
        print(
            f"{bet['team_or_player']:<{_COL_TEAM}} | "
            f"{event:<{_COL_EVENT}} | "
            f"{_odds_str(bet.get('odds')):>{_COL_ODDS}} | "
            f"{bet.get('safe_pick_value', 0.0):>{_COL_WBV}.4f}"
        )
    print(divider)
