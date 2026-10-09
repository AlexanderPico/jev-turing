"""Live JEV client for Vercel AI Gateway's ``/v1/evaluate`` endpoint.

Documented contract (Vercel "Evaluation" docs, checked 2026-10-08)::

    POST https://ai-gateway.vercel.sh/v1/evaluate
    {"model": "typesafe-ai/jev", "state": "...",
     "questions": {"<id>": {"type": "boolean", "instructions": "...",
                            "criteria": {"true": "...", "false": "..."}}}}
    -> {"answers": {"<id>": {"type": "boolean", "probability": P(true)}}, ...}

Mapping into this repo's envelope is mechanical and invents nothing:
``probabilities = {"true": P, "false": 1 - P}``, ``choice = "true"`` iff
``P >= 0.5`` (the same threshold the AI SDK / TanStack clients use).

What is sent: the spec's question text and its true/false definitions, plus
the named input bits as state. The spec's ``rule`` table is NEVER sent: the
model has to work out the answer, not look it up.

Safety: nothing here runs unless a caller constructs the client. The API key
is read lazily, on the first real request, from the environment or
``~/.hermes/.env`` and is never logged. ``transport`` can be injected so tests
never touch the network. No retries, no fallback models.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .backend import FALSE_ID, TRUE_ID

ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
MODEL = "typesafe-ai/jev"
KEY_NAME = "JEV_AI_GATEWAY_API_KEY"
QUESTION_ID = "answer"

# transport(payload) -> (http_status, parsed_json_or_text)
Transport = Callable[[dict[str, Any]], tuple[int, Any]]


class LiveCallError(RuntimeError):
    """A live request did not produce a usable answer. Callers should stop."""

    def __init__(self, category: str, detail: str):
        super().__init__("{}: {}".format(category, detail))
        self.category = category
        self.detail = detail


def _read_key() -> str:
    key = os.environ.get(KEY_NAME)
    if key:
        return key
    env = Path.home() / ".hermes" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name == KEY_NAME:
                return value.strip().strip('"').strip("'")
    raise LiveCallError("auth", "{} is not configured".format(KEY_NAME))


def http_transport(timeout_s: float = 30.0) -> Transport:
    def send(payload: dict[str, Any]) -> tuple[int, Any]:
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + _read_key(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, body[:2000]
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LiveCallError("transport", str(getattr(exc, "reason", exc))) from exc
    return send


def render_state(selected_fields: dict[str, Any]) -> str:
    return "; ".join("{}={}".format(k, "true" if v else "false") for k, v in selected_fields.items())


def build_payload(selected_fields: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    cats = {c["id"]: c["definition"] for c in spec["categories"]}
    return {
        "model": MODEL,
        "state": render_state(selected_fields),
        "questions": {QUESTION_ID: {
            "type": "boolean",
            "instructions": spec["question"]["text"],
            "criteria": {"true": cats[TRUE_ID], "false": cats[FALSE_ID]},
        }},
    }


def parse_answer(status: int, body: Any) -> float:
    """Return P(true) or raise LiveCallError with a stop category."""
    if status != 200:
        category = {401: "auth", 402: "payment", 403: "access", 429: "rate_limit"}.get(status, "http")
        raise LiveCallError(category, "HTTP {}: {}".format(status, json.dumps(body)[:500]))
    try:
        ans = body["answers"][QUESTION_ID]
        p = ans["probability"]
    except (TypeError, KeyError) as exc:
        raise LiveCallError("schema", "missing answers.{}.probability".format(QUESTION_ID)) from exc
    if ans.get("type") not in (None, "boolean") or type(p) not in (int, float) or not 0 <= p <= 1:
        raise LiveCallError("schema", "invalid boolean answer: {!r}".format(ans))
    return float(p)


def _gateway(body: Any) -> dict[str, Any]:
    meta = body.get("providerMetadata") if isinstance(body, dict) else None
    gw = meta.get("gateway") if isinstance(meta, dict) else None
    return gw if isinstance(gw, dict) else {}


def extract_cost(body: Any) -> float | None:
    """Gateway-reported cost in USD, if the response carries one."""
    try:
        cost = body["providerMetadata"]["gateway"]["cost"]
    except (TypeError, KeyError):
        return None
    try:
        return float(cost)
    except (TypeError, ValueError):
        return None


class JevGatewayClient:
    """``client(selected_fields, spec) -> envelope`` for :class:`backend.JevAdapter`.

    The last raw exchange is kept on ``self.last`` so a runner can archive it.
    """

    # Only "the request never reached a model" errors are retried: host busy or a
    # gateway/transport hiccup. A wrong answer is never retried.
    BUSY_STATUSES = (429, 502, 503, 504)

    def __init__(self, transport: Transport | None = None, *, provider: str | None = None,
                 busy_retries: int = 0, backoff_s: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self._transport = transport or http_transport()
        self._provider = provider
        self._busy_retries = busy_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self.last: dict[str, Any] = {}

    def __call__(self, selected_fields: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
        payload = build_payload(selected_fields, spec)
        if self._provider:
            # Pin one host; no silent cross-provider fallback inside a measurement.
            payload["providerOptions"] = {"gateway": {"only": [self._provider]}}
        self.last = {"payload": payload, "busy_retries": 0}
        attempt = 0
        while True:
            start = time.perf_counter()
            try:
                status, body = self._transport(payload)
            except LiveCallError as exc:
                if exc.category != "transport" or attempt >= self._busy_retries:
                    raise
                status, body = -1, str(exc)
            if status not in self.BUSY_STATUSES + (-1,) or attempt >= self._busy_retries:
                break
            attempt += 1
            self.last["busy_retries"] = attempt
            self._sleep(self._backoff_s * 2 ** (attempt - 1))
        if status == -1:
            raise LiveCallError("transport", str(body))
        self.last.update(status=status, response=body,
                         latency_ms=round((time.perf_counter() - start) * 1000.0, 1),
                         cost_usd=extract_cost(body) if status == 200 else None)
        p_true = parse_answer(status, body)
        choice = TRUE_ID if p_true >= 0.5 else FALSE_ID
        return {
            "choice": choice,
            "probabilities": {TRUE_ID: p_true, FALSE_ID: 1.0 - p_true},
            "provenance": {"mode": "live", "provider": "vercel-ai-gateway", "model": MODEL,
                           "generation_id": _gateway(body).get("generationId") or body.get("generationId"),
                           "final_provider": _gateway(body).get("routing", {}).get("finalProvider")},
        }
