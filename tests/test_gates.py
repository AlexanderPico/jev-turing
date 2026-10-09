import itertools

import pytest

from jev_turing.backend import FakeJEV
from jev_turing.gates import NAND, NOR, NOT, error_budget, gate, theoretical_accuracy, truth_table_accuracy


def test_truth_tables_error_free():
    b = FakeJEV(0.0)
    assert [NOT(b, a) for a in (False, True)] == [True, False]
    for a, c in itertools.product((False, True), repeat=2):
        assert NAND(b, a, c) == (not (a and c))
        assert NOR(b, a, c) == (not (a or c))


@pytest.mark.parametrize("vote,calls", [("none", 1), ("glue", 3), ("jev", 4)])
def test_calls_per_gate(vote, calls):
    b = FakeJEV(0.0)
    gate(b, "NAND", True, False, vote=vote)
    assert b.call_count == calls


def test_composition_feeds_bits_straight_through():
    # XOR from four NANDs; every intermediate is a raw JEV output.
    b = FakeJEV(0.0)
    for x, y in itertools.product((False, True), repeat=2):
        n1 = NAND(b, x, y)
        out = NAND(b, NAND(b, x, n1), NAND(b, y, n1))
        assert out == (x != y)
    assert b.call_count == 16


def test_xor_harness_counts_calls_and_grades_each_gate():
    from jev_turing.gates import xor_accuracy
    r = xor_accuracy(FakeJEV(0.0), 3)
    assert r["accuracy"] == 1.0 and r["jev_calls"] == 48 and r["individual_gate_errors"] == 0
    noisy = xor_accuracy(FakeJEV(0.2, seed=1), 50)
    assert noisy["individual_gate_errors"] > 0 and noisy["accuracy"] < 1.0


def test_harness_error_free_is_perfect():
    r = truth_table_accuracy(FakeJEV(0.0), "NAND", 200)
    assert r["accuracy"] == 1.0 and r["jev_calls"] == 800


def test_harness_noisy_matches_theory_and_glue_vote_helps():
    p = 0.05
    plain = truth_table_accuracy(FakeJEV(p, seed=3), "NAND", 2000)
    voted = truth_table_accuracy(FakeJEV(p, seed=3), "NAND", 2000, vote="glue")
    assert abs(plain["accuracy"] - theoretical_accuracy(p)) < 0.015
    assert abs(voted["accuracy"] - theoretical_accuracy(p, "glue")) < 0.01
    assert voted["accuracy"] > plain["accuracy"]


def test_jev_voter_is_itself_noisy():
    # A noisy majority judge can't beat its own error rate: theory says so too.
    assert theoretical_accuracy(0.05, "jev") < theoretical_accuracy(0.05, "none")
    assert theoretical_accuracy(0.001, "glue") > 0.99999


def test_error_budget():
    b = error_budget(0.001, 10_000)
    assert b["expected_errors"] == pytest.approx(10)
    assert b["p_zero_errors"] < 0.0001
