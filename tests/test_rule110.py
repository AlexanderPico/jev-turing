import json
import random

import pytest

from jev_turing import rule110
from jev_turing.backend import FakeJEV
from jev_turing.rule110 import BACKGROUNDS, RULE110_SPEC, JevRule110, reference_rule110, write_json, write_png


def test_spec_table_agrees_with_reference():
    for key, val in RULE110_SPEC["rule"].items():
        assert val == reference_rule110(*(c == "1" for c in key))


def _big_ring(init, bg, steps, n=14 * 40, base=14 * 20):
    s = [bg[x % len(bg)] == "1" for x in range(-base, n - base)]
    for i, c in enumerate(init):
        s[base + i] = c == "1"
    out = [s]
    for _ in range(steps):
        s = [reference_rule110(s[i - 1], s[i], s[(i + 1) % len(s)]) for i in range(len(s))]
        out.append(s)
    return out, base


@pytest.mark.parametrize("background", ["zero", "ether"])
def test_growing_tape_matches_independent_big_ring(background):
    rng = random.Random(background)
    for _ in range(3):
        init = "".join(rng.choice("01") for _ in range(rng.randint(1, 16)))
        sim = JevRule110(FakeJEV(0.0), init=init, background=background).run(60)
        ref, base = _big_ring(init, BACKGROUNDS[background], 60)
        for row in sim.rows:
            for x in range(row["lo"] - 20, row["lo"] + len(row["cells"]) + 20):
                v, _ = rule110._cell_at(row, x)
                assert v == ref[row["t"]][x + base]
        assert sim.counters()["local_errors"] == 0


def test_one_call_per_cell_update_and_tape_grows():
    sim = JevRule110(FakeJEV(0.0), init="1", background="zero").run(30)
    widths = sum(len(r["cells"]) for r in sim.rows[1:])
    c = sim.counters()
    assert c["tape_calls"] == widths and c["background_calls"] == 30
    assert sim.backend.call_count == c["jev_calls"]
    assert c["final_width"] > 25  # grew leftward from a single cell


def test_engine_never_uses_reference(monkeypatch):
    def forbidden(*a):
        raise AssertionError("engine called the checking-only reference rule")
    monkeypatch.setattr(rule110, "reference_rule110", forbidden)
    sim = JevRule110(FakeJEV(0.0), init="1011", background="ether", check=False).run(20)
    assert sim.tape.t == 20


def test_error_counter_counts_flips():
    sim = JevRule110(FakeJEV(0.01, seed=5), init="1", background="ether").run(40)
    c = sim.counters()
    assert c["local_errors"] == c["fake_flips"] == sim.backend.flip_count > 0


def test_glue_vote_reduces_errors():
    plain = JevRule110(FakeJEV(0.02, seed=9), init="1", background="ether").run(40).counters()
    voted = JevRule110(FakeJEV(0.02, seed=9), init="1", background="ether", vote="glue").run(40).counters()
    assert voted["local_errors"] < plain["local_errors"]


def test_json_and_png_output(tmp_path):
    sim = JevRule110(FakeJEV(0.01, seed=1), init="1", background="ether").run(20)
    d = sim.to_dict()
    assert "NOT a JEV result" in d["disclaimer"]
    j = write_json(d, tmp_path / "r.json")
    loaded = json.loads(j.read_text())
    assert loaded["call_log"]["columns"][0] == "t"
    assert len(loaded["call_log"]["rows"]) == d["counters"]["cell_updates"]
    p = write_png(d, tmp_path / "r.png")
    assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
