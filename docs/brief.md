# The brief: what this demo must prove, and how to say it

Written before any live run (2026-10-08) as the project's rules of evidence.
This file condenses it for the code. If wording here and in a pitch ever disagree, this file wins.

## Prove three things, then Rule 110

1. **NAND accuracy.** JEV as a NAND gate, with truth-table accuracy published over
   thousands of calls (`python -m jev_turing gates --gate NAND --n 1000 --vote all`).
2. **Clean composition.** JEV's true/false output feeds the next call with no cleanup
   (XOR from four NANDs in `tests/test_gates.py`; every intermediate is a raw JEV output).
3. **A latch.** Two cross-coupled JEV NANDs form an SR latch that holds one bit
   across hold cycles (`python -m jev_turing latch --trials 1000`).
4. **Rule 110 with an error counter.** One JEV call per cell update, the tape grows
   on demand, and a ground-truth checker and error counter run alongside.

## Wording rules

- **Never say "Turing-complete"** unless memory can grow without limit. Say
  **"universal given unbounded cells"**. The tape here grows on demand, but any
  actual run is finite. For fixed-size circuits, say "universal for finite circuits".
- **Glue never decides.** Glue only moves bits. The one exception, the `vote="glue"`
  majority, is labelled as glue computation everywhere it appears. `vote="jev"` makes
  the majority a JEV judgment instead.
- **Never hide errors.** At 99.9% per call, a 10,000-call run is expected to see ~10
  errors (P(zero errors) ≈ 0.005%). Show the error counter and the error budget, or
  use triple voting (von Neumann, 1956), and say which.
- **Not "an LLM is a slow NAND."** The point is that the AI *is* the gate.
- **FakeJEV numbers are not JEV numbers.** Until a live run happens, every figure is
  labelled as an offline FakeJEV simulation.

## Error budget (independent bit flips at rate p per call)

| p per call | calls | expected errors | P(zero errors) |
| --- | --- | --- | --- |
| 0.001 | 4,855 (recorded run) | 4.9 | 0.8% |
| 0.001 | 12,800 (64×200 live run) | 12.8 | ~0.0003% |
| 0.0001 | 12,800 | 1.3 | 28% |

Triple voting with a trusted voter turns p into ≈3p² (0.001 → 3×10⁻⁶) at 3× the calls.
With a noisy JEV voter (`vote="jev"`) the output can never be more reliable than the
voter itself (≈ p + 3p²), so voting only pays if the voter is more reliable than the gate.
That is von Neumann's original caveat, and the demo should show it, not hide it.

## Form

A 30 s warm-up (the NAND truth table, then the latch holding a bit), then cut to
Rule 110: each cell update is one JEV call, the tape grows live, and the checker and
error counter run alongside. Not Game of Life (its rule hides the work) and not a
full CPU (too slow, murky glue).

## Close

> **Universality rests on this one judgment.**
