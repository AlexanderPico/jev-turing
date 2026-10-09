"""Review regressions: honest presentation and usable boundary inputs."""
from html.parser import HTMLParser
from pathlib import Path

import pytest

from jev_turing.cli import main


@pytest.mark.parametrize("args", [
    ["gates", "--n", "0"],
    ["gates", "--n", "-1"],
    ["latch", "--hold-cycles", "-1"],
    ["latch", "--trials", "-1"],
    ["rule110", "--steps", "-1"],
    ["rule110", "--pad", "-1"],
    ["rule110", "--scale", "0"],
    ["gates", "--error-rate", "nan"],
    ["gates", "--error-rate", "1.1"],
])
def test_invalid_cli_counts_are_usage_errors(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("extra", [["--hold-cycles", "0"], ["--error-rate", "1", "--trials", "1"]])
def test_latch_unavailable_rates_do_not_crash(extra, capsys):
    assert main(["latch", "--trials", "2", *extra]) == 0
    assert "n/a" in capsys.readouterr().out


class Headings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "h1"):
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag in ("title", "h1"):
            self.in_heading = False

    def handle_data(self, data):
        if self.in_heading:
            self.text.append(data)


def test_site_discloses_before_scripts_load():
    """The static HTML alone (no JS) must say it's not a real ad, disclose independence,
    label the simulated run as not an AI, and carry the limits; headings must not overclaim."""
    html = (Path(__file__).resolve().parents[1] / "site/index.html").read_text()
    parser = Headings()
    parser.feed(html)
    heads = " ".join(parser.text).lower()
    assert "fine print" in heads
    for banned in ("turing-complete", "turing complete", "first ", "universal computer"):
        assert banned not in heads
    for must in ("Not a real ad. Not sponsored.", "no affiliation", "TypeSafe AI", "Vercel", "OpenAI",
                 "(not an AI)",
                 "Plain code is far better at this", "Zero errors is a bound, not a measurement",
                 "dramatization", "no network calls"):
        assert must in html, must
