"""CappedLiveJev with a fake transport: caps, ledger, stop-on-failure. No network."""
import json

import pytest

from jev_turing.gates import NAND, xor_from_nands
from jev_turing.live_backend import BudgetExhausted, CappedLiveJev
from jev_turing.live_client import LiveCallError


def transport(cost=1e-5, fail_at=None):
    sent = []

    def send(payload):
        sent.append(payload)
        if fail_at is not None and len(sent) == fail_at:
            return 429, {"error": {"type": "rate_limit_exceeded", "message": "busy"}}
        state = payload["state"]
        bits = dict(part.split("=") for part in state.split("; "))
        p = 0.02 if all(v == "true" for v in bits.values()) else 0.99  # an honest NAND
        return 200, {"answers": {"answer": {"type": "boolean", "probability": p}},
                     "providerMetadata": {"gateway": {"cost": str(cost), "generationId": "g{}".format(len(sent)),
                                                      "routing": {"finalProvider": "typesafe-ai"}}}}
    send.sent = sent
    return send


def test_composes_logs_and_never_sends_rule(tmp_path):
    t = transport()
    b = CappedLiveJev(max_calls=10, max_usd=1, ledger_path=tmp_path / "l.jsonl", transport=t)
    r = xor_from_nands(b, True, False)
    assert r["out"] is True and r["internal_errors"] == 0
    lines = [json.loads(x) for x in (tmp_path / "l.jsonl").read_text().splitlines()]
    assert len(lines) == 4 and all(x["status"] == "ok" and x["provider"] == "typesafe-ai" for x in lines)
    assert all("rule" not in json.dumps(p) for p in t.sent)
    assert b.status()["spent_usd"] == pytest.approx(4e-5)


def test_call_cap_and_usd_cap(tmp_path):
    b = CappedLiveJev(max_calls=2, max_usd=1, ledger_path=tmp_path / "a.jsonl", transport=transport())
    NAND(b, True, True); NAND(b, True, True)
    with pytest.raises(BudgetExhausted):
        NAND(b, True, True)
    b2 = CappedLiveJev(max_calls=99, max_usd=0.00025, reserve_usd_per_call=0.0001,
                       ledger_path=tmp_path / "b.jsonl", transport=transport(cost=0.0001))
    NAND(b2, False, False); NAND(b2, False, False)
    with pytest.raises(BudgetExhausted):
        NAND(b2, False, False)
    assert b2.call_count == 2


def test_failure_stops_and_is_logged(tmp_path):
    b = CappedLiveJev(max_calls=9, max_usd=1, ledger_path=tmp_path / "f.jsonl", transport=transport(fail_at=2),
                      busy_retries=0)
    NAND(b, True, True)
    with pytest.raises(LiveCallError):
        NAND(b, True, True)
    last = json.loads((tmp_path / "f.jsonl").read_text().splitlines()[-1])
    assert last["status"] == "failed" and b.failures == 1


def test_busy_host_is_retried_but_answers_never_are(tmp_path):
    waits = []
    b = CappedLiveJev(max_calls=9, max_usd=1, ledger_path=tmp_path / "r.jsonl", transport=transport(fail_at=2),
                      sleep=waits.append)
    NAND(b, True, True)
    assert NAND(b, True, True) is False  # 429 once, then answered
    rec = json.loads((tmp_path / "r.jsonl").read_text().splitlines()[-1])
    assert rec["status"] == "ok" and rec["busy_retries"] == 1 and waits == [2.0]
    assert b.call_count == 2 and b.status()["busy_retries"] == 1


def test_busy_retries_run_out(tmp_path):
    def always_busy(payload):
        return 429, {"error": {"type": "rate_limit_exceeded"}}
    waits = []
    b = CappedLiveJev(max_calls=9, max_usd=1, ledger_path=tmp_path / "o.jsonl", transport=always_busy,
                      busy_retries=2, sleep=waits.append)
    with pytest.raises(LiveCallError):
        NAND(b, True, True)
    assert waits == [2.0, 4.0]


def test_refuses_existing_ledger(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("")
    with pytest.raises(FileExistsError):
        CappedLiveJev(max_calls=1, max_usd=1, ledger_path=p, transport=transport())


def test_cli_refuses_live_without_flag(capsys):
    from jev_turing.cli import main
    assert main(["xor", "--backend", "live"]) == 2
    assert "cost money" in capsys.readouterr().err
