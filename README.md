# jev-turing

**JEV as a diode-like primitive → gates → latch → Rule 110.**

Jev (`typesafe-ai/jev`) is a fast decision model made by TypeSafe AI and served here through
Vercel AI Gateway: one question in, a probability of "true" out. This is an independent
experiment; the author has no affiliation with TypeSafe AI or Vercel.
**There's a parody ad.** `site/media/ad-jev.mp4` is a fake 33-second "paid ad" for Jev
(not sponsored, not real); the site (`site/index.html`) is its fine print at readable
size, with every call replayable. Every number in both is generated from the recorded runs
below (`python -m jev_turing.media_ad`).

This repo treats one JEV judgment as the only logic primitive and builds upward:

1. **Gates.** NOT, NAND and NOR are each exactly **one** JEV judgment. A spec frames the
   question; JEV decides; glue only moves bits.
2. **Latch.** Two cross-coupled JEV NANDs form an SR latch that holds a bit.
3. **Rule 110.** Every cell update is one JEV judgment on its 3-cell neighbourhood.
   The tape grows on demand over a periodic background (zero or the Rule 110 ether),
   with a ground-truth checker and an error counter running alongside.

**Site:** https://alexanderpico.github.io/jev-turing/ (the ad, its fine print, and a
click-any-cell replay of every call).
**Raw logs:** every request and response from every live run, in
[`raw-logs/jev-turing-raw-logs-2026-10-09.tar.gz`](raw-logs/) (1.7 MB; 22 MB unpacked).

## Live results (2026-10-09, real `typesafe-ai/jev` via Vercel AI Gateway)

Every call was one Boolean question; no voting, no retries, the answer table never
sent. Full ledgers and the written summary (`live-results-2026-10-09.md`) are in the
raw-logs archive above.

| Step | Calls | Result | Cost |
|---|---:|---|---:|
| NAND truth table, 25 per row | 100 | 100/100; P(true) 0.98-0.99 or 0.02 | $0.0014 |
| XOR from 4 chained NANDs, 25 per row | 400 | 100/100 outputs, 0 wrong gates | $0.0055 |
| SR latch: demo + 10 write/5-hold trials | 180 | 0 write, 0 hold, 0 transient losses | $0.0025 |
| **SR latch, 1,000 write/5-hold trials** | 15,030 | **1,000/1,000** kept the bit at every hold; P(true) >=0.98 or <=0.02 | $0.2071 |
| Rule 110 rule, v1 wording ("Wolfram's rule 110") | 39 | **failed**: P(true) 0.4-0.75, row 100 wrong 6/6 | $0.0005 |
| Rule 110 rule, v2 wording (rule stated in one sentence) | 80 | 80/80; P(true) >=0.97 or <=0.09 | $0.0013 |
| Rule 110, single cell, 20 steps | 385 | 0 wrong cell updates, 0 divergent cells | $0.0063 |
| **NAND, 1,000 per row** | 4,000 | **4,000/4,000**; P(true) 0.98-0.99 or 0.01-0.02 | $0.0551 |
| **Rule 110, ether background, 64 steps** | 4,771 | **0 wrong cell updates**, 0 divergent cells; every P(true) >=0.96 or <=0.09 | $0.0781 |
| **Rule 110, ether background, 200 steps** (6 parallel calls per step) | 26,340 | **0 wrong cell updates**, 0 divergent cells; every P(true) >=0.96 or <=0.09 | $0.4314 |

What this does and does not show: Jev computes NAND and the Rule 110 local rule
reliably, its outputs compose with no cleanup, and two cross-coupled NAND calls hold a
bit. About 51,500 graded live calls had zero errors. That bounds the per-call error rate (95% confidence) below about 0.1% for
NAND (4,000 calls) and below about 0.01% for the Rule 110 rule (31,576 calls across all
v2 runs); it does not pin it down. A 200-step, 224-cell run is a demonstration, not
universality, and the claims hold for the exact wording below. The site plays the live
200-step run by default (`runs/rule110-ether-200-live.*`); the 64-step live run and the
FakeJEV recording are kept in `runs/`.
Jev did **not** know "rule 110" by name: the rule has to be stated in plain words.
Pinning one host (`typesafe-ai`) hit HTTP 429 capacity limits, so the default lets
the gateway choose a host for the same model and logs which one answered.

### Exact wording used (live runs)

Every live call sends one Boolean question built from the spec, plus the inputs as
state (e.g. `L=true; C=false; R=true`). The answer table is never sent. Wording in
`jev_turing/gates.py` (NAND) and `jev_turing/rule110.py` (`RULE110_SPEC`, version 2):

- **NAND** question: "Inputs A and B are bits (true or false). Is it NOT the case that
  both A and B are true?" true = "At least one of A, B is false.", false = "A and B are
  both true."
- **Rule 110** question: "L, C and R are three adjacent cells (left neighbour, the cell,
  right neighbour), each on (true) or off (false). Rule: the cell is on at the next
  step exactly when C or R is on, unless L, C and R are all on. Is the cell on at the
  next step?" true = "C or R is on, and L, C and R are not all on.", false = "C and R
  are both off, or L, C and R are all on."

Results are claims about this wording only. Version 1 ("Under Wolfram's elementary rule
110, is the middle cell on at the next step?") failed and was not used for any run.

## Design notes

The gate/latch branch and the Rule 110 branch share a decision backend; Rule 110
is not built out of NAND gates (each cell update is one direct judgment).

The latch harness reports both final-read error and "lost at any point" (Q wrong, or
Q==Qb, after any hold cycle, even if it later recovered). Under FakeJEV noise the second
number is much higher, because a noisy latch can lose and regain its bit. The per-cycle
estimate is a model assumption, not a measured failure hazard.
Rule 110 divergence counts the represented window plus one background period;
the noisy background ring repeats its outputs across the implicit far field.

## Honest-claims rule

- **The brief's wording rules.** See [`docs/brief.md`](docs/brief.md): say
  "universal given unbounded cells", never "Turing-complete" on its own; show the
  error budget or use triple voting; glue never decides.
- **FakeJEV results are not JEV results.** `runs/rule110-ether-p0.001-seed2.*` comes from
  `FakeJEV`, an offline simulator. `runs/rule110-ether-live.*` is the live run. The site
  labels which one is playing, and makes no network calls in either case.
- **Live JEV only on request.** `--backend live` (gates, xor, latch, rule110) and
  `live-nand` refuse to run without `--i-approve-live-calls`; `--backend live` also needs
  a new `--ledger` file and enforces `--max-calls` / `--max-usd` across the whole command.
  The default backend is still `fake`. Jev needs purchased Vercel AI Gateway credit:
  the free tier and the monthly free credit return HTTP 403.
- **The site makes no calls.** It is static (GitHub Pages) and replays recorded runs; the
  API key never leaves the machine that made the runs.

## How JEV is called (mirrors jev-tables)

jev-tables (a separate, private project) calls an evaluator object with an `identity`
string and `evaluate(selected_fields, taxonomy) -> {"choice", "probabilities", "provenance"}`,
then validates the envelope before trusting it. `jev_turing/backend.py` keeps that exact
shape: a judgment spec is a taxonomy whose categories are exactly `true` / `false`, and
`judge()` makes one `evaluate` call and maps `choice == "true"` to a bool.

## Layout

```
jev_turing/
  backend.py   JudgmentBackend protocol, binary specs, judge(), JevAdapter (disabled stub), FakeJEV
  gates.py     NOT/NAND/NOR (one judgment each), triple voting, truth-table harness, error budget
  latch.py     SR latch from two cross-coupled JEV NANDs; hold-error measurement
  rule110.py   growing tape, one judgment per cell, ground-truth checker, JSON + PNG output
  cli.py       python -m jev_turing {gates,xor,latch,rule110,live-nand,site-data}
  live_client.py  Vercel AI Gateway /v1/evaluate client (P(true) -> bit), injectable transport
  live_backend.py CappedLiveJev: drop-in live backend with call/USD caps and a per-call ledger
  live_nand.py    bounded live NAND run: balanced schedule, caps, ledger, summary
runs/          recorded Rule 110 runs: FakeJEV (p=0.001) and live Jev, JSON + PNG
site/          "the fine print": ad video, click-any-cell replay of every call, limits
               (static, no network calls; data in site/data/, incl. ad-facts.js)
docs/brief.md  the brief: what to prove and how to word it
raw-logs/      every live request/response, compressed
site/media/    video + stills rendered from recorded runs (python -m jev_turing.media);
               parody ad + soundtrack (python -m jev_turing.media_ad; needs numpy + ffmpeg)
tests/         pytest (network access is blocked during tests)
```

## Run it locally

```sh
git clone https://github.com/AlexanderPico/jev-turing && cd jev-turing
# Requires Python >=3.11; macOS /usr/bin/python3 may be too old.
/opt/homebrew/bin/python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

.venv/bin/pytest -q

# Gate harness: NAND truth-table accuracy, 5% flip rate, all vote modes
.venv/bin/python -m jev_turing gates --gate NAND --n 1000 --error-rate 0.05 --vote all

# Latch demo, plus a hold-error measurement under noise
.venv/bin/python -m jev_turing latch --hold-cycles 5
.venv/bin/python -m jev_turing latch --error-rate 0.01 --trials 1000 --hold-cycles 10

# Rule 110 (re-creates the recorded run), then refresh the site data
.venv/bin/python -m jev_turing rule110 --error-rate 0.001 --seed 2 --out runs/rule110-ether-p0.001-seed2
.venv/bin/python -m jev_turing site-data runs/rule110-ether-p0.001-seed2.json
# Live run for the site (merges per-call P(true) and cost from its ledger, cross-checked)
.venv/bin/python -m jev_turing site-data runs/rule110-ether-200-live.json --var JEV_LIVE_RUN \
  --ledger raw-logs/jev-turing-raw-logs-2026-10-09/live-r110-ether-200-20261009/calls.jsonl \
  --out site/data/live-run.js

# Site: open directly, or serve locally
open site/index.html
# or: .venv/bin/python -m http.server -d site 8000   (then http://localhost:8000)
```

`--backend jev` exists only to show the disabled seam: it exits with an error.

### Live runs (paid; needs purchased Vercel AI Gateway credit)

```sh
# needs JEV_AI_GATEWAY_API_KEY (environment, or ~/.hermes/.env)
R=experiments/<new-id>; mkdir -p $R
LIVE="--backend live --i-approve-live-calls --max-usd 0.01 --ledger $R/calls.jsonl"
.venv/bin/python -m jev_turing xor $LIVE --max-calls 400 --n 25 --out $R/xor.json
.venv/bin/python -m jev_turing latch $LIVE --max-calls 300 --trials 10 --hold-cycles 5 --out $R/latch.json
.venv/bin/python -m jev_turing rule110 $LIVE --max-calls 400 --init 1 --background zero --pad 6 \
  --steps 20 --out $R/rule110 --scale 12
# 200 steps on the ether: ~26,340 calls, ~43 cents, ~25 min with 6 parallel calls per step
.venv/bin/python -m jev_turing rule110 $LIVE --max-calls 27000 --max-usd 0.60 --steps 200 \
  --workers 6 --out $R/rule110-ether-200-live --record-argv
```
Each command stops on the first failed call or when a cap is reached (exit 1).
A busy host (HTTP 429/502/503/504 or no connection) is retried up to 3 times with
backoff; that is the only retry, it happens before any answer exists, and it is logged.
At about $0.000014 per call, 1 cent buys roughly 700 calls.

### Live NAND test

```sh
# 4-call format check, then 25 blocks x 4 rows = 100 calls; hard cap 1 cent each run
.venv/bin/python -m jev_turing live-nand --i-approve-live-calls --per-row 1 --max-calls 4 \
  --max-usd 0.01 --label format-probe --out experiments/<new-id>
.venv/bin/python -m jev_turing live-nand --i-approve-live-calls --per-row 25 --max-calls 100 \
  --max-usd 0.01 --label nand-100 --out experiments/<new-id>
```

What it does (`jev_turing/live_client.py`, `jev_turing/live_nand.py`):
- sends the NAND question, its true/false definitions and `A=..; B=..`, and never
  the answer table;
- maps Jev's native `P(true)` to a bit at 0.5 and keeps the raw probability;
- runs serially, with no retries and no fallback models, and stops at the first
  failed or invalid response; wrong answers are counted, not repaired;
- writes `manifest.json`, `attempts.jsonl` (a pending line before each request) and
  `summary.json` into a new, private directory that it never overwrites.
`latency_ms` in logs is the wall-clock time of the fake call, not a JEV latency model.

The recorded run (`runs/rule110-ether-p0.001-seed2.*`): ether background, 64 steps,
FakeJEV p=0.001, seed 2. It took 4,855 calls (3,959 tape + 896 background ring) and the
checker counted 6 wrong cell updates, with 34 cells diverged from ground truth by the end.
Re-running reproduces the cells and counters; the `latency_ms` values will differ.
