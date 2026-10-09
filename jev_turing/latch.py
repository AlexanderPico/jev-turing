"""SR latch from two cross-coupled JEV NANDs (active-low inputs).

    Q  = NAND(S_n, Qb)
    Qb = NAND(R_n, Q)

S_n=0 sets (Q=1), R_n=0 resets (Q=0), S_n=R_n=1 holds, and S_n=R_n=0 is the
forbidden input (both outputs go high); it is flagged, not prevented.

Real hardware settles physically. Here the loop is iterated in order (Q, then
Qb, Gauss-Seidel style) until a full pass changes nothing, capped at
``max_passes``. Every gate output comes from one JEV judgment (or a vote, see
:mod:`jev_turing.gates`). The glue only feeds outputs back as inputs and
checks whether the pair stopped changing, which is a control-flow decision
about when to stop, not a logic decision about the stored bit.
"""
from __future__ import annotations

from typing import Any

from .backend import JudgmentBackend
from .gates import CALLS_PER_GATE, NAND


class SRLatch:
    def __init__(self, backend: JudgmentBackend, *, q: bool = False, qb: bool = True,
                 max_passes: int = 8, vote: str = "none"):
        if max_passes < 1:
            raise ValueError("max_passes must be >= 1")
        self.backend = backend
        self.q = q
        self.qb = qb
        self.max_passes = max_passes
        self.vote = vote
        self.jev_calls = 0

    def apply(self, s_n: bool, r_n: bool) -> dict[str, Any]:
        """Drive the active-low inputs and let the loop settle."""
        passes = 0
        converged = False
        calls_before = self.jev_calls
        for passes in range(1, self.max_passes + 1):
            new_q = NAND(self.backend, s_n, self.qb, vote=self.vote)
            new_qb = NAND(self.backend, r_n, new_q, vote=self.vote)
            self.jev_calls += 2 * CALLS_PER_GATE[self.vote]
            unchanged = new_q == self.q and new_qb == self.qb
            self.q, self.qb = new_q, new_qb
            if unchanged:
                converged = True
                break
        return {
            "S_n": s_n, "R_n": r_n,
            "Q": self.q, "Qb": self.qb,
            "passes": passes,
            "jev_calls": self.jev_calls - calls_before,
            "converged": converged,
            "forbidden_input": (not s_n) and (not r_n),
        }

    def set(self) -> dict[str, Any]:
        return self.apply(False, True)

    def reset(self) -> dict[str, Any]:
        return self.apply(True, False)

    def hold(self) -> dict[str, Any]:
        return self.apply(True, True)

    def write(self, bit: bool) -> dict[str, Any]:
        return self.set() if bit else self.reset()


def demo_trace(backend: JudgmentBackend, *, hold_cycles: int = 5, vote: str = "none") -> list[dict[str, Any]]:
    """set -> hold xN -> reset -> hold xN, one record per step."""
    latch = SRLatch(backend, vote=vote)
    trace = []
    for op, n in (("set", 1), ("hold", hold_cycles), ("reset", 1), ("hold", hold_cycles)):
        for _ in range(n):
            rec = getattr(latch, op)()
            rec["op"] = op
            trace.append(rec)
    return trace


def _hold_trial(backend: JudgmentBackend, i: int, hold_cycles: int, vote: str, max_passes: int) -> dict[str, Any]:
    """One write-then-hold trial. Bits alternate 1/0 by trial index."""
    bit = i % 2 == 0
    latch = SRLatch(backend, q=not bit, qb=bit, max_passes=max_passes, vote=vote)
    rec = latch.write(bit)
    out = {"trial": i, "bit": bit, "nonconverged": int(not rec["converged"]),
           "write_fail": rec["Q"] != bit or rec["Q"] == rec["Qb"], "lost": False,
           "hold_fail": False, "invalid_end": False, "trace": [[rec["Q"], rec["Qb"]]]}
    if not out["write_fail"]:
        for _ in range(hold_cycles):
            rec = latch.hold()
            out["nonconverged"] += not rec["converged"]
            out["lost"] = out["lost"] or rec["Q"] != bit or rec["Q"] == rec["Qb"]
            out["trace"].append([rec["Q"], rec["Qb"]])
        out["hold_fail"] = latch.q != bit
        out["invalid_end"] = latch.q == latch.qb
    out["calls"] = latch.jev_calls
    return out


def measure_hold(backend: JudgmentBackend, *, trials: int, hold_cycles: int, vote: str = "none",
                 max_passes: int = 8, workers: int = 1) -> dict[str, Any]:
    """Write a bit, hold it ``hold_cycles`` times, read Q; repeat ``trials`` times.

    Bits alternate 1/0 across trials. A trial counts as a write failure if Q
    is wrong (or the Q/Qb pair is invalid) right after the write, and as a hold
    failure if the write was right but Q is wrong after the holds. ``any_loss``
    additionally counts trials where Q was wrong or Q==Qb after ANY hold cycle,
    even if it later recovered, so final-read success is not mistaken for
    uninterrupted retention.
    """
    def one(i: int) -> dict[str, Any]:
        return _hold_trial(backend, i, hold_cycles, vote, max_passes)

    if workers > 1:
        # Trials are independent latches, so they can run side by side; each trial is serial.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, range(trials)))
    else:
        results = [one(i) for i in range(trials)]
    write_fail = sum(t["write_fail"] for t in results)
    hold_fail = sum(t["hold_fail"] for t in results)
    any_loss = sum(t["lost"] for t in results)
    nonconverged = sum(t["nonconverged"] for t in results)
    invalid_end = sum(t["invalid_end"] for t in results)
    calls = sum(t["calls"] for t in results)
    held_trials = trials - write_fail
    hold_error_rate = hold_fail / held_trials if held_trials else None
    per_cycle = None
    if hold_error_rate is not None and hold_cycles > 0:
        per_cycle = 1.0 - (1.0 - hold_error_rate) ** (1.0 / hold_cycles)
    return {
        "backend": backend.identity,
        "vote": vote,
        "trials": trials,
        "hold_cycles": hold_cycles,
        "write_failures": write_fail,
        "hold_failures": hold_fail,
        "hold_error_rate": hold_error_rate,
        "any_loss_during_hold": any_loss,
        "any_loss_rate": any_loss / held_trials if held_trials else None,
        "per_cycle_hold_error_est": per_cycle,
        "nonconverged_steps": nonconverged,
        "invalid_final_states": invalid_end,
        "jev_calls": calls,
        "trial_results": results,
    }
