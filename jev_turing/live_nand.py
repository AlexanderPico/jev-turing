"""Bounded live NAND truth-table run: real JEV judgments, every exchange archived.

Design (deliberately small):

* Balanced schedule: ``per_row`` blocks, each containing 00/01/10/11 once,
  shuffled with a fixed local seed (order only; it does not seed the model).
* Serial, one request per gate evaluation, no retries, no fallback, no voting.
* Hard stops: call ceiling, USD ceiling (gateway-reported cost when present,
  otherwise a conservative per-call reserve), and the first failed/invalid
  request of any kind. A valid but WRONG answer is evidence and continues.
* ``attempts.jsonl`` gets a ``pending`` line before each request and a
  terminal line after it, so an interrupted run shows exactly what is unknown.
* The expected bit is computed only by the grader, after the answer returns.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
from statistics import median
from typing import Any

from .backend import JevAdapter, judge_detailed
from .gates import NAND_SPEC, _REFERENCE
from .live_client import JevGatewayClient, LiveCallError, Transport, build_payload

ROWS = ("00", "01", "10", "11")
SCHEMA = "jev-turing/live-nand-run/1"


def schedule(per_row: int, seed: int = 0) -> list[str]:
    if per_row < 1:
        raise ValueError("per_row must be >= 1")
    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(per_row):
        block = list(ROWS)
        rng.shuffle(block)
        out.extend(block)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def run_live_nand(out_dir: str | Path, *, per_row: int, max_calls: int, max_usd: float,
                  reserve_usd_per_call: float, transport: Transport | None = None,
                  seed: int = 0, label: str = "live", busy_retries: int = 0) -> dict[str, Any]:
    """Execute the schedule until done or a stop rule fires. Returns the summary."""
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError("refusing to overwrite existing run directory: {}".format(out))
    out.mkdir(parents=True, mode=0o700)
    order = schedule(per_row, seed)[:max_calls]
    client = JevGatewayClient(transport, busy_retries=busy_retries)
    backend = JevAdapter(client, enabled=True, identity="typesafe-ai/jev via vercel-ai-gateway")
    spec_payload = build_payload({"A": True, "B": True}, NAND_SPEC)["questions"]
    manifest = {
        "schema": SCHEMA, "label": label, "started_utc": _now(),
        "model": "typesafe-ai/jev", "endpoint": "https://ai-gateway.vercel.sh/v1/evaluate",
        "question": spec_payload,
        "question_sha256": hashlib.sha256(json.dumps(spec_payload, sort_keys=True).encode()).hexdigest(),
        "state_format": "A=<true|false>; B=<true|false>",
        "rule_table_sent": False,
        "decision_threshold": "choice=true iff P(true) >= 0.5",
        "per_row": per_row, "schedule_seed": seed, "planned_calls": len(order),
        "caps": {"max_calls": max_calls, "max_usd": max_usd, "reserve_usd_per_call": reserve_usd_per_call,
                 "answer_retries": 0, "busy_host_retries": busy_retries, "concurrency": 1},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    ledger_path = out / "attempts.jsonl"
    ledger_path.touch(mode=0o600)
    ledger = ledger_path.open("a")

    records: list[dict[str, Any]] = []
    spent = 0.0
    cost_known = True
    stop = "completed"
    for i, row in enumerate(order, start=1):
        reserve = reserve_usd_per_call
        if spent + reserve > max_usd:
            stop = "budget_reserve_exhausted"
            break
        a, b = row[0] == "1", row[1] == "1"
        ledger.write(json.dumps({"attempt": i, "status": "pending", "row": row, "t": _now()}) + "\n")
        ledger.flush()
        rec: dict[str, Any] = {"attempt": i, "row": row}
        try:
            out_bit, env = judge_detailed(backend, {"A": a, "B": b}, NAND_SPEC)
        except LiveCallError as exc:
            rec.update(status="failed", error=exc.category, detail=exc.detail[:500])
            stop = "stopped_on_" + exc.category
        except Exception as exc:  # envelope validation or anything unexpected
            rec.update(status="failed", error="invalid", detail=repr(exc)[:500])
            stop = "stopped_on_invalid"
        else:
            expected = _REFERENCE["NAND"](a, b)  # grading only, after the answer exists
            rec.update(status="ok", p_true=env["probabilities"]["true"], out=out_bit,
                       expected=expected, correct=out_bit == expected,
                       generation_id=env["provenance"].get("generation_id"),
                       final_provider=env["provenance"].get("final_provider"))
        last = client.last
        rec.update(t=_now(), http_status=last.get("status"), latency_ms=last.get("latency_ms"),
                   busy_retries=last.get("busy_retries", 0),
                   cost_usd=last.get("cost_usd"), response=last.get("response"))
        routing = ((rec["response"] or {}).get("providerMetadata", {}) if isinstance(rec["response"], dict)
                   else {}).get("gateway", {}).get("routing", {})
        rec["resolved_provider"] = routing.get("resolvedProvider")
        rec["provider_attempts"] = routing.get("totalProviderAttemptCount")
        if rec["cost_usd"] is not None:
            spent += rec["cost_usd"]
        elif rec["status"] == "ok" or rec["provider_attempts"] != 0:
            # No receipt and the request may have reached a model: assume the reserve.
            cost_known = False
            spent += reserve
        ledger.write(json.dumps(rec) + "\n")
        ledger.flush()
        records.append(rec)
        if rec["status"] != "ok":
            break
    ledger.close()

    summary = summarize(records, planned=len(order), stop=stop, spent=spent, cost_known=cost_known)
    manifest["ended_utc"] = _now()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for f in out.iterdir():
        f.chmod(0o600)
    return summary


def summarize(records: list[dict[str, Any]], *, planned: int, stop: str, spent: float,
              cost_known: bool) -> dict[str, Any]:
    ok = [r for r in records if r["status"] == "ok"]
    rows = {}
    for row in ROWS:
        rr = [r for r in ok if r["row"] == row]
        k = sum(r["correct"] for r in rr)
        ps = [r["p_true"] for r in rr]
        rows[row] = {"expected": _REFERENCE["NAND"](row[0] == "1", row[1] == "1"),
                     "correct": k, "valid": len(rr), "wilson95": wilson(k, len(rr)),
                     "p_true_min": min(ps) if ps else None, "p_true_max": max(ps) if ps else None}
    lat = sorted(r["latency_ms"] for r in ok if r.get("latency_ms") is not None)
    gen_ids = [r.get("generation_id") for r in ok if r.get("generation_id")]
    k_all = sum(r["correct"] for r in ok)
    return {
        "planned": planned, "attempted": len(records), "valid": len(ok),
        "failed": len(records) - len(ok), "stop_reason": stop,
        "correct": k_all, "accuracy_valid": k_all / len(ok) if ok else None,
        "wilson95_valid": wilson(k_all, len(ok)),
        "rows": rows,
        "latency_ms": {"n": len(lat), "median": median(lat) if lat else None,
                       "p95": lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)] if lat else None},
        "cost_usd": spent, "cost_is_gateway_reported": cost_known,
        "providers": dict(Counter(r.get("final_provider") or r.get("resolved_provider") for r in ok)),
        "generation_ids_unique": len(set(gen_ids)) == len(gen_ids) if gen_ids else None,
        "caveat": ("Repeated identical prompts may not be independent samples; the interval "
                   "assumes independence and is approximate. A small perfect sample does not "
                   "establish 99.9% reliability."),
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = ["row  expected  correct/valid  P(true) range",]
    for row, r in summary["rows"].items():
        rng = "-" if r["p_true_min"] is None else "{:.3f}..{:.3f}".format(r["p_true_min"], r["p_true_max"])
        lines.append("{}   {:<8}  {:>3}/{:<3}        {}".format(
            row, str(r["expected"]).lower(), r["correct"], r["valid"], rng))
    lines.append("attempted={attempted} valid={valid} failed={failed} stop={stop_reason}".format(**summary))
    lines.append("cost_usd={:.6f} ({})".format(
        summary["cost_usd"], "from gateway receipts; unbilled rejections count as 0"
        if summary["cost_is_gateway_reported"] else "includes reserve estimates for calls without a receipt"))
    if summary.get("providers"):
        lines.append("resolved providers: {}".format(summary["providers"]))
    return "\n".join(lines)

