from jev_turing.backend import FakeJEV
from jev_turing.latch import SRLatch, demo_trace, measure_hold


def test_set_reset_hold_error_free():
    latch = SRLatch(FakeJEV(0.0))
    assert latch.set()["Q"] is True
    for _ in range(10):
        rec = latch.hold()
        assert (rec["Q"], rec["Qb"], rec["converged"]) == (True, False, True)
        assert rec["jev_calls"] == 2
    assert latch.reset()["Q"] is False
    for _ in range(10):
        rec = latch.hold()
        assert (rec["Q"], rec["Qb"]) == (False, True)


def test_forbidden_input_flagged():
    rec = SRLatch(FakeJEV(0.0)).apply(False, False)
    assert rec["forbidden_input"] and rec["Q"] and rec["Qb"]


def test_demo_trace_shape():
    trace = demo_trace(FakeJEV(0.0), hold_cycles=3)
    assert [r["op"] for r in trace] == ["set"] + ["hold"] * 3 + ["reset"] + ["hold"] * 3
    assert all(r["converged"] for r in trace)


def test_hold_error_zero_without_noise():
    m = measure_hold(FakeJEV(0.0), trials=50, hold_cycles=5)
    assert m["write_failures"] == 0 and m["hold_failures"] == 0 and m["hold_error_rate"] == 0


def test_hold_error_measured_under_noise():
    m = measure_hold(FakeJEV(0.02, seed=7), trials=1000, hold_cycles=10)
    assert 0 < m["hold_error_rate"] < 0.5
    voted = measure_hold(FakeJEV(0.02, seed=7), trials=1000, hold_cycles=10, vote="glue")
    assert voted["hold_error_rate"] < m["hold_error_rate"]


def test_any_loss_catches_transient_errors_that_final_read_misses():
    m = measure_hold(FakeJEV(0.05, seed=3), trials=2000, hold_cycles=10)
    assert m["any_loss_during_hold"] >= m["hold_failures"]
    assert m["any_loss_rate"] > m["hold_error_rate"]


def test_any_loss_zero_without_noise():
    m = measure_hold(FakeJEV(0.0), trials=20, hold_cycles=5)
    assert m["any_loss_during_hold"] == 0 and m["any_loss_rate"] == 0
