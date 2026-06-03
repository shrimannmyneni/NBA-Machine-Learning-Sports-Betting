_COL_TEAM = 26
_COL_EVENT = 50
_COL_ODDS = 8
_COL_WBV = 18


def _odds_str(odds):
    if odds is None:
        return "N/A"
    return f"+{odds}" if odds > 0 else str(odds)


def print_ranked_table(bets):
    header = (
        f"{'Player/Team':<{_COL_TEAM}} | "
        f"{'Event':<{_COL_EVENT}} | "
        f"{'Odds':>{_COL_ODDS}} | "
        f"{'Weighted Bet Value':>{_COL_WBV}}"
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
            f"{bet.get('weighted_value', 0.0):>{_COL_WBV}.4f}"
        )
    print(divider)
