import json
from datetime import date
from pathlib import Path
import pytest
import brokerbin_api as bb
import channel_check as cc

FIX = Path(__file__).parent / "fixtures"
MARKET = json.loads((FIX / "hd223_market.json").read_text())
DRAFT = json.loads((FIX / "hd223_draft.json").read_text())
BBFIX = json.loads((FIX / "brokerbin_hd223.json").read_text())
BB = bb.summarize(BBFIX["search"], BBFIX["rfq"], BBFIX["supply_demand"])
TODAY = date(2026, 8, 18)


def test_share_rules_precedence():
    m = dict(MARKET); e = dict(MARKET["ebay"])
    e["active_count"] = 0; m["ebay"] = e
    assert cc.pick_share(m, 49.95) == (0.70, "no exact-SKU active competitor")
    e = dict(MARKET["ebay"]); m["ebay"] = e
    assert cc.pick_share(m, 49.95) == (0.40, "default")  # vol seller 50.70 > ask; ask <= median but watchers 4 > 2
    assert cc.pick_share(m, 60.00)[0] == 0.30            # volume seller at/below our ask
    e["volume_seller"] = None; e["watchers_max"] = 2
    assert cc.pick_share(m, 45.00) == (0.50, "at/below clearing price, watchers <= 2")
    e["watchers_max"] = 5
    assert cc.pick_share(m, 45.00) == (0.40, "default")


def test_label_estimate_by_weight():
    assert cc.label_estimate({"weight": {"value": 1, "unit": "POUND"}}) == 8.0
    assert cc.label_estimate({"weight": {"value": 3, "unit": "POUND"}}) == 11.0
    assert cc.label_estimate({"weight": {"value": 13.4, "unit": "POUND"}}) == 28.0
    assert cc.label_estimate(None) == cc.RULES["label_default"]


def test_compute_hd223_numbers():
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    assert round(r["n_e"], 2) == 35.46                   # 49.95 - 13% - $8 label
    assert r["share"] == 0.40
    assert round(r["p_e"], 2) == 3.40                    # 51/6 * 0.40
    assert r["n_b_single"] == round(45.0 * 0.65, 2) and r["n_b_lot"] == round(45.0 * 0.55, 2)
    assert round(r["p_b"], 3) == round(2 / 3 * 0.25, 3)   # rfq90=2
    assert r["eol_months"] == pytest.approx(3.4, abs=0.2)  # 2026-08-18 -> 2026-12-01
    s = r["scenarios"]
    assert s["ebay"]["6"] >= s["ebay"]["3"]
    assert s["brokerbin"]["lot"]["weight"] == 1.0
    assert r["verdict"] in ("ebay", "combo")
    assert "EOL cap" in " ".join(r["flags"])
    assert r["assumptions"]["share"] == 0.40


def test_no_brokerbin_asks_falls_back_to_ebay():
    empty = bb.summarize({"data": []}, {"data": []}, {"data": []})
    d = dict(DRAFT); d.pop("eol_date")
    r = cc.compute(MARKET, d, empty, today=TODAY)
    assert r["n_b_single"] is None
    assert r["scenarios"]["brokerbin"]["6"] is None
    assert r["verdict"] == "ebay"
    assert any("no BrokerBin asks" in f for f in r["flags"])


def test_verdict_prefers_combo_when_within_tie_pct():
    d = dict(DRAFT); d.pop("eol_date")
    tie_rules = dict(cc.RULES); tie_rules["combo_tie_pct"] = 1.0
    r = cc.compute(MARKET, d, BB, rules=tie_rules, today=TODAY)
    assert r["verdict"] == "combo" and "combo preferred" in r["rationale"]
    strict = dict(cc.RULES); strict["combo_tie_pct"] = 0.0
    r2 = cc.compute(MARKET, d, BB, rules=strict, today=TODAY)
    s = r2["scenarios"]
    def key(n):
        return (s[n]["6"] if s[n]["6"] is not None else float("-inf"),
                s[n]["3"] if s[n]["3"] is not None else float("-inf"))
    best = max(("ebay", "brokerbin", "combo"), key=key)   # spec: 6-mo, tie-break 3-mo
    assert r2["verdict"] == best


def test_thin_data_flag():
    m = json.loads(json.dumps(MARKET)); m["ebay"]["sold_units"] = 3
    d = dict(DRAFT); d.pop("eol_date")
    r = cc.compute(m, d, BB, today=TODAY)
    assert any("thin eBay data" in f for f in r["flags"])
