"""Parody-ad fine print must carry the real numbers and the disclaimers."""
from jev_turing import media, media_ad


def test_fine_print_has_disclaimers_and_real_numbers():
    run = media.load_live_site_run()
    fp = media_ad.fine_print(run, 4.0, media.RUN_200_MINUTES)
    for must in ("Not a real ad", "Not sponsored by", "TypeSafe AI", "Vercel", "26,340", "0 wrong",
                 "does not measure it", "no chatbots were tested", "dramatization", "ChatGPT was not tested",
                 "trademark of OpenAI", "$0.43", "4 milliseconds",
                 "not a universal computer"):
        assert must in fp, must


def test_print_ad_renders(tmp_path):
    media_ad.ad_print(media.load_live_site_run(), tmp_path / "ad.png")
    assert (tmp_path / "ad.png").stat().st_size > 20_000


def test_error_bound_rule_of_three():
    assert media_ad.error_bound_one_in(26340) == 8700   # ~ n/3, rounded down to 100
    assert media_ad.error_bound_one_in(4000) == 1300


def test_site_facts_match_the_ad(tmp_path):
    """The web page reads these; they must be the ad's own numbers, formatted the ad's way."""
    import json
    run = media.load_live_site_run()
    out = tmp_path / "ad-facts.js"
    fx = media_ad.write_site_facts(run, out)
    loaded = json.loads(out.read_text().split("window.JEV_AD_FACTS = ", 1)[1].rstrip().rstrip(";"))
    assert loaded["fine_print"] == media_ad.fine_print(run, fx["python_ms"], fx["minutes"], fx)
    assert loaded["text"]["calls"] == "26,340" and loaded["text"]["cost"] == "0.43"
    assert loaded["text"]["minutes"] in loaded["fine_print"] and "1 in {}".format(loaded["text"]["bound_one_in"]) in loaded["fine_print"]
    # committed copy agrees with the ad on everything shown (python_ms is re-measured each
    # render, so compare the displayed text, not the raw float)
    js = (media.ROOT / "site" / "data" / "ad-facts.js").read_text()
    committed = json.loads(js.split("window.JEV_AD_FACTS = ", 1)[1].rstrip().rstrip(";"))
    for k in ("calls", "cost", "minutes", "median_s", "min_conf_pct", "bound_one_in"):
        assert committed["text"][k] == loaded["text"][k], k
    assert committed["fake_cells_off"] == 34 and committed["live64_cells_off"] == 0
