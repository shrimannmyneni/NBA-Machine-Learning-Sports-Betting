import re

import pytest

from src.Utils.Expected_Value import expected_value
from src.Utils.Ranker import rank_bets
from src.Utils.ts import ts
from src.Utils.Weighted_Bet_Value import weighted_bet_value


def test_weighted_bet_value_formula():
    # 10*0.4 + 0.6*0.4 + 3.0*0.2 = 4.0 + 0.24 + 0.6 = 4.84
    assert weighted_bet_value(10, 0.6, 3.0) == pytest.approx(4.84, abs=1e-4)


def test_weighted_bet_value_zero_inputs():
    assert weighted_bet_value(0, 0, 0) == 0.0


def test_ranker_returns_top_n(sample_bets):
    result = rank_bets(sample_bets, top_n=3)
    assert len(result) == 3


def test_ranker_sorted_descending(sample_bets):
    result = rank_bets(sample_bets, top_n=5)
    scores = [b["weighted_value"] for b in result]
    assert scores == sorted(scores, reverse=True)


def test_ranker_top_n_zero_returns_all(sample_bets):
    # Desired behaviour: top_n=0 means "no limit — return all".
    # NOTE: the current implementation uses [:0] which returns [].
    # This test will fail until rank_bets adds a special case for top_n=0.
    result = rank_bets(list(sample_bets), top_n=0)
    assert len(result) == len(sample_bets)


def test_ts_helper_format():
    result = ts("hello")
    assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] hello$", result)


def test_expected_value_positive_odds():
    # Pwin=0.5, +150: payout=150, EV = 0.5*150 - 0.5*100 = 25.0
    assert expected_value(0.5, 150) == pytest.approx(25.0)


def test_expected_value_negative_odds():
    # Pwin=0.65, -150: payout=66.67, EV = 0.65*66.67 - 0.35*100 ≈ 8.33
    assert expected_value(0.65, -150) == pytest.approx(8.33, abs=0.01)
