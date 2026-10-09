"""Soundtrack: in sync with the video timeline, silent before the reveal, no clipping."""
import numpy as np
import pytest

np = pytest.importorskip("numpy")

from jev_turing import media_audio as ma  # noqa: E402
from jev_turing.media_ad import BEAT, TIMELINE  # noqa: E402


def test_track_matches_timeline_and_has_reveal_gap():
    assert ma.BEAT == BEAT
    x = ma.build_track(TIMELINE)
    total = sum(b for _, b in TIMELINE) * BEAT
    assert abs(len(x) / ma.SR - total) < 0.25
    assert np.max(np.abs(x)) <= 0.9  # peak-normalised to about -1 dBFS
    starts, t = {}, 0
    for name, beats in TIMELINE:
        starts[name] = t
        t += beats
    i0, i1 = (ma.n_of((starts["meet"] + o) * BEAT) for o in (0.7, 1.95))
    assert np.max(np.abs(x[i0:i1])) < 1e-3  # dead air before "Jev"
    j = ma.n_of((starts["meet"] + 2) * BEAT)
    assert np.max(np.abs(x[j:j + ma.n_of(0.1)])) > 0.3  # and then the hit
