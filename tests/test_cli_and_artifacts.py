import json
from pathlib import Path

from jev_turing.cli import main

ROOT = Path(__file__).resolve().parents[1]
RECORDED = ROOT / "runs" / "rule110-ether-p0.001-seed2.json"


def test_cli_gates_latch_rule110(tmp_path, capsys):
    assert main(["gates", "--gate", "NAND", "--n", "50", "--vote", "all"]) == 0
    assert main(["latch", "--hold-cycles", "3", "--trials", "20", "--error-rate", "0.01"]) == 0
    assert main(["rule110", "--steps", "10", "--out", str(tmp_path / "run")]) == 0
    assert (tmp_path / "run.json").exists() and (tmp_path / "run.png").exists()
    assert "NOT JEV results" in capsys.readouterr().out


def test_cli_jev_backend_refuses():
    assert main(["gates", "--backend", "jev", "--n", "1"]) == 2


def test_recorded_run_is_fake_and_consistent():
    run = json.loads(RECORDED.read_text())
    assert run["backend"].startswith("fake-jev")
    assert "NOT a JEV result" in run["disclaimer"]
    c = run["counters"]
    errs = sum(r[run["call_log"]["columns"].index("error")] for r in run["call_log"]["rows"])
    assert errs == c["local_errors"]


def test_site_data_matches_recorded_run_and_live_disabled():
    js = (ROOT / "site" / "data" / "recorded-run.js").read_text()
    payload = js.split("window.JEV_RECORDED_RUN = ", 1)[1].rstrip().rstrip(";")
    assert json.loads(payload) == json.loads(RECORDED.read_text())
    html = (ROOT / "site" / "index.html").read_text()
    assert "live-run.js" in html and "no network calls" in html
    assert "fetch(" not in (ROOT / "site" / "app.js").read_text()


def test_attach_live_ledger_lines_up_and_rejects_mismatch(tmp_path):
    from jev_turing.cli import attach_live_ledger
    from jev_turing.backend import FakeJEV
    from jev_turing.rule110 import JevRule110
    run = JevRule110(FakeJEV(0.0), init="1", background="zero", pad=2).run(3).to_dict()
    cols = run["call_log"]["columns"]
    lines = []
    for i, row in enumerate(run["call_log"]["rows"]):
        L, C, R, out = (bool(row[cols.index(k)]) for k in ("L", "C", "R", "out"))
        lines.append({"call": i + 1, "inputs": {"L": L, "C": C, "R": R}, "choice": "true" if out else "false",
                      "p_true": 0.97 if out else 0.07, "cost_usd": 1e-5, "provider": "typesafe-ai"})
    p = tmp_path / "l.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines))
    merged = attach_live_ledger(json.loads(json.dumps(run)), p)
    assert merged["call_log"]["columns"][-1] == "p_true" and merged["meta"]["hosts"] == ["typesafe-ai"]
    lines[0]["choice"] = "false" if lines[0]["choice"] == "true" else "true"
    p.write_text("\n".join(json.dumps(x) for x in lines))
    import pytest
    with pytest.raises(ValueError):
        attach_live_ledger(json.loads(json.dumps(run)), p)


def test_no_workflows_or_pages():
    assert not (ROOT / ".github").exists()
