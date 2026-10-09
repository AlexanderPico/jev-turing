"""Media renderer smoke test: stills render from recorded runs (video skipped; no ffmpeg needed)."""
from pathlib import Path

import pytest

from jev_turing import media


@pytest.mark.skipif(not (media.PROJECT_RUNS / "live-nand-4000-20261009" / "summary.json").exists(),
                    reason="project-record live runs not present")
def test_stills_render(tmp_path):
    assert media.main(["--out", str(tmp_path), "--skip-video"]) == 0
    for name in ("real-vs-fake.png", "nand-table.png", "how-it-works.png"):
        p = Path(tmp_path) / name
        assert p.exists() and p.stat().st_size > 10_000


def test_spacetime_marks_divergence():
    run = media.load(media.ROOT / "runs" / "rule110-ether-p0.001-seed2.json")
    img = media.draw_spacetime(run, len(run["rows"]), 1)
    colours = {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}
    assert media.RED in colours or media.DIVERGED_OFF in colours  # the fake run has drift
    live = media.load(media.ROOT / "runs" / "rule110-ether-200-live.json")
    img = media.draw_spacetime(live, len(live["rows"]), 1)
    colours = {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}
    assert not colours & {media.RED, media.DIVERGED_OFF, media.AMBER}  # the live run has none
