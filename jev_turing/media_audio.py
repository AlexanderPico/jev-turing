"""Synthesized soundtrack for the parody ad. No samples, no downloads, no licences needed.

    python -m jev_turing.media_audio --out site/media/ad-jev.wav

Every sound is generated here from sine waves and noise, so the track is ours to use.
The cue sheet is derived from ``media_ad.TIMELINE`` (scene lengths in beats at 120 bpm),
so hits land on the same frames as the visual slams.

Style target: tech-launch spot. Tight kick/clap groove, sub bass, a four-chord pad
(Bm-G-D-A), risers into reveals, a hard cut to silence before "Meet ... Jev", impacts on
every number slam, and a bell sting on the end card.
"""
from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np

SR = 48_000
BPM = 120
BEAT = 60 / BPM
RNG = np.random.default_rng(110)


def n_of(sec: float) -> int:
    return int(round(sec * SR))


def tvec(sec: float) -> np.ndarray:
    return np.arange(n_of(sec)) / SR


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------------------------------------------------------------------------
# Filters (zero-phase, FFT; fine offline)
# ---------------------------------------------------------------------------

def filt(x: np.ndarray, lo: float | None = None, hi: float | None = None, order: int = 2) -> np.ndarray:
    if len(x) < 8:
        return x
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.ones_like(f)
    if hi is not None:
        g *= 1 / np.sqrt(1 + (f / hi) ** (2 * order))
    if lo is not None:
        with np.errstate(divide="ignore"):
            g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-6)) ** (2 * order))
    return np.fft.irfft(X * g, n=len(x))


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

def decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (tau * SR))


def kick(tau: float = 0.16) -> np.ndarray:
    t = tvec(0.5)
    f = 46 + 120 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * decay(len(t), tau)
    click = filt(RNG.normal(size=len(t)), lo=1500) * decay(len(t), 0.003) * 0.4
    return np.tanh(1.8 * (body + click))


def clap() -> np.ndarray:
    n = n_of(0.3)
    noise = filt(RNG.normal(size=n), lo=900, hi=7000)
    env = np.zeros(n)
    for off in (0.0, 0.011, 0.022):  # three quick bursts, like a real clap
        i = n_of(off)
        env[i:] += decay(n - i, 0.006)
    env += decay(n, 0.09) * 0.6
    return noise * env * 0.35


def hat(open_: bool = False) -> np.ndarray:
    n = n_of(0.18 if open_ else 0.05)
    return filt(RNG.normal(size=n), lo=7000) * decay(n, 0.05 if open_ else 0.012) * 0.25


def saw(freq: float, sec: float, harmonics: int = 10, detune: float = 0.0) -> np.ndarray:
    t = tvec(sec)
    f = freq * (1 + detune)
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        if f * k > SR / 2.2:
            break
        out += np.sin(2 * np.pi * f * k * t + k) / k
    return out


def note_env(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n)
    a, r = min(n, n_of(attack)), min(n, n_of(release))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def bass(midi: int, sec: float) -> np.ndarray:
    s = saw(hz(midi), sec, 14) + 0.6 * np.sin(2 * np.pi * hz(midi) * tvec(sec))
    s = filt(s, hi=700) * note_env(len(s), 0.004, 0.03) * (0.55 + 0.45 * decay(len(s), 0.12))
    return np.tanh(1.4 * s) * 0.5


def pad(chord: list[int], sec: float, bright: float = 2400) -> np.ndarray:
    out = np.zeros(n_of(sec))
    for m in chord:
        for d in (-0.004, 0.0, 0.005):
            out += saw(hz(m), sec, 9, d)
    out = filt(out, hi=bright) * note_env(len(out), 0.25, 0.35)
    return out / (len(chord) * 3) * 0.6


def pluck(midi: int, sec: float = 0.22) -> np.ndarray:
    s = saw(hz(midi), sec, 12)
    return filt(s, hi=3200) * decay(len(s), 0.09) * note_env(len(s), 0.002, 0.02) * 0.35


def impact(size: float = 1.0) -> np.ndarray:
    t = tvec(1.6)
    sub = np.sin(2 * np.pi * np.cumsum(55 * np.exp(-t / 0.5) + 32) / SR) * decay(len(t), 0.45 * size)
    noise = filt(RNG.normal(size=len(t)), hi=2500) * decay(len(t), 0.18 * size) * 0.5
    k = np.zeros_like(t)
    kk = kick(0.22)
    k[: len(kk)] = kk
    return np.tanh(1.3 * (0.9 * sub + noise + 0.8 * k)) * size


def tick() -> np.ndarray:
    n = n_of(0.06)
    return filt(RNG.normal(size=n), lo=2500, hi=9000) * decay(n, 0.01) * 0.6


def riser(sec: float) -> np.ndarray:
    t = tvec(sec)
    u = t / sec
    noise = filt(RNG.normal(size=len(t)), lo=400, hi=9000) * u ** 2.2 * 0.45
    f = 180 * (12 ** u)  # 180 Hz -> ~2.2 kHz
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * u ** 2 * 0.25
    return noise + tone


def reverse_swell(sec: float) -> np.ndarray:
    return impact(0.8)[: n_of(sec)][::-1] * np.linspace(0, 1, n_of(sec)) ** 1.5 * 0.6


def typing_click() -> np.ndarray:
    n = n_of(0.03)
    return filt(RNG.normal(size=n), lo=1800, hi=6000) * decay(n, 0.004) * 0.5


def blip(midi: int) -> np.ndarray:
    t = tvec(0.07)
    return np.sin(2 * np.pi * hz(midi) * t) * decay(len(t), 0.02) * 0.18


def bell(midi: int, sec: float = 3.0) -> np.ndarray:
    t = tvec(sec)
    f0 = hz(midi)
    out = np.zeros_like(t)
    for ratio, amp, tau in ((1, 1, 1.4), (2.0, 0.5, 0.9), (3.0, 0.25, 0.5), (4.16, 0.2, 0.3), (5.43, 0.12, 0.2)):
        out += amp * np.sin(2 * np.pi * f0 * ratio * t) * decay(len(t), tau)
    return out * note_env(len(t), 0.003, 0.05) * 0.22


# ---------------------------------------------------------------------------
# Mixer
# ---------------------------------------------------------------------------

class Mix:
    def __init__(self, seconds: float):
        self.n = n_of(seconds)
        self.dry = np.zeros((self.n, 2))
        self.wet = np.zeros((self.n, 2))

    def add(self, sig: np.ndarray, at_beat: float, gain: float = 1.0, pan: float = 0.0, send: float = 0.0) -> None:
        i = n_of(at_beat * BEAT)
        if i >= self.n:
            return
        seg = sig[: self.n - i] * gain
        ang = (pan + 1) * np.pi / 4
        for ch, w in ((0, np.cos(ang)), (1, np.sin(ang))):
            self.dry[i: i + len(seg), ch] += seg * w * np.sqrt(2)
            if send:
                self.wet[i: i + len(seg), ch] += seg * w * np.sqrt(2) * send

    def render(self, normalize: bool = True) -> np.ndarray:
        ir_n = n_of(1.8)
        out = self.dry.copy()
        for ch in range(2):
            ir = filt(RNG.normal(size=ir_n), hi=5000) * decay(ir_n, 0.45)
            ir /= np.sqrt(np.sum(ir ** 2))
            size = 1 << int(np.ceil(np.log2(self.n + ir_n)))
            rev = np.fft.irfft(np.fft.rfft(self.wet[:, ch], size) * np.fft.rfft(ir, size), size)[: self.n]
            out[:, ch] += rev * 0.5
        out = np.stack([filt(out[:, c], lo=28) for c in range(2)], axis=1)
        return normalize_peak(out) if normalize else out


def normalize_peak(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    peak = np.max(np.abs(x)) or 1.0
    return x / peak * 10 ** (peak_db / 20)


def gate(x: np.ndarray, start_beat: float, end_beat: float, fade: float = 0.02) -> np.ndarray:
    """Silence x between two beats (short fades), e.g. the hard cut before a reveal."""
    g = np.ones(len(x))
    i0, i1, f = n_of(start_beat * BEAT), n_of(end_beat * BEAT), n_of(fade)
    g[i0:i1] = 0
    g[max(0, i0 - f):i0] = np.linspace(1, 0, min(f, i0))
    g[i1:i1 + f] = np.linspace(0, 1, len(g[i1:i1 + f]))
    return x * g[:, None]


# ---------------------------------------------------------------------------
# Arrangement
# ---------------------------------------------------------------------------

PROG = [  # (bass midi, pad voicing) Bm - G - D - A
    (35, [59, 62, 66]),
    (31, [59, 62, 67]),
    (38, [57, 62, 66]),
    (33, [57, 61, 64]),
]
D_MAJOR = (38, [62, 66, 69, 74])


def groove(m: Mix, start: float, beats: float, *, full: bool = True, arp: bool = False, fill_last: bool = False,
           pad_gain: float = 0.5) -> None:
    """Four-on-the-floor section starting at beat ``start``; chords change every 4 beats."""
    end = start + beats
    b = start
    bar = 0
    while b < end - 1e-9:
        root, chord = PROG[bar % 4]
        bar_len = min(4, end - b)
        m.add(pad(chord, bar_len * BEAT + 0.3), b, pad_gain, send=0.25)
        for q in range(int(bar_len * 2)):  # eighth notes
            beat = b + q / 2
            last_beat = fill_last and beat >= end - 1
            if q % 2 == 0:
                m.add(kick(), beat, 0.8)
                if full and (q // 2) % 2 == 1 and not last_beat:
                    m.add(clap(), beat, 0.9, send=0.2)
            else:
                m.add(hat(open_=(q % 4 == 3)), beat, 0.9 if full else 0.6, pan=0.25)
            if full:
                m.add(hat(), beat + 0.25, 0.35, pan=-0.2)
            m.add(bass(root + (12 if q % 4 == 3 else 0), BEAT / 2 * 0.92), beat, 0.7)
            if last_beat:
                m.add(clap(), beat, 0.7)
                m.add(clap(), beat + 0.25, 0.8)
        if arp:
            tones = sorted(chord) + [chord[0] + 12]
            for s16 in range(int(bar_len * 4)):
                m.add(pluck(tones[s16 % len(tones)] + 12), b + s16 / 4, 0.55, pan=0.3 if s16 % 2 else -0.3,
                      send=0.15)
        b += 4
        bar += 1


def build_track(timeline: list[tuple[str, float]]) -> np.ndarray:
    starts: dict[str, float] = {}
    t = 0.0
    for name, beats in timeline:
        starts[name] = t
        t += beats
    total_beats = t
    m = Mix(total_beats * BEAT + 0.2)
    S = starts

    # Intro: one hit per word, quiet pad underneath, then a hard stop.
    for i, (name, chord) in enumerate((("poems", PROG[0][1]), ("trip", PROG[1][1]), ("great", PROG[2][1]))):
        m.add(pad(chord, 2 * BEAT + 0.2, 1600), S[name], 0.35, send=0.3)
        m.add(kick(0.2), S[name], 0.8)
        m.add(tick(), S[name], 0.5)
        m.add(kick(0.25), S[name] + 1, 0.9)
        m.add(clap(), S[name] + 1, 0.6, send=0.3)
    m.add(reverse_swell(BEAT), S["black"], 0.9)

    # "But would you trust YOUR AI to compute?"
    m.add(kick(0.2), S["trust"], 0.7)
    m.add(np.sin(2 * np.pi * hz(35) * tvec(6 * BEAT)) * note_env(n_of(6 * BEAT), 0.3, 0.2) * 0.35, S["trust"])
    m.add(impact(1.0), S["trust"] + 1, 1.0, send=0.4)          # YOUR
    m.add(kick(0.2), S["trust"] + 3, 0.8)                       # AI to compute?
    m.add(clap(), S["trust"] + 3, 0.6, send=0.3)
    m.add(riser(2 * BEAT), S["trust"] + 4, 0.8)

    # Split screen: groove, ChatGPT typing on the left, Jev blips on the right.
    groove(m, S["versus"], 9, fill_last=True)
    m.add(impact(0.8), S["versus"], 0.8, send=0.3)
    beat = S["versus"]
    while beat < S["versus"] + 8.5:
        m.add(typing_click(), beat, 0.55, pan=-0.7)
        beat += RNG.uniform(0.09, 0.3)
    penta = [74, 76, 78, 81, 83, 86]
    for s16 in range(int(8.5 * 4)):
        m.add(blip(penta[RNG.integers(len(penta))]), S["versus"] + s16 / 4, 1.0, pan=0.7)

    # Hard cut. "Meet" ... near-silence ... "Jev". On its own layer so the main mix
    # (and its reverb tail) can be gated to true silence underneath.
    mt = Mix(total_beats * BEAT + 0.2)
    mt.add(kick(0.18), S["meet"], 0.8)
    mt.add(tick(), S["meet"], 0.5)
    mt.add(impact(1.4), S["meet"] + 2, 1.2, send=0.5)
    mt.add(pad(D_MAJOR[1], 2 * BEAT + 0.4, 3500), S["meet"] + 2, 0.7, send=0.4)
    mt.add(bell(74), S["meet"] + 2, 0.9, send=0.5)
    mt.add(kick(0.2), S["meet"] + 3, 0.6)                       # It doesn't chat. It decides.

    # Hero run: full groove plus arpeggio, riser into the numbers.
    groove(m, S["hero"], 11, arp=True, pad_gain=0.55)
    m.add(riser(3 * BEAT), S["hero"] + 8, 0.9)

    # Number slams on beats 0, 2, 4 of the scene; kick-only bed underneath.
    for i in range(3):
        m.add(impact(0.9 + 0.2 * i), S["numbers"] + 2 * i, 0.9 + 0.1 * i, send=0.35)
    for q in range(6):
        if q % 2:
            m.add(kick(), S["numbers"] + q, 0.7)
    m.add(pad(D_MAJOR[1], 2 * BEAT + 0.3, 3200), S["numbers"] + 4, 0.55, send=0.4)

    # Chart: light groove, a rising tone while the bars grow, a ding on Jev's zero.
    groove(m, S["chart"], 7, full=False, pad_gain=0.4)
    m.add(riser(3.8 * BEAT) * 0.6, S["chart"], 0.7)
    m.add(bell(81, 1.5), S["chart"] + 4, 0.7, send=0.3)

    # Spec slams on beats 0, 2, 4.
    groove(m, S["specs"], 7, pad_gain=0.45)
    for i in range(3):
        m.add(impact(0.8), S["specs"] + 2 * i, 0.75, send=0.3)
        m.add(tick(), S["specs"] + 2 * i, 0.6)
    m.add(riser(BEAT), S["specs"] + 6, 0.7)

    # End card: big hit, D major chord rings out, bell sting.
    e = S["end"]
    m.add(impact(1.3), e, 1.1, send=0.5)
    m.add(pad(D_MAJOR[1], (total_beats - e) * BEAT, 3000) * np.linspace(1, 0, n_of((total_beats - e) * BEAT)) ** 0.7,
          e, 0.8, send=0.5)
    m.add(bass(D_MAJOR[0], 2.0) * decay(n_of(2.0), 0.9), e, 0.9)
    m.add(bell(74, 4.0), e + 0.5, 0.9, send=0.5)
    m.add(bell(81, 4.0), e + 1.0, 0.8, send=0.5)
    main = gate(m.render(normalize=False), S["meet"], S["meet"] + 2)
    # leave the "Meet" kick audible, then nothing until the "Jev" hit
    meet = gate(mt.render(normalize=False), S["meet"] + 0.6, S["meet"] + 2 - 0.02)
    return normalize_peak(main + meet)


def write_wav(x: np.ndarray, path: Path) -> None:
    data = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def main(argv: list[str] | None = None) -> int:
    from .media_ad import TIMELINE

    p = argparse.ArgumentParser(prog="python -m jev_turing.media_audio", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    write_wav(build_track(TIMELINE), Path(a.out))
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
