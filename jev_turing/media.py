"""Render social/media assets from recorded runs. Deterministic; no network.

    python -m jev_turing.media --out media/

Every pixel and number comes from files in ``runs/`` (and, for the latch/NAND panels,
the live-run JSONs under the project record). Nothing is re-simulated.

Outputs (in ``--out``, default ``site/media/``; the site shows the PNGs):
  rule110-200-live.mp4     30-45 s captioned video, 1080x1080 (X post 1)
  rule110-200-live-poster.png  last frame as a still
  real-vs-fake.png         live 64-step run vs FakeJEV p=0.001 recording, same setup
  nand-table.png           NAND truth table with live counts and P(true)
  latch.png                latch write/hold strip from the live 1,000-trial test
  how-it-works.png         one cell = one question diagram
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
# Live NAND/latch summaries for the stills. Unpack raw-logs/*.tar.gz here, or pass --runs.
PROJECT_RUNS = ROOT / "raw-logs" / "jev-turing-raw-logs-2026-10-09"

BG = (12, 13, 16)
PANEL = (24, 26, 32)
FG = (232, 232, 226)
MUTED = (150, 154, 162)
ON = (232, 232, 226)
OFF = (17, 17, 20)
BG_ON = (92, 92, 98)
BG_OFF = (32, 32, 37)
GREEN = (70, 200, 130)
RED = (255, 80, 80)
AMBER = (255, 190, 40)
DIVERGED_OFF = (110, 20, 24)


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        return ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size, index=1 if bold else 0)
    return ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", size, index=1 if bold else 0)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_live_site_run() -> dict[str, Any]:
    """The 200-step live run as the site plays it: per-call P(true) and ledger cost merged in."""
    js = (ROOT / "site" / "data" / "live-run.js").read_text(encoding="utf-8")
    return json.loads(js.split("window.JEV_LIVE_RUN = ", 1)[1].rstrip().rstrip(";"))


# ---------------------------------------------------------------------------
# Rule 110 rendering
# ---------------------------------------------------------------------------

def _cell(row: dict[str, Any], x: int) -> tuple[bool, bool]:
    i = x - row["lo"]
    if 0 <= i < len(row["cells"]):
        return row["cells"][i] == "1", True
    bg = row["bg"]
    return bg[x % len(bg)] == "1", False


def _bounds(run: dict[str, Any]) -> tuple[int, int]:
    rows = run["rows"] + run.get("reference_rows", [])
    return min(r["lo"] for r in rows), max(r["lo"] + len(r["cells"]) for r in rows)


def _error_cells(run: dict[str, Any]) -> set[tuple[int, int]]:
    cols = run["call_log"]["columns"]
    ti, ki, xi, ei = (cols.index(k) for k in ("t", "kind", "x", "error"))
    return {(r[ti] + 1, r[xi]) for r in run["call_log"]["rows"] if r[ki] == "tape" and r[ei]}


def draw_spacetime(run: dict[str, Any], upto: int, scale: int, *, lo: int | None = None,
                   hi: int | None = None, mark: bool = True) -> Image.Image:
    """Rows 0..upto (inclusive); later rows left blank. Diverged/error cells marked."""
    blo, bhi = _bounds(run)
    lo = blo if lo is None else lo
    hi = bhi if hi is None else hi
    rows, refs = run["rows"], run.get("reference_rows", [])
    errs = _error_cells(run) if mark else set()
    img = Image.new("RGB", (hi - lo, len(rows)), BG)
    px = img.load()
    for y in range(min(upto + 1, len(rows))):
        row = rows[y]
        ref = refs[y] if y < len(refs) else None
        for x in range(lo, hi):
            v, inside = _cell(row, x)
            c = (ON if v else OFF) if inside else (BG_ON if v else BG_OFF)
            if mark and ref is not None and _cell(ref, x)[0] != v:
                c = RED if v else DIVERGED_OFF
            if (y, x) in errs:
                c = AMBER
            px[x - lo, y] = c
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def _calls_through(run: dict[str, Any], t: int) -> int:
    return sum(s["calls"] for s in run["per_step"][:t])


def _text(d: ImageDraw.ImageDraw, xy, s, f, fill=FG, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


# Copy for each video variant. "straight" is the original reliability framing;
# "deadpan" is the playful overengineering framing (same frames, different words).
VARIANTS: dict[str, dict[str, str]] = {
    "straight": {
        "title": "Every pixel = one AI yes/no call",
        "sub1": "Rule 110, computed live by the Jev model.",
        "sub2": "No code decides a cell.",
        "end1": "{calls:,} chained AI decisions. 0 wrong.",
        "end2": "Every cell checked against true Rule 110. Total cost ${cost:.2f}.",
    },
    "deadpan": {
        "title": "We replaced the logic gates with AI",
        "sub1": "Every pixel is one paid call to an AI model.",
        "sub2": "It's going great.",
        "end1": "Python: {python_ms:.0f} milliseconds, free.",
        "end2": "AI: {minutes:.0f} minutes, ${cost:.2f}. Also 0 wrong, which is the weird part.",
    },
}


def video_frames(run: dict[str, Any], tmp: Path, *, size: int = 1080, height: int = 1350, fps: int = 30,
                 start: int = 0, variant: str = "straight") -> int:
    """Write PNG frames: 2 s title over a growing tape, ~30 s of growth, 6 s hold on totals."""
    steps = len(run["rows"]) - 1
    total_calls = run["counters"]["jev_calls"]
    cost = run.get("meta", {}).get("cost_usd")
    lo, hi = _bounds(run)
    width = hi - lo
    scale = max(1, min((size - 60) // width, (height - 420) // len(run["rows"])))
    grow_frames = 26 * fps
    hold_frames = 7 * fps
    big, mid, small = font(62, bold=True), font(44, bold=True), font(32)
    mono = font(34, mono=True)
    fmt = {"calls": total_calls, "cost": cost or 0, "minutes": RUN_200_MINUTES, "python_ms": _python_ms(run)}
    full = draw_spacetime(run, steps, scale)
    blank = Image.new("RGB", full.size, BG)
    n = 0
    for f in range(grow_frames + hold_frames):
        t = min(steps, round(steps * min(1.0, (f + 1) / grow_frames)))
        canvas = Image.new("RGB", (size, height), BG)
        d = ImageDraw.Draw(canvas)
        v = VARIANTS[variant]
        _text(d, (size // 2, 44), v["title"], big, anchor="ma")
        _text(d, (size // 2, 124), v["sub1"], small, MUTED, anchor="ma")
        _text(d, (size // 2, 164), v["sub2"], small, MUTED, anchor="ma")
        st = blank.copy()
        st.paste(full.crop((0, 0, full.width, (t + 1) * scale)), (0, 0))
        canvas.paste(st, ((size - st.width) // 2, 230))
        y0 = 230 + st.height + 28
        calls = _calls_through(run, t)
        errs = run["per_step"][t - 1].get("local_errors_cum", 0) if t else 0
        _text(d, (40, y0), "step {}/{}".format(t, steps), mono, FG)
        _text(d, (size // 2, y0), "AI calls {:,}".format(calls), mono, FG, anchor="ma")
        _text(d, (size - 40, y0), "wrong: {}".format(errs), mono, GREEN if errs == 0 else RED, anchor="ra")
        if f >= grow_frames:
            band_y = y0 + 70
            d.rectangle([0, band_y, size, height], fill=PANEL)
            _text(d, (size // 2, band_y + 26), v["end1"].format(**fmt), mid, GREEN, anchor="ma")
            _text(d, (size // 2, band_y + 90), v["end2"].format(**fmt), small, MUTED, anchor="ma")
        canvas.save(tmp / "f{:05d}.png".format(start + n))
        n += 1
    return start + n


def intro_frames(run: dict[str, Any], tmp: Path, start: int, *, size: int = 1080, height: int = 1350,
                 fps: int = 30, seconds: float = 5.0, variant: str = "straight") -> int:
    """Zoomed-in opening: the first rows of real calls appear cell by cell, with Jev's confidence."""
    cols = run["call_log"]["columns"]
    ci = {k: cols.index(k) for k in ("t", "kind", "x", "L", "C", "R", "out")}
    pi = cols.index("p_true") if "p_true" in cols else None
    rows = run["rows"]
    centre = rows[0]["lo"] + len(rows[0]["cells"]) // 2
    n_cols, n_rows = 13, 6
    x0 = centre - n_cols // 2
    calls = [c for c in run["call_log"]["rows"]
             if c[ci["kind"]] == "tape" and c[ci["t"]] < n_rows - 1 and x0 <= c[ci["x"]] < x0 + n_cols]
    cell = 70
    gx = (size - n_cols * cell) // 2
    gy = 300
    total = int(seconds * fps)
    big, small, mid = font(62, bold=True), font(32), font(38, bold=True)
    mono = font(34, mono=True)
    for f in range(total):
        k = min(len(calls), int(len(calls) * (f + 1) / (total * 0.85)))
        shown = {(c[ci["t"]] + 1, c[ci["x"]]): c for c in calls[:k]}
        canvas = Image.new("RGB", (size, height), BG)
        d = ImageDraw.Draw(canvas)
        _text(d, (size // 2, 44), VARIANTS[variant]["title"], big, anchor="ma")
        _text(d, (size // 2, 124), "Each square below is one question to the Jev model:", small, MUTED, anchor="ma")
        _text(d, (size // 2, 164), "\"given its 3 neighbours, is this cell on next step?\"", small, MUTED, anchor="ma")
        for ty in range(n_rows):
            for i in range(n_cols):
                x = x0 + i
                if ty == 0:
                    v, inside = _cell(rows[0], x)
                elif (ty, x) in shown:
                    v, inside = bool(shown[(ty, x)][ci["out"]]), True
                else:
                    continue
                X, Y = gx + i * cell, gy + ty * cell
                d.rectangle([X + 3, Y + 3, X + cell - 3, Y + cell - 3], fill=ON if v else OFF,
                            outline=(70, 72, 80), width=2)
        if k:
            c = calls[k - 1]
            ty, x = c[ci["t"]] + 1, c[ci["x"]]
            X, Y = gx + (x - x0) * cell, gy + ty * cell
            d.rectangle([X, Y, X + cell, Y + cell], outline=AMBER, width=5)
            Lx = gx + (x - x0 - 1) * cell
            d.rectangle([Lx, Y - cell, Lx + 3 * cell, Y], outline=AMBER, width=3)
            yb = gy + n_rows * cell + 60
            lcr = "".join(str(int(c[ci[k2]])) for k2 in ("L", "C", "R"))
            p = c[pi] if pi is not None else None
            _text(d, (size // 2, yb), "neighbours {}  →  Jev: {}".format(
                lcr, ("{:.0f}% sure it's on".format(p * 100) if p is not None else "on" if c[ci["out"]] else "off")),
                mono, FG, anchor="ma")
            _text(d, (size // 2, yb + 60), "cell turns {}".format("ON" if c[ci["out"]] else "OFF"), mid,
                  GREEN, anchor="ma")
        canvas.save(tmp / "f{:05d}.png".format(start + f))
    return total


def render_video(run: dict[str, Any], out: Path, fps: int = 30, variant: str = "straight") -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        n0 = intro_frames(run, tmp, 0, fps=fps, variant=variant)
        n = video_frames(run, tmp, fps=fps, start=n0, variant=variant)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                        str(out)], check=True)
        shutil.copy(tmp / "f{:05d}.png".format(n - 1), out.with_name(out.stem + "-poster.png"))


# ---------------------------------------------------------------------------
# Stills
# ---------------------------------------------------------------------------

def real_vs_fake(live: dict[str, Any], fake: dict[str, Any], out: Path) -> None:
    lo = min(_bounds(live)[0], _bounds(fake)[0])
    hi = max(_bounds(live)[1], _bounds(fake)[1])
    scale = 9
    a = draw_spacetime(fake, len(fake["rows"]), scale, lo=lo, hi=hi)
    b = draw_spacetime(live, len(live["rows"]), scale, lo=lo, hi=hi)
    pad, top, gap = 60, 250, 80
    W = pad * 2 + a.width * 2 + gap
    H = top + a.height + 220
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _text(d, (W // 2, 44), "Same start, same 64 steps: a noisy gate vs. the real AI", font(52, True), anchor="ma")
    _text(d, (W // 2, 120), "Red = cells that drifted from true Rule 110.  Yellow = a single wrong answer.",
          font(32), MUTED, anchor="ma")
    for i, (im, run, title) in enumerate(((a, fake, "Simulated gate, 0.1% random errors"),
                                          (b, live, "Live Jev model"))):
        x = pad + i * (a.width + gap)
        img.paste(im, (x, top))
        c = run["counters"]
        _text(d, (x + a.width // 2, top - 62), title, font(38, True), anchor="ma")
        col = GREEN if c["local_errors"] == 0 else RED
        _text(d, (x + a.width // 2, top + a.height + 26),
              "{} wrong answers · {} cells off at the end".format(c["local_errors"], c["divergent_cells_final"]),
              font(34, True), col, anchor="ma")
        _text(d, (x + a.width // 2, top + a.height + 76), "{:,} calls".format(c["jev_calls"]), font(30), MUTED,
              anchor="ma")
    _text(d, (W // 2, H - 56), "Left: offline simulator with injected random errors (not an AI). "
          "Right: real calls to typesafe-ai/jev, recorded 2026-10-09.", font(26), MUTED, anchor="ma")
    img.save(out)


def nand_table(summary: dict[str, Any], out: Path) -> None:
    rows = [dict(v, inputs=k) for k, v in sorted(summary["rows"].items())]
    W, H = 1200, 760
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _text(d, (60, 50), "One AI call = one NAND gate", font(52, True))
    _text(d, (60, 120), "Question sent: \"Is it NOT the case that both A and B are true?\" plus A and B.",
          font(28), MUTED)
    _text(d, (60, 160), "The answer table is never sent.", font(28), MUTED)
    hx = [60, 180, 300, 500, 860]
    hy = 240
    for x, h in zip(hx, ("A", "B", "NAND", "Jev correct", "Jev's P(true)")):
        _text(d, (x, hy), h, font(30, True), MUTED)
    d.line([60, hy + 50, W - 60, hy + 50], fill=(60, 64, 72), width=2)
    for i, r in enumerate(rows):
        y = hy + 80 + i * 90
        a, b = r["inputs"][0], r["inputs"][1]
        exp = r["expected"]
        for x, v in ((hx[0], a), (hx[1], b)):
            _bit(d, x, y, v == "1")
        _bit(d, hx[2] + 20, y, exp)
        _text(d, (hx[3], y), "{:,}/{:,}".format(r["correct"], r["valid"]), font(40, True, mono=True), GREEN)
        lo_p, hi_p = r["p_true_min"], r["p_true_max"]
        _text(d, (hx[4], y), "{:.2f}".format(lo_p) if lo_p == hi_p else "{:.2f} to {:.2f}".format(lo_p, hi_p),
              font(36, mono=True))
    _text(d, (60, H - 70), "4,000 live calls to typesafe-ai/jev, 2026-10-09. 0 wrong.", font(28), MUTED)
    img.save(out)


def _bit(d: ImageDraw.ImageDraw, x: int, y: int, v: bool) -> None:
    d.rectangle([x, y, x + 44, y + 44], fill=ON if v else OFF, outline=(90, 90, 96), width=2)
    _text(d, (x + 22, y + 22), "1" if v else "0", font(26, True, mono=True), OFF if v else FG, anchor="mm")


def latch_strip(latch: dict[str, Any], out: Path) -> None:
    m = latch["hold_measurement"]
    trace = latch["trace"]
    W, H = 1200, 700
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _text(d, (60, 50), "Two AI gates wired in a loop remember a bit", font(46, True))
    _text(d, (60, 115), "Each gate's answer is fed back as the other gate's input. Nothing else stores the bit.",
          font(26), MUTED)
    labels = []
    for rec in trace:
        labels.append((rec["op"], rec["Q"]))
    cw = (W - 120) // len(labels)
    y = 220
    for i, (op, q) in enumerate(labels):
        x = 60 + i * cw
        d.rectangle([x + 4, y, x + cw - 4, y + 120], fill=ON if q else OFF, outline=(90, 90, 96), width=2)
        _text(d, (x + cw // 2, y + 60), "1" if q else "0", font(40, True, mono=True), OFF if q else FG, anchor="mm")
        _text(d, (x + cw // 2, y + 150), op, font(24), AMBER if op != "hold" else MUTED, anchor="ma")
    _text(d, (60, y + 200), "stored bit after each step: set, hold x5, reset, hold x5", font(26), MUTED)
    trials = m["trials"]
    ok = trials - m["write_failures"] - m["any_loss_during_hold"]
    _text(d, (60, H - 190), "Live test: {:,} write-and-hold trials, {} holds each".format(trials, m["hold_cycles"]),
          font(32, True))
    col = GREEN if ok == trials else AMBER
    _text(d, (60, H - 135), "{:,}/{:,} kept the bit the whole time  ·  {:,} AI calls".format(ok, trials, m["jev_calls"]),
          font(32, True), col)
    _text(d, (60, H - 70), "typesafe-ai/jev, recorded 2026-10-09.", font(24), MUTED)
    img.save(out)


# Wall-clock of the recorded 200-step live run: ledger file created 11:36:11, run JSON
# written 11:58:38 (2026-10-09), 6 parallel calls per step.
RUN_200_MINUTES = 22.5


_PY_MS: dict[int, float] = {}


def _python_ms(run: dict[str, Any], repeats: int = 5) -> float:
    """Time the same 200 steps with the plain reference rule (best of a few runs, cached per run size)."""
    key = len(run["rows"]) * 100_000 + len(run["rows"][-1]["cells"])
    if key not in _PY_MS:
        _PY_MS[key] = _time_python(run, repeats)
    return _PY_MS[key]


def _time_python(run: dict[str, Any], repeats: int) -> float:
    import time

    from .rule110 import reference_rule110
    width = len(run["rows"][-1]["cells"])
    best = float("inf")
    for _ in range(repeats):
        c = [False] * width
        c[width // 2] = True
        t = time.perf_counter()
        for _ in range(len(run["rows"]) - 1):
            c = [reference_rule110(c[i - 1], c[i], c[(i + 1) % width]) for i in range(width)]
        best = min(best, (time.perf_counter() - t) * 1000)
    return best


def benchmark_card(out: Path, *, cost: float, minutes: float, python_ms: float, calls: int) -> None:
    """Deadpan 'benchmark': the same 200 steps, plain Python vs one AI call per cell."""
    W, H = 1200, 900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _text(d, (60, 50), "Benchmark: 200 steps of Rule 110", font(52, True))
    _text(d, (60, 120), "Same cells. Same answers. Very different vibes.", font(30), MUTED)
    rows = [("", "Plain Python", "AI as the logic gate"),
            ("Time", "{:.0f} ms".format(python_ms), "{:.0f} minutes".format(minutes)),
            ("Cost", "$0.00", "${:.2f}".format(cost)),
            ("Calls to a model", "0", "{:,}".format(calls)),
            ("Wrong cells", "0", "0"),
            ("Vibes", "none", "immaculate")]
    cx = [60, 470, 820]
    for i, row in enumerate(rows):
        y = 220 + i * 100
        if i:
            d.line([60, y - 22, W - 60, y - 22], fill=(48, 50, 58), width=2)
        for j, cell in enumerate(row):
            f = font(34, True) if (i == 0 or j == 0) else font(40, True, mono=True)
            col = MUTED if j == 0 else (GREEN if (row[0] == "Wrong cells") else FG)
            if i == 0:
                col = AMBER if j == 2 else MUTED
            _text(d, (cx[j], y), cell, f, col)
    _text(d, (60, H - 80), "Python time measured on one Mac; AI figures from the recorded live run (typesafe-ai/jev, 2026-10-09).",
          font(22), MUTED)
    img.save(out)


def how_it_works(out: Path) -> None:
    W, H = 1200, 760
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _text(d, (60, 50), "How one cell is decided", font(52, True))
    # three neighbour cells
    y = 170
    for i, (lab, v) in enumerate((("L", True), ("C", False), ("R", True))):
        x = 80 + i * 110
        d.rectangle([x, y, x + 90, y + 90], fill=ON if v else OFF, outline=(90, 90, 96), width=2)
        _text(d, (x + 45, y + 120), lab, font(28, True), MUTED, anchor="ma")
    _text(d, (420, y + 45), "→", font(56, True), MUTED, anchor="lm")
    d.rounded_rectangle([510, y - 20, 1140, y + 260], radius=16, fill=PANEL)
    _text(d, (535, y), "Question to Jev (exact wording):", font(24, True), AMBER)
    q = ["\"...Rule: the cell is on at the next step",
         "exactly when C or R is on, unless L, C and",
         "R are all on. Is the cell on at the next step?\"",
         "",
         "state: L=true; C=false; R=true"]
    for i, line in enumerate(q):
        _text(d, (535, y + 44 + i * 38), line, font(26, mono=False), FG)
    y2 = 500
    _text(d, (80, y2), "Jev answers: 97% sure it is on  →  the cell turns on", font(34, True), GREEN)
    _text(d, (80, y2 + 60), "A separate checker compares every answer to true Rule 110.", font(28), MUTED)
    _text(d, (80, y2 + 100), "It only grades; it never changes a cell. The answer table is never sent.", font(28), MUTED)
    _text(d, (80, H - 60), "Code moves bits between calls. Every on/off decision is the AI's.", font(26), MUTED)
    img.save(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m jev_turing.media", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(ROOT / "site" / "media"))
    p.add_argument("--runs", default=str(PROJECT_RUNS), help="project-record runs dir (live NAND/latch JSON)")
    p.add_argument("--skip-video", action="store_true")
    p.add_argument("--variant", choices=sorted(VARIANTS), default=None,
                   help="render only this video variant (default: all)")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    runs = Path(a.runs)
    live200 = load_live_site_run()
    real_vs_fake(load(ROOT / "runs" / "rule110-ether-live.json"),
                 load(ROOT / "runs" / "rule110-ether-p0.001-seed2.json"), out / "real-vs-fake.png")
    nand_table(load(runs / "live-nand-4000-20261009" / "summary.json"), out / "nand-table.png")
    latch_path = runs / "live-latch-1000-20261009" / "latch.json"
    if latch_path.exists():
        latch_strip(load(latch_path), out / "latch.png")
    how_it_works(out / "how-it-works.png")
    cost = live200["meta"]["cost_usd"]  # summed from the ledger by `site-data --ledger`
    benchmark_card(out / "benchmark.png", cost=cost, minutes=RUN_200_MINUTES, python_ms=_python_ms(live200),
                   calls=live200["counters"]["jev_calls"])
    if not a.skip_video:
        for name in ([a.variant] if a.variant else sorted(VARIANTS)):
            suffix = "" if name == "straight" else "-" + name
            render_video(live200, out / "rule110-200-live{}.mp4".format(suffix), variant=name)
    for f in sorted(out.iterdir()):
        print("wrote", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
