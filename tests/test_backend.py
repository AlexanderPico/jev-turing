import pytest

from jev_turing.backend import (FakeJEV, JevAdapter, JevNotConfiguredError, JudgmentError, judge,
                                make_backend, validate_result)
from jev_turing.gates import NAND_SPEC


def test_fake_error_free_follows_rule():
    b = FakeJEV(0.0, seed=1)
    assert judge(b, {"A": True, "B": True}, NAND_SPEC) is False
    assert judge(b, {"A": True, "B": False}, NAND_SPEC) is True
    assert b.call_count == 2 and b.flip_count == 0


def test_fake_error_rate_one_always_flips():
    b = FakeJEV(1.0, seed=1)
    assert judge(b, {"A": True, "B": True}, NAND_SPEC) is True
    assert b.calls[-1]["flipped"] is True


def test_fake_seed_reproducible_and_rate_close():
    outs = []
    for _ in range(2):
        b = FakeJEV(0.1, seed=42)
        outs.append([judge(b, {"A": False, "B": False}, NAND_SPEC) for _ in range(5000)])
    assert outs[0] == outs[1]
    rate = outs[0].count(False) / 5000
    assert 0.08 < rate < 0.12


def test_call_log_fields():
    b = FakeJEV(0.0, seed=0)
    judge(b, {"A": False, "B": True}, NAND_SPEC)
    entry = b.calls[0]
    assert set(entry) == {"call", "spec", "inputs", "output", "flipped", "latency_ms"}
    assert entry["inputs"] == "01" and entry["output"] is True and entry["spec"] == "gate-nand"
    assert entry["latency_ms"] >= 0


def test_result_envelope_matches_jev_tables_shape():
    r = FakeJEV(0.0).evaluate({"A": True, "B": True}, NAND_SPEC)
    assert set(r) == {"choice", "probabilities", "provenance"}
    validate_result(r)


def test_validate_rejects_bad_choice():
    with pytest.raises(JudgmentError):
        validate_result({"choice": "maybe", "probabilities": {"true": .5, "false": .5}, "provenance": {}})


def test_inputs_must_be_bools():
    with pytest.raises(JudgmentError):
        judge(FakeJEV(), {"A": 1, "B": 0}, NAND_SPEC)


def test_real_jev_adapter_raises_unless_configured():
    with pytest.raises(JevNotConfiguredError):
        judge(JevAdapter(), {"A": True, "B": True}, NAND_SPEC)
    with pytest.raises(JevNotConfiguredError):
        JevAdapter(client=lambda f, s: {}, enabled=False).evaluate({}, NAND_SPEC)
    with pytest.raises(JevNotConfiguredError):
        make_backend("jev").evaluate({"A": True, "B": True}, NAND_SPEC)


def test_real_jev_adapter_uses_explicit_client_only():
    client = lambda f, s: {"choice": "false", "probabilities": {"true": 0.1, "false": 0.9}, "provenance": {}}
    b = JevAdapter(client=client, enabled=True, identity="test-client")
    assert judge(b, {"A": True, "B": True}, NAND_SPEC) is False
    assert b.identity == "test-client"
