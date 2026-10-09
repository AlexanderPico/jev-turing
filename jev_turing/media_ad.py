"""Parody "paid ad" for Jev, cut like a tech-launch spot. Hype up front, honest footnotes.

    python -m jev_turing.media_ad            # writes site/media/ad-jev.mp4 (+ poster) and ad-print.png

Not a real ad. Every number is computed from the recorded live runs; nothing is typed in by
hand. Borrowed ad grammar (see projects/jev-turing/rollout/concept-d-fake-ad.md):

- Apple launch films: one phrase per beat, black background, big number slams, "Meet ...".
- Apple spec pages: superscript footnotes, "Testing conducted by ... using ...".
- Apple keynote charts: a confident chart, vaguely labelled "relative".
- Mac vs PC / Samsung "Ingenius": side-by-side with a mildly hapless rival.
- Car and drug ads: "Dramatization." and a wall of fine print at the end.
- The Jev launch itself: a side-by-side race against a chatbot.

The ChatGPT side is a dramatization; no chatbot was tested. The fine print says so. The
soundtrack is synthesized in ``media_audio`` (no samples) and muxed in by ``render_ad_video``.
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from . import media
from .media import AMBER, BG, FG, GREEN, MUTED, RED, ROOT, _text, font

GOLD = (255, 214, 92)
FINE = (120, 124, 132)
W, H = 1080, 1350
FPS = 30
BEAT = 0.5  # seconds; cuts land on a 120 bpm grid

# Scene order and length in beats. The soundtrack (media_audio) reads this too, so hits
# and cuts stay in sync. In-scene hits are placed on whole beats (see each scene).
TIMELINE: list[tuple[str, float]] = [
    ("poems", 2), ("trip", 2), ("great", 2), ("black", 1), ("trust", 6), ("versus", 9),
    ("meet", 4), ("hero", 11), ("numbers", 6), ("chart", 7), ("specs", 7), ("end", 10),
]


# ---------------------------------------------------------------------------
# Facts (all computed from recorded runs)
# ---------------------------------------------------------------------------

def facts(run: dict[str, Any], fake: dict[str, Any]) -> dict[str, Any]:
    cols = run["call_log"]["columns"]
    li, pi = cols.index("latency_ms"), cols.index("p_true")
    rows = run["call_log"]["rows"]
    c = run["counters"]
    return {
        "calls": c["jev_calls"],
        "wrong": c["local_errors"],
        "steps": len(run["rows"]) - 1,
        "cost": run["meta"]["cost_usd"],
        "median_ms": statistics.median(r[li] for r in rows),
        "min_conf": min(max(r[pi], 1 - r[pi]) for r in rows),
        "python_ms": media._python_ms(run),
        "minutes": media.RUN_200_MINUTES,
        "fake_cells_off": fake["counters"]["divergent_cells_final"],
        "fake_wrong": fake["counters"]["local_errors"],
        # live 64-step run, same start as the fake one (runs/rule110-ether-live.json)
        "live64_cells_off": media.load(ROOT / "runs" / "rule110-ether-live.json")["counters"]["divergent_cells_final"],
    }


def fine_print(run: dict[str, Any], python_ms: float, minutes: float, fx: dict[str, Any] | None = None) -> str:
    """The footnotes. One string so tests can check every disclaimer is present."""
    c = run["counters"]
    f = fx or {}
    return (
        "Not a real ad. Not sponsored by, affiliated with, or approved by TypeSafe AI or Vercel; the author paid for "
        "every call. ChatGPT scene is a dramatization: ChatGPT was not tested, and no chatbots were tested, harmed or "
        "compared. ChatGPT is a trademark of OpenAI; this has nothing to do with OpenAI either. "
        "1. Testing conducted by the author on 2026-10-09 using production typesafe-ai/jev via Vercel AI Gateway: "
        "{calls:,} live calls, {wrong} wrong, each checked against true Rule 110 by a separate program. Zero errors "
        "bounds the error rate (under about 1 in {bound:,} at 95% confidence); it does not measure it. "
        "2. Median time per call{med}; calls ran 6 at a time. "
        "3. Lowest confidence in any answer{conf}. Three-bit yes/no questions, the easiest kind there is. "
        "4. Wrong cells after 64 steps from the same start, versus a simulated gate that is wrong 0.1% of the time. "
        "The simulated gate is not an AI. "
        "Results hold only for the exact question wording in the repo; the model did not recognise \"Rule 110\" by "
        "name. 200 steps on 224 cells is a demonstration, not a universal computer. "
        "The run took {minutes:.0f} minutes and cost ${cost:.2f}. Plain Python does the same thing in {ms:.0f} "
        "milliseconds for free. Do not replace your CPU with an API."
    ).format(calls=c["jev_calls"], wrong=c["local_errors"], minutes=minutes, bound=error_bound_one_in(c["jev_calls"]), cost=run["meta"]["cost_usd"],
             ms=python_ms,
             med=": {:.0f} ms".format(f["median_ms"]) if f else "",
             conf=": {:.0f}%".format(f["min_conf"] * 100) if f else "")


def error_bound_one_in(n: int) -> int:
    """95% upper bound on the error rate after n calls with 0 errors, as '1 in N' (rounded down to 100)."""
    import math
    p = 1 - 0.05 ** (1 / n)  # exact; about 3/n ("rule of three")
    return int(math.floor(1 / p / 100) * 100)


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------

def ease_out(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return 1 - (1 - u) ** 3


def slam(img: Image.Image, text: str, y: int, size: int, colour, u: float, *, mono: bool = False,
         mark: str | None = None) -> None:
    """Text lands with a quick scale-down (1.25 -> 1.0) and fade-in; optional superscript footnote."""
    k = ease_out(u / 0.3) if u < 0.3 else 1.0
    s = int(size * (1.25 - 0.25 * k))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    a = int(255 * min(1.0, k * 1.4))
    f = font(s, True, mono)
    d.text((W // 2, y), text, font=f, fill=colour + (a,), anchor="mm")
    if mark and k > 0.6:
        w = d.textlength(text, font=f)
        d.text((W // 2 + w / 2 + 6, y - s * 0.62), mark, font=font(max(20, s // 3), True), fill=MUTED + (a,))
    img.paste(layer, (0, 0), layer)


def fine_block(d: ImageDraw.ImageDraw, text: str, x: int, y: int, chars: int, size: int) -> None:
    for i, line in enumerate(textwrap.wrap(text, chars)):
        d.text((x, y + i * int(size * 1.3)), line, font=font(size), fill=FINE)


# ---------------------------------------------------------------------------
# Scenes: (seconds, draw(img, u, t_local)) where u runs 0..1 across the scene
# ---------------------------------------------------------------------------

CHATBOT_REPLY = ("Great question! Cellular automata are a fascinating area of study. Whether this cell is on "
                 "depends on several factors, and it's important to consider the broader context. Let's break it "
                 "down step by step. First, what do we mean by \"on\"? In many traditions,")


def build_scenes(run: dict[str, Any], fx: dict[str, Any]) -> list[tuple[float, Callable]]:
    steps = fx["steps"]
    lo, hi = media._bounds(run)
    scale = max(1, min((W - 60) // (hi - lo), (H - 520) // len(run["rows"])))
    full = media.draw_spacetime(run, steps, scale)
    fp = fine_print(run, fx["python_ms"], fx["minutes"], fx)

    def words(seq, colour=FG, size=110):
        def draw(img, u, t):
            i = min(len(seq) - 1, int(u * len(seq)))
            slam(img, seq[i], H // 2, size, colour, u * len(seq) - i)
        return draw

    def black(img, u, t):
        pass

    def trust(img, u, t):
        d = ImageDraw.Draw(img)
        d.text((W // 2, 470), "But would you trust", font=font(74, True), fill=FG, anchor="mm")
        if u > 1 / 6:                     # beat 1 of 6
            slam(img, "YOUR", 615, 190, AMBER, (u - 1 / 6) * 4)
        if u > 3 / 6:                     # beat 3
            d.text((W // 2, 770), "AI to compute?", font=font(74, True), fill=FG, anchor="mm")

    def versus(img, u, t):
        d = ImageDraw.Draw(img)
        mid = W // 2
        d.rectangle([0, 0, mid - 3, H], fill=(20, 21, 26))
        d.text((mid // 2, 70), "ChatGPT", font=font(50, True), fill=MUTED, anchor="mm")
        d.text((mid + mid // 2, 70), "Jev", font=font(56, True), fill=GOLD, anchor="mm")
        d.rounded_rectangle([40, 140, mid - 40, 262], radius=18, fill=(46, 50, 60))
        d.multiline_text((62, 160), "L=on, C=off, R=on.\nIs the cell on next step?", font=font(28), fill=FG,
                         spacing=10)
        n = int(len(CHATBOT_REPLY) * min(1.0, u * 1.1))
        body = "\n".join(textwrap.wrap(CHATBOT_REPLY[:n], 25))
        d.rounded_rectangle([40, 290, mid - 40, 1040], radius=18, fill=(30, 32, 40))
        d.multiline_text((62, 312), body, font=font(30), fill=(200, 202, 208), spacing=12)
        d.text((62, 1070), "typing" + "." * (1 + int(t * 4) % 3), font=font(28), fill=MUTED)
        d.text((mid // 2, 1180), "cells decided: 0", font=font(34, True, mono=True), fill=RED, anchor="mm")
        # Jev side: a zoomed window on the real run (centre 60 cells, first rows), filling in fast
        tt = min(steps, max(1, int(110 * ease_out(u))))
        cx = (hi - lo) // 2
        sub = media.draw_spacetime(run, tt, 1).crop((cx - 30, 0, cx + 30, 110))
        z = (mid - 60) // sub.width
        sub = sub.resize((sub.width * z, sub.height * z), Image.NEAREST)
        img.paste(sub, (mid + 30, 140))
        d.text((mid + mid // 2, 1180), "cells decided: {:,}".format(media._calls_through(run, tt)),
               font=font(34, True, mono=True), fill=GREEN, anchor="mm")
        d.text((W - 24, H - 28), "Dramatization.", font=font(22), fill=MUTED, anchor="rs")

    def meet(img, u, t):
        d = ImageDraw.Draw(img)
        if u < 0.5:                       # "Jev" lands on beat 2 of 4
            slam(img, "Meet", H // 2 - 20, 130, FG, u / 0.5 * 2)
            return
        k = ease_out((u - 0.5) / 0.15)
        d.text((W // 2, H // 2 - 60), "Jev", font=font(int(300 * (1.3 - 0.3 * k)), True), fill=GOLD, anchor="mm")
        if u > 0.75:                      # beat 3
            d.text((W // 2, H // 2 + 140), "It doesn't chat. It decides.", font=font(56, True), fill=FG,
                   anchor="mm")

    def hero(img, u, t):
        d = ImageDraw.Draw(img)
        tt = min(steps, round(steps * ease_out(min(1.0, u * 1.08))))
        st = Image.new("RGB", full.size, BG)
        st.paste(full.crop((0, 0, full.width, (tt + 1) * scale)), (0, 0))
        img.paste(st, ((W - st.width) // 2, 230))
        d.text((W // 2, 70), "Every pixel: one AI decision.", font=font(56, True), fill=FG, anchor="mm")
        d.text((W // 2, 142), "Each one feeds the next.", font=font(40), fill=MUTED, anchor="mm")
        yb = 230 + full.height + 40
        d.text((60, yb), "DECISIONS", font=font(26, True), fill=MUTED)
        d.text((60, yb + 36), "{:,}".format(media._calls_through(run, tt)), font=font(70, True, mono=True), fill=FG)
        d.text((W - 60, yb), "MISTAKES", font=font(26, True), fill=MUTED, anchor="ra")
        d.text((W - 60, yb + 36), "0", font=font(70, True, mono=True), fill=GREEN, anchor="ra")

    def numbers(img, u, t):
        img.paste(Image.blend(full, Image.new("RGB", full.size, BG), 0.82), ((W - full.width) // 2, 230))
        lines = [("{:,} decisions.".format(fx["calls"]), FG, 0.0, 96, None),   # beats 0, 2, 4 of 6
                 ("In a row.", FG, 1 / 3, 96, None),
                 ("Zero mistakes.", GREEN, 2 / 3, 112, "1")]
        for i, (s, col, start, size, mark) in enumerate(lines):
            if u >= start:
                slam(img, s, 480 + i * 170, size, col, (u - start) / 0.4 * 2.2, mark=mark)

    def chart(img, u, t):
        d = ImageDraw.Draw(img)
        slam(img, "Relative mistakes", 130, 72, FG, 1.0, mark="4")
        base_y, top_y = 1040, 330
        k = ease_out(u / 0.55)
        bars = [("A gate that's wrong\n0.1% of the time", fx["fake_cells_off"], (95, 97, 106)),
                ("Jev", fx["live64_cells_off"], GOLD)]
        mx = max(b[1] for b in bars) or 1
        for i, (lab, val, col) in enumerate(bars):
            x0 = 210 + i * 400
            hgt = (base_y - top_y) * (val / mx) * k
            if val == 0:
                d.rectangle([x0, base_y - 8, x0 + 260, base_y], fill=col)
            else:
                d.rounded_rectangle([x0, int(base_y - hgt), x0 + 260, base_y], radius=14, fill=col)
            d.text((x0 + 130, base_y - hgt - 56), str(round(val * k)), font=font(72, True, mono=True),
                   fill=GOLD if val == 0 else FG, anchor="mm")
            d.multiline_text((x0 + 130, base_y + 80), lab, font=font(36, True), fill=GOLD if val == 0 else MUTED,
                             anchor="mm", align="center", spacing=6)

    def specs(img, u, t):
        items = [("{:.2f} s".format(fx["median_ms"] / 1000), "per decision", "2", GOLD),
                 ("{:.0f}%+".format(fx["min_conf"] * 100), "sure. Every time.", "3", GOLD),
                 ("0", "mistakes", "1", GREEN)]
        d = ImageDraw.Draw(img)
        for i, (big, small, mark, col) in enumerate(items):
            start = i * 2 / 7             # beats 0, 2, 4 of 7
            if u >= start:
                uu = (u - start) / 0.27 * 1.2
                y = 320 + i * 320
                slam(img, big, y, 160, col, uu, mark=mark)
                if uu > 0.3:
                    d.text((W // 2, y + 112), small, font=font(44), fill=MUTED, anchor="mm")

    def endcard(img, u, t):
        d = ImageDraw.Draw(img)
        d.text((W // 2, 400), "Jev", font=font(240, True), fill=GOLD, anchor="mm")
        d.text((W // 2, 590), "It doesn't chat. It decides.", font=font(60, True), fill=FG, anchor="mm")
        if u > 0.15:
            d.text((W // 2, 700), "Would you trust YOUR AI to compute?", font=font(40), fill=MUTED, anchor="mm")
        if u > 0.25:
            fine_block(d, fp, 40, H - 262, 120, 16)

    draws = {
        "poems": words(["Chatbots", "write poems."]),
        "trip": words(["They plan", "your trip."]),
        "great": words(["They say", "\"Great question!\""], size=96),
        "black": black, "trust": trust, "versus": versus, "meet": meet, "hero": hero,
        "numbers": numbers, "chart": chart, "specs": specs, "end": endcard,
    }
    return [(beats * BEAT, draws[name]) for name, beats in TIMELINE]


def ad_frames(run: dict[str, Any], tmp: Path, *, fps: int = FPS) -> int:
    fx = facts(run, media.load(ROOT / "runs" / "rule110-ether-p0.001-seed2.json"))
    n = 0
    for dur, draw in build_scenes(run, fx):
        frames = int(round(dur * fps))
        for f in range(frames):
            img = Image.new("RGB", (W, H), BG)
            draw(img, (f + 1) / frames, f / fps)
            img.save(tmp / "f{:05d}.png".format(n))
            n += 1
    return n


def _loudness_gain(ffmpeg: str, wav: Path, target_lufs: float, max_true_peak: float) -> float:
    """One static gain toward a social-video loudness target (keeps the dynamics; a limiter catches peaks)."""
    import json as _json
    import re

    p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(wav), "-af", "loudnorm=print_format=json", "-f", "null",
                        "-"], capture_output=True, text=True)
    stats = _json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr).group(0))
    return target_lufs - float(stats["input_i"])


def render_ad_video(run: dict[str, Any], out: Path, fps: int = FPS, audio: bool = True) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        n = ad_frames(run, tmp, fps=fps)
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%05d.png")]
        if audio:
            from . import media_audio
            wav = tmp / "soundtrack.wav"  # intermediate only; keeps site/media free of a 6 MB wav
            media_audio.write_wav(media_audio.build_track(TIMELINE), wav)
            gain = _loudness_gain(ffmpeg, wav, target_lufs=-14.0, max_true_peak=-1.0)
            cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-af", "volume={:.2f}dB,alimiter=limit=0.89:level=false".format(gain), "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
        shutil.copy(tmp / "f{:05d}.png".format(n - 1), out.with_name(out.stem + "-poster.png"))


def ad_print(run: dict[str, Any], out: Path) -> None:
    """Magazine-style still: headline, the run, brand line, a wall of tiny footnotes."""
    fx = facts(run, media.load(ROOT / "runs" / "rule110-ether-p0.001-seed2.json"))
    PW, PH = 1200, 1500
    img = Image.new("RGB", (PW, PH), BG)
    d = ImageDraw.Draw(img)
    _text(d, (PW // 2, 60), "Would you trust", font(80, True), FG, anchor="ma")
    _text(d, (PW // 2, 160), "YOUR AI to compute?", font(80, True), AMBER, anchor="ma")
    lo, hi = media._bounds(run)
    scale = max(1, min((PW - 120) // (hi - lo), 620 // len(run["rows"])))
    st = media.draw_spacetime(run, len(run["rows"]), scale)
    img.paste(st, ((PW - st.width) // 2, 290))
    y = 290 + st.height + 30
    s = "{:,} AI decisions in a row. Zero mistakes.".format(fx["calls"])
    _text(d, (PW // 2, y), s, font(42, True), GREEN, anchor="ma")
    d.text((PW / 2 + d.textlength(s, font=font(42, True)) / 2 + 4, y - 4), "1", font=font(22, True), fill=MUTED)
    _text(d, (PW // 2, y + 80), "Jev", font(110, True), GOLD, anchor="ma")
    _text(d, (PW // 2, y + 210), "It doesn't chat. It decides.", font(40, True), FG, anchor="ma")
    fine_block(d, fine_print(run, fx["python_ms"], fx["minutes"], fx), 50, PH - 215, 140, 14)
    img.save(out)


def write_site_facts(run: dict[str, Any], out: Path) -> dict[str, Any]:
    """Write site/data/ad-facts.js so the web page quotes the same numbers and fine print as the ad."""
    import json

    fx = facts(run, media.load(ROOT / "runs" / "rule110-ether-p0.001-seed2.json"))
    fx = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fx.items()}
    fx["fine_print"] = fine_print(run, fx["python_ms"], fx["minutes"], fx)
    fx["bound_one_in"] = error_bound_one_in(fx["calls"])
    # Display strings formatted by Python, so the page shows exactly what the ad shows
    # (JS Math.round(22.5) = 23, Python's "{:.0f}" gives 22).
    fx["text"] = {"minutes": "{:.0f}".format(fx["minutes"]), "python_ms": "{:.0f}".format(fx["python_ms"]),
                  "cost": "{:.2f}".format(fx["cost"]), "median_s": "{:.2f}".format(fx["median_ms"] / 1000),
                  "median_ms": "{:.0f}".format(fx["median_ms"]), "min_conf_pct": "{:.0f}".format(fx["min_conf"] * 100),
                  "bound_one_in": "{:,}".format(fx["bound_one_in"]), "calls": "{:,}".format(fx["calls"])}
    out.write_text("// Generated by python -m jev_turing.media_ad. Same numbers as the ad video.\n"
                   "window.JEV_AD_FACTS = " + json.dumps(fx, indent=1) + ";\n")
    return fx


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m jev_turing.media_ad", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(ROOT / "site" / "media"))
    p.add_argument("--skip-video", action="store_true")
    p.add_argument("--no-audio", action="store_true", help="silent video (no numpy needed)")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    run = media.load_live_site_run()
    facts_js = ROOT / "site" / "data" / "ad-facts.js"
    write_site_facts(run, facts_js)
    print("wrote", facts_js)
    ad_print(run, out / "ad-print.png")
    print("wrote", out / "ad-print.png")
    if not a.skip_video:
        render_ad_video(run, out / "ad-jev.mp4", audio=not a.no_audio)
        print("wrote", out / "ad-jev.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
