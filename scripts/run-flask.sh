# Everything working. The page serves cleanly and the SSE stream is firing live
#  — June 3 data comes from the cache instantly (no BRef delay), timestamps are appearing,
# and the event_id is correctly resolved.

# To run it yourself:


cd Flask
flask --debug run --port 5001
# Then open http://localhost:5000.

# What each button does:

# ↓ Pull Props — expands a form with date (default today), optional Home/Away fields.
#  Hit Run to stream BettingPros output live.
# ▶ Run Model — streams main.py -A -odds betmgm -props. Ranked bets table auto-renders as HTML when detected.
# ⬇ Archive Props — runs archive_props.sh for today.
# ✓ Label Last Game — runs label_last_game.sh, streams BRef box score scraping live.
# ⟳ Retrain Model — streams all 30 trial log-loss lines from train_props.sh.
# ⌫ Clear — wipes the terminal.
# [warn] lines appear yellow, [error] red, summary → lines in blue, the [done] sentinel in teal. The ranked bets table 
# renders with green highlighting on the Weighted Bet Value column.