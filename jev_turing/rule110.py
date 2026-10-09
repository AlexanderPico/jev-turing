"""Rule 110 where every cell update is ONE JEV judgment.

Each update sends the 3-cell neighbourhood (L, C, R) to a single binary
judgment, :data:`RULE110_SPEC`. The engine (:class:`Tape` + :class:`JevRule110`)
only moves bits: it reads neighbours, asks the judge, writes the answer, and
grows the tape when the pattern reaches an edge.

Unbounded tape, on demand
-------------------------
The tape is a finite window over an infinite line whose far field is a
spatially periodic *background* (all-zero, or the period-14 Rule 110 "ether"
that Cook's universality construction runs on). The background is kept as a
one-period ring that is ALSO evolved by JEV judgments (cyclic boundary), so no
Python rule ever computes a cell, including far-field cells. Before each step,
if an edge cell differs from the background, the window grows by one
background cell on that side. Memory is bounded only by how long you run.

Checking
--------
:func:`reference_rule110` is a pure-Python Rule 110. It is used ONLY by
:class:`GroundTruthChecker` to grade the JEV run. The engine never calls it
(a test enforces this). The checker reports:

* ``local_errors``: calls where the judge's answer differs from Rule 110 on
  the inputs it was actually given (the error counter);
* ``divergent cells``: cells where the JEV spacetime differs from an
  independent reference evolution of the same initial condition (an error
  plus everything it has propagated into).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .backend import JudgmentBackend, binary_spec, judge_detailed
from .gates import CALLS_PER_GATE, MAJ3_SPEC, VOTE_MODES

RULE110_SPEC = binary_spec(
    "ca-rule110",
    "L, C and R are three adjacent cells of a one-dimensional cellular automaton "
    "(left neighbour, the cell, right neighbour), each on (true) or off (false). "
    "Under Wolfram's elementary rule 110, is the middle cell on at the next step?",
    ("L", "C", "R"),
    {"111": False, "110": True, "101": True, "100": False,
     "011": True, "010": True, "001": True, "000": False},
    true_definition="Rule 110 maps this neighbourhood to on.",
    false_definition="Rule 110 maps this neighbourhood to off.",
)
# v1 above names the rule and relies on the judge knowing it. Live JEV does not
# (2026-10-09: P(true) ~0.4-0.75 on every row, row 100 wrong 6/6). v2 states the
# rule as one plain sentence, exactly as the NAND spec states NAND. The 8-row
# table is still never sent; the judge must apply the sentence to L, C, R.
RULE110_SPEC_V1 = RULE110_SPEC
RULE110_SPEC = binary_spec(
    "ca-rule110",
    "L, C and R are three adjacent cells (left neighbour, the cell, right neighbour), "
    "each on (true) or off (false). Rule: the cell is on at the next step exactly when "
    "C or R is on, unless L, C and R are all on. Is the cell on at the next step?",
    ("L", "C", "R"),
    {"111": False, "110": True, "101": True, "100": False,
     "011": True, "010": True, "001": True, "000": False},
    true_definition="C or R is on, and L, C and R are not all on.",
    false_definition="C and R are both off, or L, C and R are all on.",
    version=2,
)

BACKGROUNDS = {
    "zero": "0",
    # Rule 110 ether: spatial period 14, temporal period 7 on a 14-cell ring.
    "ether": "11111000100110",
}

UpdateFn = Callable[[bool, bool, bool], bool]


def parse_bits(s: str) -> list[bool]:
    if not s or set(s) - {"0", "1"}:
        raise ValueError("bit string must be non-empty and contain only 0/1: {!r}".format(s))
    return [c == "1" for c in s]


def bits_str(bits: list[bool]) -> str:
    return "".join("1" if b else "0" for b in bits)


# ---------------------------------------------------------------------------
# Tape mechanics (moves bits; the update function decides every cell)
# ---------------------------------------------------------------------------

class Tape:
    """Growable window ``[lo, lo+len(cells))`` over a periodic background ring."""

    def __init__(self, init: list[bool], background: list[bool], *, offset: int = 0, pad: int = 0):
        if not background:
            raise ValueError("background must be non-empty")
        self.ring = list(background)
        self.t = 0
        self.lo = offset - pad
        self.cells = [self.bg_at(x) for x in range(self.lo, offset)] + list(init) + \
                     [self.bg_at(x) for x in range(offset + len(init), offset + len(init) + pad)]

    @property
    def period(self) -> int:
        return len(self.ring)

    @property
    def hi(self) -> int:
        return self.lo + len(self.cells)

    def bg_at(self, x: int) -> bool:
        return self.ring[x % self.period]

    def at(self, x: int) -> bool:
        if self.lo <= x < self.hi:
            return self.cells[x - self.lo]
        return self.bg_at(x)

    def grow(self) -> int:
        """Ensure both edge cells equal the background. Returns cells added."""
        added = 0
        while self.cells[0] != self.bg_at(self.lo):
            self.lo -= 1
            self.cells.insert(0, self.bg_at(self.lo))
            added += 1
        while self.cells[-1] != self.bg_at(self.hi - 1):
            self.cells.append(self.bg_at(self.hi))
            added += 1
        return added

    def step(self, update: Callable[[str, int, bool, bool, bool], bool]) -> None:
        """Advance one generation. ``update(kind, x, L, C, R)`` decides each cell."""
        self.grow()
        new_cells = [update("tape", x, self.at(x - 1), self.at(x), self.at(x + 1))
                     for x in range(self.lo, self.hi)]
        p = self.period
        new_ring = [update("bg", j, self.ring[(j - 1) % p], self.ring[j], self.ring[(j + 1) % p])
                    for j in range(p)]
        self.cells, self.ring = new_cells, new_ring
        self.t += 1

    def snapshot(self) -> dict[str, Any]:
        return {"t": self.t, "lo": self.lo, "cells": bits_str(self.cells), "bg": bits_str(self.ring)}


# ---------------------------------------------------------------------------
# Ground truth (CHECKING ONLY)
# ---------------------------------------------------------------------------

def reference_rule110(left: bool, center: bool, right: bool) -> bool:
    """Pure-Python Rule 110. Used ONLY by the checker, never by the engine."""
    return bool((110 >> ((left << 2) | (center << 1) | right)) & 1)


class GroundTruthChecker:
    """Grades a JEV run: per-call errors plus divergence from a reference run."""

    def __init__(self, init: list[bool], background: list[bool], *, offset: int = 0, pad: int = 0):
        self.reference = Tape(init, background, offset=offset, pad=pad)
        self.local_errors = 0
        self.errors_by_kind = {"tape": 0, "bg": 0}
        self.first_error_t: int | None = None

    def grade_call(self, t: int, kind: str, left: bool, center: bool, right: bool, out: bool) -> tuple[bool, bool]:
        expected = reference_rule110(left, center, right)
        err = out != expected
        if err:
            self.local_errors += 1
            self.errors_by_kind[kind] += 1
            if self.first_error_t is None:
                self.first_error_t = t
        return expected, err

    def advance(self) -> None:
        self.reference.step(lambda kind, x, l, c, r: reference_rule110(l, c, r))

    def divergence(self, tape: Tape) -> int:
        lo = min(tape.lo, self.reference.lo)
        hi = max(tape.hi, self.reference.hi)
        tape_cells = sum(tape.at(x) != self.reference.at(x) for x in range(lo, hi))
        ring_cells = sum(a != b for a, b in zip(tape.ring, self.reference.ring))
        return tape_cells + ring_cells


# ---------------------------------------------------------------------------
# JEV-driven engine
# ---------------------------------------------------------------------------

# One row per cell update. With voting, "calls" > 1 and "flipped" counts the
# flipped sub-calls (including a flipped MAJ3 judgment in vote="jev").
CALL_LOG_COLUMNS = ["t", "kind", "x", "L", "C", "R", "out", "expected", "error", "calls", "flipped",
                    "latency_ms"]


class JevRule110:
    def __init__(self, backend: JudgmentBackend, *, init: str = "1", background: str = "zero",
                 offset: int = 0, pad: int = 0, check: bool = True, log_calls: bool = True,
                 vote: str = "none", workers: int = 1):
        if vote not in VOTE_MODES:
            raise ValueError("vote must be one of {}".format(VOTE_MODES))
        if workers < 1 or (workers > 1 and vote != "none"):
            raise ValueError("workers > 1 is supported only with vote='none'")
        self.workers = workers
        self._prefetched: dict[tuple[str, int], tuple[bool, dict[str, Any], float]] = {}
        self.vote = vote
        bg_pattern = BACKGROUNDS.get(background, background)
        self.background_name = background if background in BACKGROUNDS else "custom"
        self.background_pattern = bg_pattern
        self.init_pattern = init
        self.offset = offset
        self.pad = pad
        self.backend = backend
        init_bits, bg_bits = parse_bits(init), parse_bits(bg_pattern)
        self.tape = Tape(init_bits, bg_bits, offset=offset, pad=pad)
        self.checker = GroundTruthChecker(init_bits, bg_bits, offset=offset, pad=pad) if check else None
        self.log_calls = log_calls
        self.call_log: list[list[Any]] = []
        self.jev_calls = {"tape": 0, "bg": 0}
        self.flipped = 0
        self.rows = [self.tape.snapshot()]
        self.reference_rows = [self.checker.reference.snapshot()] if self.checker else []
        self.per_step: list[dict[str, Any]] = []

    def _update(self, kind: str, x: int, left: bool, center: bool, right: bool) -> bool:
        t = self.tape.t
        start = time.perf_counter()
        fields = {"L": left, "C": center, "R": right}
        pre = self._prefetched.pop((kind, x), None)
        if pre is not None:
            out, result, latency_ms = pre
            results = [result]
        elif self.vote == "none":
            out, result = judge_detailed(self.backend, fields, RULE110_SPEC)
            results = [result]
        else:
            copies = [judge_detailed(self.backend, fields, RULE110_SPEC) for _ in range(3)]
            results = [r for _, r in copies]
            a, b, c = (o for o, _ in copies)
            if self.vote == "glue":
                out = (a and b) or (a and c) or (b and c)  # GLUE COMPUTES: trusted voter
            else:
                out, maj = judge_detailed(self.backend, {"A": a, "B": b, "C": c}, MAJ3_SPEC)
                results.append(maj)
        if pre is None:
            latency_ms = (time.perf_counter() - start) * 1000.0
        n_calls = CALLS_PER_GATE[self.vote]
        self.jev_calls[kind] += n_calls
        flips = [r["provenance"].get("flipped") for r in results]
        flipped = None if any(f is None for f in flips) else sum(bool(f) for f in flips)
        if flipped:
            self.flipped += flipped
        expected = err = None
        if self.checker is not None:
            expected, err = self.checker.grade_call(t, kind, left, center, right, out)
        if self.log_calls:
            self.call_log.append([t, kind, x, int(left), int(center), int(right), int(out),
                                  None if expected is None else int(expected),
                                  None if err is None else int(err),
                                  n_calls, flipped,
                                  round(latency_ms, 4)])
        return out

    def _prefetch(self) -> None:
        """Ask every cell of the coming step at once (each depends only on the current row).

        The answers are then consumed by ``Tape.step`` in the normal order, so the
        run, call log and grading are identical to the serial engine.
        """
        from concurrent.futures import ThreadPoolExecutor

        from .live_backend import CALL_CONTEXT

        tape, t = self.tape, self.tape.t
        tape.grow()  # Tape.step's own grow() is then a no-op
        p = tape.period
        jobs = [("tape", x, tape.at(x - 1), tape.at(x), tape.at(x + 1)) for x in range(tape.lo, tape.hi)]
        jobs += [("bg", j, tape.ring[(j - 1) % p], tape.ring[j], tape.ring[(j + 1) % p]) for j in range(p)]

        def ask(job):
            kind, x, left, center, right = job
            CALL_CONTEXT.set("t={} {} x={}".format(t, kind, x))
            start = time.perf_counter()
            out, result = judge_detailed(self.backend, {"L": left, "C": center, "R": right}, RULE110_SPEC)
            return (kind, x), (out, result, (time.perf_counter() - start) * 1000.0)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            self._prefetched = dict(pool.map(ask, jobs))  # re-raises the first failure

    def step(self) -> None:
        calls_before = sum(self.jev_calls.values())
        if self.workers > 1:
            self._prefetch()
        self.tape.step(self._update)
        if self._prefetched:
            raise RuntimeError("prefetched answers were not all used: {}".format(sorted(self._prefetched)[:5]))
        self.rows.append(self.tape.snapshot())
        rec: dict[str, Any] = {"t": self.tape.t, "calls": sum(self.jev_calls.values()) - calls_before,
                               "width": len(self.tape.cells)}
        if self.checker is not None:
            self.checker.advance()
            self.reference_rows.append(self.checker.reference.snapshot())
            rec["local_errors_cum"] = self.checker.local_errors
            rec["divergent_cells"] = self.checker.divergence(self.tape)
        self.per_step.append(rec)

    def run(self, steps: int) -> "JevRule110":
        for _ in range(steps):
            self.step()
        return self

    def counters(self) -> dict[str, Any]:
        c: dict[str, Any] = {
            "steps": self.tape.t,
            "jev_calls": sum(self.jev_calls.values()),
            "cell_updates": len(self.call_log) if self.log_calls else None,
            "vote": self.vote,
            "tape_calls": self.jev_calls["tape"],
            "background_calls": self.jev_calls["bg"],
            "fake_flips": self.flipped if getattr(self.backend, "identity", "").startswith("fake-jev") else None,
            "final_width": len(self.tape.cells),
        }
        if self.checker is not None:
            c.update({
                "local_errors": self.checker.local_errors,
                "local_errors_tape": self.checker.errors_by_kind["tape"],
                "local_errors_background": self.checker.errors_by_kind["bg"],
                "first_error_t": self.checker.first_error_t,
                "divergent_cells_final": self.per_step[-1]["divergent_cells"] if self.per_step else 0,
            })
        return c

    def to_dict(self, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        is_fake = getattr(self.backend, "identity", "").startswith("fake-jev")
        return {
            "schema": "jev-turing/rule110-run/1",
            "disclaimer": ("Offline FakeJEV simulation. NOT a JEV result; no live JEV call was made."
                           if is_fake else "Backend: {}".format(self.backend.identity)),
            "backend": self.backend.identity,
            "error_rate": getattr(self.backend, "error_rate", None),
            "seed": getattr(self.backend, "seed", None),
            "background": {"name": self.background_name, "pattern": self.background_pattern,
                           "period": len(self.background_pattern)},
            "init": {"pattern": self.init_pattern, "offset": self.offset, "pad": self.pad},
            "spec": RULE110_SPEC,
            "counters": self.counters(),
            "per_step": self.per_step,
            "rows": self.rows,
            "reference_rows": self.reference_rows,
            "call_log": {"columns": CALL_LOG_COLUMNS, "rows": self.call_log},
            "meta": meta or {},
        }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_json(run: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(run, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _cell_at(row: dict[str, Any], x: int) -> tuple[bool, bool]:
    """(value, inside_window) for absolute x in a snapshot row."""
    lo, cells, bg = row["lo"], row["cells"], row["bg"]
    if lo <= x < lo + len(cells):
        return cells[x - lo] == "1", True
    return bg[x % len(bg)] == "1", False


def write_png(run: dict[str, Any], path: str | Path, *, scale: int = 4) -> Path:
    """Spacetime diagram: time runs down. Divergent cells in red, erroneous
    calls in amber, cells outside the grown window dimmed."""
    from PIL import Image  # optional dependency

    rows, refs = run["rows"], run.get("reference_rows") or []
    lo = min(r["lo"] for r in rows + refs)
    hi = max(r["lo"] + len(r["cells"]) for r in rows + refs)
    err_cells = set()
    cols = run["call_log"]["columns"]
    it, ik, ix, ie = cols.index("t"), cols.index("kind"), cols.index("x"), cols.index("error")
    for c in run["call_log"]["rows"]:
        if c[ik] == "tape" and c[ie]:
            err_cells.add((c[it] + 1, c[ix]))
    width, height = hi - lo, len(rows)
    img = Image.new("RGB", (width, height))
    px = img.load()
    on, off = (230, 230, 225), (17, 17, 20)
    on_dim, off_dim = (90, 90, 95), (30, 30, 34)
    red_on, red_off = (255, 80, 80), (110, 20, 24)
    amber = (255, 190, 40)
    for y, row in enumerate(rows):
        ref = refs[y] if y < len(refs) else None
        for x in range(lo, hi):
            v, inside = _cell_at(row, x)
            color = (on if v else off) if inside else (on_dim if v else off_dim)
            if ref is not None and _cell_at(ref, x)[0] != v:
                color = red_on if v else red_off
            if (y, x) in err_cells:
                color = amber
            px[x - lo, y] = color
    img = img.resize((width * scale, height * scale), Image.NEAREST)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
