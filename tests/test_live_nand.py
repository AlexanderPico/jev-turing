"""Live NAND runner and gateway client, exercised with an injected fake transport."""
import json
from collections import Counter

import pytest

from jev_turing.backend import validate_result
from jev_turing.gates import NAND_SPEC
from jev_turing.live_client import JevGatewayClient, LiveCallError, build_payload, parse_answer
from jev_turing.live_nand import run_live_nand, schedule, wilson


def answering(p_for_row, cost=0.000001):
    """Fake transport: P(true) chosen per input row; records every payload."""
    sent = []

    def send(payload):
        sent.append(payload)
        row = "".join("1" if part.endswith("true") else "0" for part in payload["state"].split("; "))
        return 200, {"answers": {"answer": {"type": "boolean", "probability": p_for_row(row)}},
                     "providerMetadata": {"gateway": {"cost": str(cost), "generationId": "gen-{}".format(len(sent)),
                                                      "routing": {"finalProvider": "typesafe-ai"}}}}
    send.sent = sent
    return send


def correct(row):
    return 0.02 if row == "11" else 0.98


def test_schedule_is_balanced_and_deterministic():
    s = schedule(25, seed=0)
    assert Counter(s) == {"00": 25, "01": 25, "10": 25, "11": 25}
    assert all(sorted(s[i:i + 4]) == ["00", "01", "10", "11"] for i in range(0, 100, 4))
    assert s == schedule(25, seed=0)


def test_payload_sends_question_and_bits_but_never_the_rule_table():
    payload = build_payload({"A": True, "B": False}, NAND_SPEC)
    text = json.dumps(payload)
    assert payload["state"] == "A=true; B=false"
    assert "rule" not in text and '"11"' not in text
    q = payload["questions"]["answer"]
    assert q["type"] == "boolean" and set(q["criteria"]) == {"true", "false"}


def test_mapping_is_honest_and_passes_envelope_validation():
    env = JevGatewayClient(answering(lambda r: 0.73))({"A": False, "B": False}, NAND_SPEC)
    validate_result(env)
    assert env["choice"] == "true" and env["probabilities"]["true"] == 0.73


@pytest.mark.parametrize("status,body,category", [
    (403, {"error": {"message": "Free tier"}}, "access"),
    (429, {}, "rate_limit"),
    (200, {"answers": {}}, "schema"),
    (200, {"answers": {"answer": {"type": "boolean", "probability": 1.5}}}, "schema"),
])
def test_bad_responses_raise_stop_categories(status, body, category):
    with pytest.raises(LiveCallError) as exc:
        parse_answer(status, body)
    assert exc.value.category == category


def test_full_run_counts_and_ledger(tmp_path):
    t = answering(correct)
    s = run_live_nand(tmp_path / "r", per_row=3, max_calls=12, max_usd=0.01, reserve_usd_per_call=0.0001,
                      transport=t)
    assert (s["attempted"], s["valid"], s["correct"], s["stop_reason"]) == (12, 12, 12, "completed")
    lines = [json.loads(x) for x in (tmp_path / "r/attempts.jsonl").read_text().splitlines()]
    assert [x["status"] for x in lines[:2]] == ["pending", "ok"]
    assert len(lines) == 24
    assert s["cost_is_gateway_reported"] and s["cost_usd"] == pytest.approx(12e-6)
    assert s["generation_ids_unique"] is True and s["providers"] == {"typesafe-ai": 12}


def test_wrong_answers_are_counted_not_repaired(tmp_path):
    s = run_live_nand(tmp_path / "r", per_row=2, max_calls=8, max_usd=0.01, reserve_usd_per_call=0.0001,
                      transport=answering(lambda r: 0.9))  # always says true: wrong on 11
    assert s["rows"]["11"]["correct"] == 0 and s["rows"]["00"]["correct"] == 2
    assert s["stop_reason"] == "completed"


def test_first_failure_stops_the_run(tmp_path):
    calls = []

    def flaky(payload):
        calls.append(payload)
        return (403, {"error": "no"}) if len(calls) == 2 else answering(correct)(payload)
    s = run_live_nand(tmp_path / "r", per_row=5, max_calls=20, max_usd=0.01, reserve_usd_per_call=0.0001,
                      transport=flaky)
    assert len(calls) == 2 and s["stop_reason"] == "stopped_on_access" and s["failed"] == 1


def test_budget_reserve_stops_before_overspending(tmp_path):
    t = answering(correct, cost=0.004)
    s = run_live_nand(tmp_path / "r", per_row=5, max_calls=20, max_usd=0.01, reserve_usd_per_call=0.004,
                      transport=t)
    assert len(t.sent) == 2 and s["stop_reason"] == "budget_reserve_exhausted"


def test_rejection_that_reached_no_provider_costs_zero_but_unreceipted_success_uses_reserve(tmp_path):
    def rejected(payload):
        return 403, {"error": "free tier", "providerMetadata": {"gateway": {"routing": {
            "resolvedProvider": "typesafe-ai", "totalProviderAttemptCount": 0}}}}
    s = run_live_nand(tmp_path / "a", per_row=1, max_calls=4, max_usd=1, reserve_usd_per_call=0.5,
                      transport=rejected)
    assert s["cost_usd"] == 0 and s["cost_is_gateway_reported"]

    def no_receipt(payload):
        return 200, {"answers": {"answer": {"type": "boolean", "probability": 0.9}}}
    s = run_live_nand(tmp_path / "b", per_row=1, max_calls=1, max_usd=1, reserve_usd_per_call=0.5,
                      transport=no_receipt)
    assert s["cost_usd"] == 0.5 and not s["cost_is_gateway_reported"]


def test_refuses_to_overwrite(tmp_path):
    (tmp_path / "r").mkdir()
    with pytest.raises(FileExistsError):
        run_live_nand(tmp_path / "r", per_row=1, max_calls=4, max_usd=1, reserve_usd_per_call=0,
                      transport=answering(correct))


def test_wilson_bounds():
    lo, hi = wilson(25, 25)
    assert 0.86 < lo < 0.87 and hi == 1.0
    assert wilson(0, 0) is None
