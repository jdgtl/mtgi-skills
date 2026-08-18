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
BB = bb.summarize(BBFIX["search"], BBFIX["rfq"], BBFIX["supply_demand"], brand="BrightSign")
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


def test_render_contains_verdict_and_table():
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    out = cc.render(r)
    assert "CHANNEL CHECK — HD223" in out
    assert "3 mo net" in out and "6 mo net" in out and "unbounded" in out
    assert "VERDICT " + r["verdict"] in out
    assert "assumptions" in out


def test_apply_writes_channel_block_idempotently(tmp_path):
    p = tmp_path / "MTGI-HD223.json"
    p.write_text(json.dumps(DRAFT))
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    cc.apply(p, r, today=TODAY)
    d1 = json.loads(p.read_text())
    assert d1["channel"]["verdict"] == r["verdict"]
    assert d1["channel"]["checked_at"] == "2026-08-18"
    assert set(d1["channel"]["net"]) == {"ebay", "brokerbin", "combo"}
    cc.apply(p, r, today=TODAY)
    d2 = json.loads(p.read_text())
    assert d1 == d2


def test_main_resolves_by_mpn_and_exits_zero(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BROKERBIN_MOCK", "1")
    (tmp_path / "market").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "market" / "HD223.json").write_text(json.dumps(MARKET))
    (tmp_path / "drafts" / "MTGI-HD223.json").write_text(json.dumps(DRAFT))
    rc = cc.main(["HD223", "--market-dir", str(tmp_path / "market"), "--drafts-dir", str(tmp_path / "drafts"),
                  "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mpn"] == "HD223" and out["verdict"] in ("ebay", "brokerbin", "combo")


def test_main_missing_market_file_is_a_clear_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BROKERBIN_MOCK", "1")
    (tmp_path / "market").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "MTGI-HD223.json").write_text(json.dumps(DRAFT))
    rc = cc.main(["MTGI-HD223", "--market-dir", str(tmp_path / "market"), "--drafts-dir", str(tmp_path / "drafts")])
    assert rc == 0
    assert "market/HD223.json" in capsys.readouterr().err


def test_volume_seller_without_price_is_ignored():
    m = json.loads(json.dumps(MARKET))
    m["ebay"]["volume_seller"] = {"seller": "foo", "units": 40}     # no price_allin
    m["ebay"]["watchers_max"] = 5
    assert cc.pick_share(m, 49.95) == (0.40, "default")
    m["ebay"]["volume_seller"] = {"price_allin": None}
    assert cc.pick_share(m, 49.95) == (0.40, "default")


def test_apply_skipped_when_brokerbin_unavailable(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BROKERBIN_MOCK", "0")
    monkeypatch.setattr(cc.brokerbin_api.BrokerBinAPI, "from_credentials",
                        classmethod(lambda cls, **k: (_ for _ in ()).throw(cc.brokerbin_api.BrokerBinError("quota"))))
    (tmp_path / "market").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "market" / "HD223.json").write_text(json.dumps(MARKET))
    dp = tmp_path / "drafts" / "MTGI-HD223.json"; dp.write_text(json.dumps(DRAFT))
    rc = cc.main(["MTGI-HD223", "--market-dir", str(tmp_path / "market"), "--drafts-dir", str(tmp_path / "drafts"), "--apply"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "not applied" in err
    assert "channel" not in json.loads(dp.read_text())
