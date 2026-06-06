import argparse
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def test_cache_key_includes_event_id():
    source = (PROJECT_ROOT / "src/DataProviders/BettingProsProvider.py").read_text()
    # _fetch_offers() must embed event_id in the cache filename to prevent collisions
    # when multiple games share the same date.
    assert re.search(r"cache_path\s*=.*event_id", source), (
        "Cache path in BettingProsProvider._fetch_offers does not include event_id"
    )


def test_auto_bref_id_derivation():
    from src.DataProviders.BRefPlayerStatsProvider import _auto_bref_id
    # last5("wembanyama") = "wemba", first2("victor") = "vi" → "wembavi01"
    assert _auto_bref_id("Victor Wembanyama") == "wembavi01"


def test_auto_bref_id_jr_suffix():
    from src.DataProviders.BRefPlayerStatsProvider import _auto_bref_id
    # "Jr." is stripped; last5("jackson") = "jacks", first2("jaren") = "ja"
    assert _auto_bref_id("Jaren Jackson Jr.") == "jacksja01"


def test_main_exits_cleanly_no_game(mocker, capsys):
    import main as main_module

    mock_sbr = mocker.patch.object(main_module, "SbrOddsProvider")
    mock_sbr.return_value.get_odds.return_value = None

    mock_input = mocker.patch("builtins.input")

    args = argparse.Namespace(
        odds="betmgm",
        props=False,
        xgb=False,
        nn=False,
        A=False,
        kc=False,
        props_csv=None,
        date=None,
    )

    main_module.main(args)

    mock_input.assert_not_called()

    captured = capsys.readouterr()
    assert "No odds returned" in captured.out or "no game" in captured.out.lower()
