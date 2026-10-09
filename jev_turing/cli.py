"""``python -m jev_turing {gates,latch,rule110,live-nand,site-data}``. FakeJEV unless live is explicitly approved."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backend import JevNotConfiguredError, make_backend
from .gates import SPECS, VOTE_MODES, error_budget, theoretical_accuracy, truth_table_accuracy, xor_accuracy
from .latch import demo_trace, measure_hold
from .rule110 import BACKGROUNDS, JevRule110, write_json, write_png

FAKE_BANNER = "[FakeJEV offline simulation: these are NOT JEV results]"


def _nonnegative_int(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def _positive_int(value: str) -> int:
    n = _nonnegative_int(value)
    if n == 0:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def _probability(value: str) -> float:
    p = float(value)
    if not 0 <= p <= 1:
        raise argparse.ArgumentTypeError("must be in [0, 1]")
    return p


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--backend", choices=["fake", "jev", "live"], default="fake",
                   help="'live' = paid typesafe-ai/jev calls (needs --i-approve-live-calls); 'jev' is the old disabled stub")
    p.add_argument("--i-approve-live-calls", action="store_true")
    p.add_argument("--max-calls", type=_positive_int, default=100, help="live: hard call cap for this command")
    p.add_argument("--max-usd", type=float, default=0.01, help="live: hard USD cap for this command")
    p.add_argument("--ledger", default=None, help="live: new JSONL file, one line per call (required for live)")
    p.add_argument("--error-rate", type=_probability, default=0.0, help="FakeJEV per-call bit-flip probability")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")


class LiveRefused(RuntimeError):
    pass


def _backend(a: argparse.Namespace, shared: list) -> Any:
    """Fake backends are fresh per use; a live backend is shared so the caps cover the whole command."""
    if a.backend != "live":
        return make_backend(a.backend, error_rate=a.error_rate, seed=a.seed)
    if shared:
        return shared[0]
    if not a.i_approve_live_calls or not a.ledger:
        raise LiveRefused("live JEV calls cost money: pass --i-approve-live-calls and --ledger <new file> "
                          "(caps: --max-calls {}, --max-usd {})".format(a.max_calls, a.max_usd))
    from .live_backend import CappedLiveJev
    shared.append(CappedLiveJev(max_calls=a.max_calls, max_usd=a.max_usd, ledger_path=a.ledger))
    return shared[0]


def _banner(a: argparse.Namespace, shared: list) -> str:
    if a.backend == "fake":
        return FAKE_BANNER
    if a.backend == "live" and shared:
        return "[LIVE JEV: {}]  {}".format(shared[0].identity, json.dumps(shared[0].status()))
    return ""


def cmd_gates(a: argparse.Namespace) -> int:
    gates = list(SPECS) if a.gate == "all" else [a.gate]
    votes = list(VOTE_MODES) if a.vote == "all" else [a.vote]
    results = []
    live: list = []
    for g in gates:
        for v in votes:
            backend = _backend(a, live)
            r = truth_table_accuracy(backend, g, a.n, vote=v)
            r["theoretical_accuracy"] = theoretical_accuracy(a.error_rate, v)
            results.append(r)
    if a.json:
        print(json.dumps(results, indent=2))
        return 0
    print(_banner(a, live))
    print("p_flip={:g}  n_per_row={}  seed={}".format(a.error_rate, a.n, a.seed))
    print("{:<5} {:<5} {:>9} {:>9} {:>10}  per-row".format("gate", "vote", "accuracy", "theory", "jev_calls"))
    for r in results:
        rows = " ".join("{}:{:.4f}".format(x["inputs"], x["accuracy"]) for x in r["rows"])
        print("{:<5} {:<5} {:>9.4f} {:>9.4f} {:>10}  {}".format(
            r["gate"], r["vote"], r["accuracy"], r["theoretical_accuracy"], r["jev_calls"], rows))
    if "glue" in votes:
        print("note: vote=glue uses a trusted Python majority (glue computes); vote=jev makes MAJ3 a JEV call.")
    return 0


def cmd_xor(a: argparse.Namespace) -> int:
    live: list = []
    r = xor_accuracy(_backend(a, live), a.n, vote=a.vote)
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    if a.json:
        print(json.dumps({k: v for k, v in r.items() if k != "trials"}, indent=2))
        return 0
    print(_banner(a, live))
    print("XOR from 4 NANDs, vote={}, n_per_row={}: accuracy={:.4f}, jev_calls={}, wrong individual gates={}".format(
        a.vote, a.n, r["accuracy"], r["jev_calls"], r["individual_gate_errors"]))
    for row in r["rows"]:
        print("  {} -> expect {:d}: {}/{}".format(row["inputs"], row["expected"], row["correct"], row["n"]))
    return 0


def cmd_latch(a: argparse.Namespace) -> int:
    live: list = []
    backend = _backend(a, live)
    out: dict[str, Any] = {"trace": demo_trace(backend, hold_cycles=a.hold_cycles, vote=a.vote)}
    if a.trials:
        backend = _backend(a, live)
        out["hold_measurement"] = measure_hold(backend, trials=a.trials, hold_cycles=a.hold_cycles, vote=a.vote,
                                               workers=a.workers)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if a.json:
        if "hold_measurement" in out:
            out["hold_measurement"] = {k: v for k, v in out["hold_measurement"].items() if k != "trial_results"}
        print(json.dumps(out, indent=2))
        return 0
    print(_banner(a, live))
    print("SR latch (two cross-coupled JEV NANDs, active-low S_n/R_n), p_flip={:g}, vote={}".format(
        a.error_rate, a.vote))
    for rec in out["trace"]:
        print("  {:<5} S_n={:d} R_n={:d} -> Q={:d} Qb={:d}  passes={} calls={}{}".format(
            rec["op"], rec["S_n"], rec["R_n"], rec["Q"], rec["Qb"], rec["passes"], rec["jev_calls"],
            "" if rec["converged"] else "  (NOT CONVERGED)"))
    if "hold_measurement" in out:
        m = out["hold_measurement"]
        rate = "n/a" if m["hold_error_rate"] is None else "{:.4f}".format(m["hold_error_rate"])
        per_cycle = "n/a" if m["per_cycle_hold_error_est"] is None else "{:.5f}".format(m["per_cycle_hold_error_est"])
        loss = "n/a" if m["any_loss_rate"] is None else "{:.4f}".format(m["any_loss_rate"])
        print("hold test: {} trials x {} hold cycles: write failures={}, hold failures={}, "
              "final-read hold error rate={}, lost at any point={}, per-cycle est={}, jev_calls={}".format(
                  m["trials"], m["hold_cycles"], m["write_failures"], m["hold_failures"],
                  rate, loss, per_cycle, m["jev_calls"]))
    return 0


def cmd_rule110(a: argparse.Namespace) -> int:
    live: list = []
    backend = _backend(a, live)
    sim = JevRule110(backend, init=a.init, background=a.background, pad=a.pad, vote=a.vote,
                     workers=a.workers)
    try:
        sim.run(a.steps)
    except Exception:
        if a.out and a.backend == "live":
            # Save whatever finished when a cap or failed call stops the run.
            write_json(sim.to_dict(meta={"partial": True}), a.out + ".partial.json")
        raise
    run = sim.to_dict(meta={"command": "python -m jev_turing " + " ".join(sys.argv[1:]) if a.record_argv else ""})
    c = run["counters"]
    paths = []
    if a.out:
        paths.append(write_json(run, a.out + ".json"))
        if not a.no_png:
            paths.append(write_png(run, a.out + ".png", scale=a.scale))
    if a.json:
        print(json.dumps(c, indent=2))
        return 0
    print(_banner(a, live))
    print("Rule 110, background={}, init={}, steps={}, vote={}, p_flip={:g}, seed={}".format(
        a.background, a.init, a.steps, a.vote, a.error_rate, a.seed))
    print("  JEV calls: {} (tape {}, background ring {}); final width {}".format(
        c["jev_calls"], c["tape_calls"], c["background_calls"], c["final_width"]))
    print("  error counter (checker): {} wrong cell updates; first at t={}; divergent cells at end: {}".format(
        c["local_errors"], c["first_error_t"], c["divergent_cells_final"]))
    if a.backend == "fake":
        b = error_budget(a.error_rate, c["jev_calls"])
        print("  error budget: expected {:.2f} raw flips over {} calls; P(zero flips)={:.4f}".format(
            b["expected_errors"], c["jev_calls"], b["p_zero_errors"]))
    for p in paths:
        print("  wrote", p)
    return 0


def attach_live_ledger(run: dict[str, Any], ledger_path: str | Path) -> dict[str, Any]:
    """Add each call's P(true) as a call-log column and the total cost to meta.

    Rule 110 without voting makes exactly one call per call-log row, in order, so
    row i is ledger line i. The inputs are cross-checked so a mismatch fails loudly.
    """
    ledger = [json.loads(line) for line in Path(ledger_path).read_text(encoding="utf-8").splitlines()]
    rows = run["call_log"]["rows"]
    cols = run["call_log"]["columns"]
    if run["counters"]["vote"] != "none" or len(ledger) != len(rows):
        raise ValueError("ledger does not line up with the call log ({} vs {} rows)".format(len(ledger), len(rows)))
    li = {k: cols.index(k) for k in ("L", "C", "R", "out")}
    if all(rec.get("ctx") for rec in ledger):  # parallel run: match each call to its cell by tag
        by_ctx = {rec["ctx"]: rec for rec in ledger}
        ti, ki, xi = cols.index("t"), cols.index("kind"), cols.index("x")
        try:
            ledger = [by_ctx["t={} {} x={}".format(row[ti], row[ki], row[xi])] for row in rows]
        except KeyError as exc:
            raise ValueError("ledger has no call for cell {}".format(exc)) from exc
    for row, rec in zip(rows, ledger):
        got = (rec["inputs"]["L"], rec["inputs"]["C"], rec["inputs"]["R"], rec["choice"] == "true")
        if got != tuple(bool(row[li[k]]) for k in ("L", "C", "R", "out")):
            raise ValueError("ledger call {} does not match call-log row".format(rec["call"]))
        row.append(rec["p_true"])
    run["call_log"]["columns"] = cols + ["p_true"]
    run.setdefault("meta", {})["cost_usd"] = round(sum(rec.get("cost_usd") or 0 for rec in ledger), 6)
    run["meta"]["hosts"] = sorted({rec.get("provider") for rec in ledger if rec.get("provider")})
    return run


def cmd_site_data(a: argparse.Namespace) -> int:
    run = json.loads(Path(a.run).read_text(encoding="utf-8"))
    if a.ledger:
        run = attach_live_ledger(run, a.ledger)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("// Generated by `python -m jev_turing site-data`; do not edit.\n"
                   "window.{} = ".format(a.var) + json.dumps(run, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print("wrote", out)
    return 0


def cmd_live_nand(a: argparse.Namespace) -> int:
    from .live_nand import render_report, run_live_nand
    if not a.i_approve_live_calls:
        print("refusing: live JEV calls cost money. Re-run with --i-approve-live-calls "
              "after the caps below are approved.", file=sys.stderr)
        print("planned: {} calls, max ${:.4f}".format(min(4 * a.per_row, a.max_calls), a.max_usd), file=sys.stderr)
        return 2
    s = run_live_nand(a.out, per_row=a.per_row, max_calls=a.max_calls, max_usd=a.max_usd,
                      reserve_usd_per_call=a.reserve_usd, seed=a.seed, label=a.label,
                      busy_retries=a.busy_retries)
    print("[LIVE JEV run: typesafe-ai/jev via Vercel AI Gateway]")
    print(render_report(s))
    print("  wrote", a.out)
    return 0 if s["stop_reason"] == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m jev_turing", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gates", help="truth-table accuracy harness")
    _common(g)
    g.add_argument("--gate", choices=list(SPECS) + ["all"], default="NAND")
    g.add_argument("--vote", choices=list(VOTE_MODES) + ["all"], default="none")
    g.add_argument("--n", type=_positive_int, default=1000, help="evaluations per truth-table row")
    g.set_defaults(func=cmd_gates)

    x = sub.add_parser("xor", help="XOR from four chained NAND judgments (composition test)")
    _common(x)
    x.add_argument("--vote", choices=VOTE_MODES, default="none")
    x.add_argument("--n", type=_positive_int, default=25, help="trials per input row")
    x.add_argument("--out", default=None, help="write full JSON (every trial) here")
    x.set_defaults(func=cmd_xor)

    l = sub.add_parser("latch", help="SR latch demo (+ optional hold-error measurement)")
    _common(l)
    l.add_argument("--vote", choices=VOTE_MODES, default="none")
    l.add_argument("--hold-cycles", type=_nonnegative_int, default=5)
    l.add_argument("--trials", type=_nonnegative_int, default=0, help="if >0, measure hold error over this many trials")
    l.add_argument("--out", default=None, help="write the trace + measurement JSON here")
    l.add_argument("--workers", type=_positive_int, default=1, help="hold trials run side by side (each trial is serial)")
    l.set_defaults(func=cmd_latch)

    r = sub.add_parser("rule110", help="Rule 110 with one JEV call per cell update")
    _common(r)
    r.add_argument("--init", default="1010100111000111", help="initial bits placed at x=0")
    r.add_argument("--background", default="ether", help="zero | ether | custom 0/1 period string")
    r.add_argument("--pad", type=_nonnegative_int, default=21, help="background cells shown on each side at t=0")
    r.add_argument("--steps", type=_nonnegative_int, default=64)
    r.add_argument("--vote", choices=VOTE_MODES, default="none")
    r.add_argument("--workers", type=_positive_int, default=1,
                   help="parallel calls within one step (vote=none only); results identical to serial")
    r.add_argument("--out", default=None, help="path prefix; writes <out>.json and <out>.png")
    r.add_argument("--no-png", action="store_true")
    r.add_argument("--scale", type=_positive_int, default=4)
    r.add_argument("--record-argv", action="store_true", help="store the command line in the run JSON")
    r.set_defaults(func=cmd_rule110)

    n = sub.add_parser("live-nand", help="bounded LIVE NAND truth-table run (paid; needs explicit approval flag)")
    n.add_argument("--out", required=True, help="new run directory (never overwritten)")
    n.add_argument("--per-row", type=_positive_int, default=1, help="blocks; each block runs 00/01/10/11 once")
    n.add_argument("--max-calls", type=_positive_int, default=4)
    n.add_argument("--max-usd", type=float, default=0.01)
    n.add_argument("--reserve-usd", type=float, default=0.0001,
                   help="cost assumed per call when the gateway reports none (and pre-call headroom)")
    n.add_argument("--seed", type=int, default=0, help="schedule shuffle seed (order only)")
    n.add_argument("--label", default="live")
    n.add_argument("--busy-retries", type=_nonnegative_int, default=3,
                   help="retry only when the host is busy/unreachable (429/5xx), never on an answer")
    n.add_argument("--i-approve-live-calls", action="store_true")
    n.set_defaults(func=cmd_live_nand)

    s = sub.add_parser("site-data", help="wrap a run JSON as site/data/recorded-run.js")
    s.add_argument("run")
    s.add_argument("--out", default="site/data/recorded-run.js")
    s.add_argument("--var", default="JEV_RECORDED_RUN", choices=["JEV_RECORDED_RUN", "JEV_LIVE_RUN"])
    s.add_argument("--ledger", default=None, help="live run: per-call ledger to merge P(true) and cost from")
    s.set_defaults(func=cmd_site_data)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (JevNotConfiguredError, LiveRefused) as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    except Exception as exc:  # live stop conditions: failed call or cap reached
        from .live_backend import BudgetExhausted
        from .live_client import LiveCallError
        if isinstance(exc, (BudgetExhausted, LiveCallError)):
            print("stopped:", exc, file=sys.stderr)
            return 1
        raise
