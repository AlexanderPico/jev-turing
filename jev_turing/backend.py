"""Pluggable JEV backend: one binary judgment in, one True/False out.

Call shape (mirrors jev-tables)
-------------------------------
jev-tables (a separate, private project) talks to an evaluator
object with a non-empty ``identity`` string and one method::

    evaluator.evaluate(selected_fields: dict, taxonomy: dict)
        -> {"choice": <category id>, "probabilities": {id: p}, "provenance": {k: scalar}}

``taxonomy`` frames the question (``question.text`` plus ``categories[]`` with
stable ``id`` + ``definition``); ``selected_fields`` is the only data the
evaluator sees. The caller validates the result before trusting it
(``decisions.build_decision``) and the live provider is a placeholder that
always raises.

This module keeps that exact shape. A *judgment spec* is a jev-tables-style
taxonomy whose categories are exactly ``"true"`` and ``"false"``, and
:func:`judge` is the only place a result is turned into a Python ``bool``:
``choice == "true"``. That one string comparison is the whole of the glue.

Deliberate differences from jev-tables:

* No ``needs-review`` fallback category. A gate has to commit to a bit, so a
  binary spec has exactly two categories.
* A spec may carry ``rule``: the full input -> answer table that defines the
  judgment, the same role category ``definition`` text plays in jev-tables.
  It is part of the question shown to the judge. A real adapter would render
  it into the prompt; :class:`FakeJEV` reads it directly (that is what makes it
  a fake).
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Mapping, Protocol

SCHEMA_VERSION = "1.0"
TRUE_ID = "true"
FALSE_ID = "false"
BINARY_IDS = (TRUE_ID, FALSE_ID)


class JudgmentError(ValueError):
    """A backend returned something that is not a valid binary judgment."""


class JevNotConfiguredError(RuntimeError):
    """The real-JEV adapter was called without explicit configuration."""


class JudgmentBackend(Protocol):
    """Same protocol as ``jev_tables.decisions.Evaluator``."""

    identity: str

    def evaluate(self, selected_fields: dict[str, Any], taxonomy: dict) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Specs (taxonomy-shaped binary questions)
# ---------------------------------------------------------------------------

def bit_key(selected_fields: Mapping[str, Any], inputs: tuple[str, ...]) -> str:
    """Encode the named input bits as a key like ``"10"``.

    This is bookkeeping (moving bits into a lookup key for the judge's rule
    table and the call log); it never evaluates the judgment.
    """
    out = []
    for name in inputs:
        value = selected_fields[name]
        if not isinstance(value, bool):
            raise JudgmentError("input {!r} must be a bool, got {!r}".format(name, value))
        out.append("1" if value else "0")
    return "".join(out)


def binary_spec(
    spec_id: str,
    question: str,
    inputs: tuple[str, ...],
    rule: Mapping[str, bool],
    *,
    true_definition: str,
    false_definition: str,
    version: int = 1,
) -> dict[str, Any]:
    """Build a jev-tables-style taxonomy for one yes/no judgment."""
    expected_keys = {format(i, "0{}b".format(len(inputs))) for i in range(2 ** len(inputs))}
    if set(rule) != expected_keys:
        raise ValueError("rule must cover every input combination exactly once")
    if not all(isinstance(v, bool) for v in rule.values()):
        raise ValueError("rule values must be bools")
    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_id": spec_id,
        "version": version,
        "question": {"type": "binary_choice", "text": question},
        "inputs": list(inputs),
        "rule": dict(sorted(rule.items())),
        "categories": [
            {"id": TRUE_ID, "definition": true_definition, "label": "True"},
            {"id": FALSE_ID, "definition": false_definition, "label": "False"},
        ],
    }


def validate_spec(spec: Mapping[str, Any]) -> None:
    ids = [c.get("id") for c in spec.get("categories", [])]
    if sorted(ids) != sorted(BINARY_IDS):
        raise JudgmentError("binary spec categories must be exactly 'true' and 'false'")
    if not spec.get("taxonomy_id") or not isinstance(spec.get("inputs"), list):
        raise JudgmentError("spec needs taxonomy_id and inputs")


# ---------------------------------------------------------------------------
# The one place a judgment becomes a bit
# ---------------------------------------------------------------------------

def validate_result(result: Any) -> None:
    """Same checks jev-tables' build_decision applies, narrowed to two ids."""
    if not isinstance(result, dict) or set(result) != {"choice", "probabilities", "provenance"}:
        raise JudgmentError("result must contain exactly choice, probabilities, provenance")
    choice, probs, prov = result["choice"], result["probabilities"], result["provenance"]
    if choice not in BINARY_IDS:
        raise JudgmentError("choice must be 'true' or 'false', got {!r}".format(choice))
    if (
        not isinstance(probs, dict)
        or set(probs) != set(BINARY_IDS)
        or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in probs.values())
    ):
        raise JudgmentError("probabilities must cover true/false with values in [0,1]")
    if abs(sum(probs.values()) - 1.0) > 1e-9:
        raise JudgmentError("probabilities must sum to 1")
    if probs[choice] != max(probs.values()):
        raise JudgmentError("choice must have the maximum probability")
    if not isinstance(prov, dict) or not all(
        isinstance(k, str) and isinstance(v, (str, int, float, bool, type(None))) for k, v in prov.items()
    ):
        raise JudgmentError("provenance must be a scalar-valued object")


def judge_detailed(backend: JudgmentBackend, selected_fields: dict[str, Any],
                   spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Like :func:`judge` but also returns the validated raw result."""
    if not isinstance(getattr(backend, "identity", None), str) or not backend.identity:
        raise JudgmentError("backend must declare a non-empty identity")
    result = backend.evaluate(selected_fields, spec)
    validate_result(result)
    return result["choice"] == TRUE_ID, result


def judge(backend: JudgmentBackend, selected_fields: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Ask the backend ONE binary question and return its answer as a bool.

    Exactly one ``backend.evaluate`` call per invocation. The glue here only
    validates the envelope and maps the string ``"true"`` to ``True``.
    """
    return judge_detailed(backend, selected_fields, spec)[0]


# ---------------------------------------------------------------------------
# Real JEV: adapter stub, disabled unless explicitly configured
# ---------------------------------------------------------------------------

class JevAdapter:
    """Seam for the real JEV decision model. Disabled by default.

    It never reads environment variables, key files, or the network on its own.
    To use it, the caller must pass BOTH ``enabled=True`` and a ``client``
    callable ``client(selected_fields, spec) -> dict`` that returns a
    jev-tables-shaped result. Wiring a client that actually calls JEV (cost,
    rate limits, credentials) is out of scope for this repo and has not been
    done; nothing live has run.
    """

    identity = "jev-unconfigured"

    def __init__(self, client: Callable[[dict, dict], dict] | None = None, *, enabled: bool = False,
                 identity: str = "jev-live"):
        self._client = client
        self._enabled = enabled
        if enabled and client is not None:
            self.identity = identity

    def evaluate(self, selected_fields: dict[str, Any], taxonomy: dict) -> dict[str, Any]:
        if not self._enabled or self._client is None:
            raise JevNotConfiguredError(
                "Live JEV is not configured: pass enabled=True and an explicit client. "
                "This repo performs no network calls and reads no credentials."
            )
        return self._client(selected_fields, taxonomy)


# ---------------------------------------------------------------------------
# FakeJEV: offline, seeded, noisy, fully logged
# ---------------------------------------------------------------------------

class FakeJEV:
    """Offline stand-in for JEV. NOT a JEV result.

    It reads the spec's ``rule`` table to find the intended answer, then flips
    that bit with probability ``error_rate`` (an independent bit-flip channel,
    the simplest noise model; real JEV errors may be input-dependent and
    correlated). Every call is appended to :attr:`calls`.

    ``latency_ms`` in the log is the measured wall-clock time of the fake call
    itself (microseconds of Python), not a model of JEV latency.
    """

    def __init__(self, error_rate: float = 0.0, seed: int | None = None, *, confidence: float = 0.99,
                 keep_log: bool = True):
        if not 0.0 <= error_rate <= 1.0:
            raise ValueError("error_rate must be in [0, 1]")
        if not 0.5 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0.5, 1]")
        self.error_rate = float(error_rate)
        self.seed = seed
        self.confidence = confidence
        self.keep_log = keep_log
        self._rng = random.Random(seed)
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0
        self.flip_count = 0
        self.identity = "fake-jev(p_flip={:g},seed={})".format(self.error_rate, seed)

    def reset_log(self) -> None:
        self.calls.clear()
        self.call_count = 0
        self.flip_count = 0

    def evaluate(self, selected_fields: dict[str, Any], taxonomy: dict) -> dict[str, Any]:
        start = time.perf_counter()
        validate_spec(taxonomy)
        inputs = tuple(taxonomy["inputs"])
        key = bit_key(selected_fields, inputs)
        intended = bool(taxonomy["rule"][key])
        flipped = self._rng.random() < self.error_rate
        output = (not intended) if flipped else intended
        choice = TRUE_ID if output else FALSE_ID
        other = FALSE_ID if output else TRUE_ID
        latency_ms = (time.perf_counter() - start) * 1000.0
        self.call_count += 1
        self.flip_count += int(flipped)
        if self.keep_log:
            self.calls.append({
                "call": self.call_count,
                "spec": taxonomy["taxonomy_id"],
                "inputs": key,
                "output": output,
                "flipped": flipped,
                "latency_ms": round(latency_ms, 4),
            })
        return {
            "choice": choice,
            "probabilities": {choice: self.confidence, other: round(1.0 - self.confidence, 12)},
            "provenance": {"mode": "offline", "provider": "fake-jev", "flipped": flipped,
                           "error_rate": self.error_rate},
        }


def make_backend(name: str, *, error_rate: float = 0.0, seed: int | None = None) -> JudgmentBackend:
    """CLI helper: ``fake`` is the only backend that works out of the box."""
    if name == "fake":
        return FakeJEV(error_rate=error_rate, seed=seed)
    if name == "jev":
        return JevAdapter()  # evaluate() raises JevNotConfiguredError
    raise ValueError("unknown backend: {}".format(name))
