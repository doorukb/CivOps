"""Free checks on the eval data. These never call the API."""

import pytest

from eval.bias_pairs import check_pairs
from eval.missed_escalations import check_cases, wilson


def test_missed_escalation_cases_avoid_tripwire_words():
    assert check_cases() == []


def test_bias_pairs_are_well_formed():
    assert check_pairs() == []


def test_wilson_interval():
    low, high = wilson(5, 10)
    assert (round(low, 3), round(high, 3)) == (0.237, 0.763)

    low, high = wilson(0, 27)  # zero misses is still wide at n=27
    assert low == pytest.approx(0, abs=1e-9) and 0.10 < high < 0.14
