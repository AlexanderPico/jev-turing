"""Logic gates where each gate evaluation is exactly ONE JEV judgment.

The spec (a jev-tables-style taxonomy) frames the decision; the backend
decides. The glue in this module only packs input bits into ``selected_fields``
and hands the backend's bool back. It never computes NOT/NAND/NOR itself.

Triple voting (von Neumann 1956, majority of three redundant copies) has two
modes, and they differ in honesty:

* ``vote="glue"``: three JEV gate calls, then a Python majority. **The
  majority step is computation done in glue.** It is a trusted, noiseless
  voter. That makes it a useful error-budget illustration, but it breaks the
  "glue only moves bits" rule, so results in this mode must be labelled as
  using a glue voter.
* ``vote="jev"``: three JEV gate calls, then a fourth JEV judgment, MAJ3, that
  decides the majority. The rule holds, and the voter can itself err (4 calls).
"""
from __future__ import annotations

import itertools
from typing import Any, Callable

from .backend import JudgmentBackend, binary_spec, judge

VOTE_MODES = ("none", "glue", "jev")

NOT_SPEC = binary_spec(
    "gate-not", "Input A is a bit (true or false). Is A false?",
    ("A",), {"0": True, "1": False},
    true_definition="A is false.", false_definition="A is true.",
)

NAND_SPEC = binary_spec(
    "gate-nand",
    "Inputs A and B are bits (true or false). Is it NOT the case that both A and B are true?",
    ("A", "B"), {"00": True, "01": True, "10": True, "11": False},
    true_definition="At least one of A, B is false.",
    false_definition="A and B are both true.",
)

NOR_SPEC = binary_spec(
    "gate-nor",
    "Inputs A and B are bits (true or false). Are A and B both false?",
    ("A", "B"), {"00": True, "01": False, "10": False, "11": False},
    true_definition="Neither A nor B is true.",
    false_definition="At least one of A, B is true.",
)

MAJ3_SPEC = binary_spec(
    "vote-maj3",
    "Inputs A, B and C are three redundant copies of one bit. Are at least two of them true?",
    ("A", "B", "C"),
    {"000": False, "001": False, "010": False, "011": True,
     "100": False, "101": True, "110": True, "111": True},
    true_definition="Two or three of A, B, C are true.",
    false_definition="Two or three of A, B, C are false.",
)

SPECS: dict[str, dict[str, Any]] = {"NOT": NOT_SPEC, "NAND": NAND_SPEC, "NOR": NOR_SPEC}


def _fields(spec: dict[str, Any], bits: tuple[bool, ...]) -> dict[str, bool]:
    names = spec["inputs"]
    if len(bits) != len(names):
        raise ValueError("{} takes {} input(s), got {}".format(spec["taxonomy_id"], len(names), len(bits)))
    return {name: bool(b) for name, b in zip(names, bits)}


def gate(backend: JudgmentBackend, name: str, *bits: bool, vote: str = "none") -> bool:
    """Evaluate gate ``name`` on ``bits``.

    vote="none": 1 JEV call. vote="glue": 3 JEV calls + Python majority (glue
    computes). vote="jev": 3 JEV calls + 1 JEV MAJ3 judgment = 4 calls.
    """
    spec = SPECS[name]
    fields = _fields(spec, bits)
    if vote == "none":
        return judge(backend, fields, spec)
    if vote not in VOTE_MODES:
        raise ValueError("vote must be one of {}".format(VOTE_MODES))
    a, b, c = (judge(backend, fields, spec) for _ in range(3))
    if vote == "glue":
        # GLUE COMPUTES HERE: a trusted, noiseless majority voter.
        return (a and b) or (a and c) or (b and c)
    return judge(backend, {"A": a, "B": b, "C": c}, MAJ3_SPEC)


def NOT(backend: JudgmentBackend, a: bool, *, vote: str = "none") -> bool:
    return gate(backend, "NOT", a, vote=vote)


def NAND(backend: JudgmentBackend, a: bool, b: bool, *, vote: str = "none") -> bool:
    return gate(backend, "NAND", a, b, vote=vote)


def NOR(backend: JudgmentBackend, a: bool, b: bool, *, vote: str = "none") -> bool:
    return gate(backend, "NOR", a, b, vote=vote)


CALLS_PER_GATE = {"none": 1, "glue": 3, "jev": 4}

# ---------------------------------------------------------------------------
# Accuracy harness (checking only: the reference functions below never feed a
# gate output; they only grade it)
# ---------------------------------------------------------------------------

_REFERENCE: dict[str, Callable[..., bool]] = {
    "NOT": lambda a: not a,
    "NAND": lambda a, b: not (a and b),
    "NOR": lambda a, b: not (a or b),
}


def theoretical_accuracy(p: float, vote: str = "none") -> float:
    """Expected per-evaluation accuracy for independent bit flips at rate p."""
    q = 1.0 - p
    maj_ok = q ** 3 + 3 * q ** 2 * p  # at least 2 of 3 copies correct
    if vote == "none":
        return q
    if vote == "glue":
        return maj_ok
    if vote == "jev":
        # The MAJ3 judgment is correct w.p. q; if it errs, the output is wrong.
        return maj_ok * q + (1 - maj_ok) * p
    raise ValueError(vote)


def truth_table_accuracy(backend: JudgmentBackend, name: str, n_per_row: int, *, vote: str = "none") -> dict[str, Any]:
    """Run every truth-table row ``n_per_row`` times; grade against a reference."""
    spec = SPECS[name]
    arity = len(spec["inputs"])
    rows = []
    total_ok = 0
    for bits in itertools.product((False, True), repeat=arity):
        expected = _REFERENCE[name](*bits)
        ok = sum(gate(backend, name, *bits, vote=vote) == expected for _ in range(n_per_row))
        total_ok += ok
        rows.append({
            "inputs": "".join("1" if b else "0" for b in bits),
            "expected": expected,
            "correct": ok,
            "n": n_per_row,
            "accuracy": ok / n_per_row if n_per_row else None,
        })
    n_total = n_per_row * len(rows)
    return {
        "gate": name,
        "vote": vote,
        "backend": backend.identity,
        "n_per_row": n_per_row,
        "evaluations": n_total,
        "jev_calls": n_total * CALLS_PER_GATE[vote],
        "accuracy": total_ok / n_total if n_total else None,
        "rows": rows,
    }


def xor_from_nands(backend: JudgmentBackend, x: bool, y: bool, *, vote: str = "none") -> dict[str, Any]:
    """XOR built from four NANDs. Every intermediate is a raw JEV output fed straight on."""
    n1 = NAND(backend, x, y, vote=vote)
    n2 = NAND(backend, x, n1, vote=vote)
    n3 = NAND(backend, y, n1, vote=vote)
    out = NAND(backend, n2, n3, vote=vote)
    # Checking only, after the fact: each gate is graded on the inputs it actually received.
    ref = _REFERENCE["NAND"]
    gate_errors = sum([n1 != ref(x, y), n2 != ref(x, n1), n3 != ref(y, n1), out != ref(n2, n3)])
    return {"x": x, "y": y, "n1": n1, "n2": n2, "n3": n3, "out": out,
            "expected": x != y, "internal_errors": gate_errors}


def xor_accuracy(backend: JudgmentBackend, n_per_row: int, *, vote: str = "none") -> dict[str, Any]:
    rows, total_ok, gate_errs, trials = [], 0, 0, []
    for x, y in itertools.product((False, True), repeat=2):
        ok = 0
        for _ in range(n_per_row):
            t = xor_from_nands(backend, x, y, vote=vote)
            ok += t["out"] == t["expected"]
            gate_errs += t["internal_errors"]
            trials.append(t)
        total_ok += ok
        rows.append({"inputs": "{}{}".format(int(x), int(y)), "expected": x != y, "correct": ok,
                     "n": n_per_row, "accuracy": ok / n_per_row if n_per_row else None})
    n = 4 * n_per_row
    return {"circuit": "XOR(4xNAND)", "vote": vote, "backend": backend.identity, "n_per_row": n_per_row,
            "evaluations": n, "jev_calls": 4 * n * CALLS_PER_GATE[vote],
            "accuracy": total_ok / n if n else None,
            "individual_gate_errors": gate_errs, "rows": rows, "trials": trials}


def error_budget(p_call: float, calls: int) -> dict[str, float]:
    """How a per-call error rate scales over a run of ``calls`` judgments."""
    return {
        "p_call": p_call,
        "calls": calls,
        "expected_errors": p_call * calls,
        "p_zero_errors": (1.0 - p_call) ** calls,
    }
