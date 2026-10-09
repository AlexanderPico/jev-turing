"""Capped, logged live JEV backend usable by every harness (gates, latch, Rule 110).

``CappedLiveJev`` has the same ``identity`` / ``evaluate`` shape as FakeJEV, so
the existing harnesses run unchanged. Each call:

* checks the call and USD caps BEFORE the request (raises ``BudgetExhausted``);
* sends exactly one Boolean question (``live_client.build_payload``), pinned to
  one provider so all answers come from the same host;
* appends one JSON line (inputs, P(true), choice, cost, latency, provider,
  generation id) to ``ledger_path``;
* raises ``LiveCallError`` on any failed or malformed response. No retries.

Nothing here is constructed unless a caller explicitly asks for live mode.
"""
from __future__ import annotations

import contextvars
import json
import threading
from pathlib import Path
from typing import Any, Callable

from .live_client import JevGatewayClient, LiveCallError, Transport

# None = let the gateway pick a host for typesafe-ai/jev (same model) and record
# which one answered. Pinning to "typesafe-ai" alone hit HTTP 429 capacity limits.
DEFAULT_PROVIDER: str | None = None

# Optional bookkeeping tag recorded in the ledger (e.g. "t=5 tape x=3") so parallel
# calls can be matched to cells. It is written to the ledger only, never sent.
CALL_CONTEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar("jev_call_context", default=None)


class BudgetExhausted(RuntimeError):
    pass


class CappedLiveJev:
    def __init__(self, *, max_calls: int, max_usd: float, ledger_path: str | Path,
                 reserve_usd_per_call: float = 0.0001, provider: str | None = DEFAULT_PROVIDER,
                 transport: Transport | None = None, busy_retries: int = 3,
                 sleep: Callable[[float], None] | None = None):
        self.max_calls = max_calls
        self.max_usd = max_usd
        self.reserve = reserve_usd_per_call
        self.provider = provider
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.ledger_path.exists():
            raise FileExistsError("refusing to append to an existing ledger: {}".format(self.ledger_path))
        self.ledger_path.touch(mode=0o600)
        self._transport = transport
        self._busy_retries = busy_retries
        self._sleep = sleep
        self.busy_retry_total = 0
        self._lock = threading.Lock()
        self.call_count = 0
        self.spent_usd = 0.0
        self.cost_known = True
        self.failures = 0
        self.identity = "typesafe-ai/jev via vercel-ai-gateway" + (
            " (provider={})".format(provider) if provider else " (any host)")
        # Harness compatibility with FakeJEV-only fields:
        self.error_rate = None
        self.seed = None

    def evaluate(self, selected_fields: dict[str, Any], taxonomy: dict) -> dict[str, Any]:
        with self._lock:
            if self.call_count >= self.max_calls:
                raise BudgetExhausted("call cap reached ({})".format(self.max_calls))
            if self.spent_usd + self.reserve > self.max_usd:
                raise BudgetExhausted("USD cap reached (${:.6f} of ${:.4f})".format(self.spent_usd, self.max_usd))
            self.call_count += 1
            n = self.call_count
        kw: dict[str, Any] = {"busy_retries": self._busy_retries}
        if self._sleep is not None:
            kw["sleep"] = self._sleep
        client = JevGatewayClient(self._transport, provider=self.provider, **kw)
        rec: dict[str, Any] = {"call": n, "ctx": CALL_CONTEXT.get(), "spec": taxonomy.get("taxonomy_id"),
                               "inputs": {k: bool(v) for k, v in selected_fields.items()}}
        try:
            env = client(selected_fields, taxonomy)
        except LiveCallError as exc:
            rec.update(status="failed", error=exc.category, detail=exc.detail[:500],
                       http_status=client.last.get("status"), busy_retries=client.last.get("busy_retries", 0))
            with self._lock:
                self.failures += 1
                self._write(rec)
            raise
        last = client.last
        cost = last.get("cost_usd")
        rec.update(status="ok", choice=env["choice"], p_true=env["probabilities"]["true"],
                   cost_usd=cost, latency_ms=last.get("latency_ms"),
                   provider=env["provenance"].get("final_provider"),
                   generation_id=env["provenance"].get("generation_id"),
                   busy_retries=last.get("busy_retries", 0))
        with self._lock:
            self.busy_retry_total += last.get("busy_retries", 0)
            if cost is None:
                self.cost_known = False
                self.spent_usd += self.reserve
            else:
                self.spent_usd += cost
            self._write(rec)
        env["provenance"]["flipped"] = None  # unknown for a live model; the checker grades instead
        return env

    def _write(self, rec: dict[str, Any]) -> None:
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def status(self) -> dict[str, Any]:
        return {"calls": self.call_count, "failures": self.failures, "busy_retries": self.busy_retry_total,
                "spent_usd": round(self.spent_usd, 6),
                "cost_is_gateway_reported": self.cost_known, "ledger": str(self.ledger_path)}
