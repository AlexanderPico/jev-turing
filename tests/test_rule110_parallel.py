"""Parallel prefetch must give exactly the serial run, and tag every live call."""
import json

from jev_turing.cli import attach_live_ledger
from jev_turing.live_backend import CappedLiveJev
from jev_turing.rule110 import JevRule110, reference_rule110


def honest_transport():
    def send(payload):
        bits = dict(p.split("=") for p in payload["state"].split("; "))
        on = reference_rule110(*(bits[k] == "true" for k in "LCR"))
        return 200, {"answers": {"answer": {"type": "boolean", "probability": 0.97 if on else 0.07}},
                     "providerMetadata": {"gateway": {"cost": "0.00001", "routing": {"finalProvider": "typesafe-ai"}}}}
    return send


def test_parallel_matches_serial_and_ledger_merges(tmp_path):
    runs = {}
    for w in (1, 8):
        b = CappedLiveJev(max_calls=10000, max_usd=1, ledger_path=tmp_path / "w{}.jsonl".format(w),
                          transport=honest_transport())
        runs[w] = JevRule110(b, workers=w).run(12).to_dict()
    assert runs[1]["rows"] == runs[8]["rows"]
    assert runs[1]["counters"]["jev_calls"] == runs[8]["counters"]["jev_calls"]
    assert runs[8]["counters"]["local_errors"] == 0
    ledger = [json.loads(x) for x in (tmp_path / "w8.jsonl").read_text().splitlines()]
    assert all(r["ctx"] for r in ledger) and len({r["ctx"] for r in ledger}) == len(ledger)
    merged = attach_live_ledger(json.loads(json.dumps(runs[8])), tmp_path / "w8.jsonl")
    assert merged["call_log"]["columns"][-1] == "p_true"


def test_parallel_stops_on_cap(tmp_path):
    import pytest
    from jev_turing.live_backend import BudgetExhausted
    b = CappedLiveJev(max_calls=30, max_usd=1, ledger_path=tmp_path / "c.jsonl", transport=honest_transport())
    with pytest.raises(BudgetExhausted):
        JevRule110(b, workers=4).run(50)
    assert b.call_count == 30
