import credentials


def test_brokerbin_credentials_are_in_schema():
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["keychain"] == "brokerbin-mtgi-api-token"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["env"] == "BROKERBIN_API_KEY"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["keychain"] == "brokerbin-mtgi-login"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["env"] == "BROKERBIN_LOGIN"


def test_brokerbin_env_override(monkeypatch):
    monkeypatch.setenv("BROKERBIN_API_KEY", "env-token")
    assert credentials.get("brokerbin_api_token") == "env-token"


import json
from pathlib import Path
import pytest
import brokerbin_api as bb

FIX = Path(__file__).parent / "fixtures" / "brokerbin_hd223.json"


def test_mock_search_shape(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    r = api.search("HD223")
    assert r["meta"]["total"] == 6 and len(r["data"]) == 6


def test_summarize_excludes_our_listing():
    fx = json.loads(FIX.read_text())
    s = bb.summarize(fx["search"], fx["rfq"], fx["supply_demand"], brand="BrightSign")
    assert s["sellers"] == 5             # HP row dropped by brand filter
    assert s["other_brand_rows"] == 1
    assert s["unpriced_listings"] == 1   # CALL-priced row
    assert s["ours"] == {"price": 42.0, "qty": 17}
    assert s["ask_med"] == 45.0          # median of 38, 45, 60 (ours + unpriced excluded)
    assert s["ask_min"] == 38.0
    assert s["qty_total"] == 40          # 12 + 6 + 2 + 17 + 3
    assert s["rfq90"] == 2
    assert s["supply_qty_latest"] == 198 and s["matches_latest"] == 29


def test_summarize_no_priced_asks():
    s = bb.summarize({"meta": {}, "data": []}, {"data": []}, {"data": []})
    assert s["ask_med"] is None and s["sellers"] == 0 and s["rfq90"] == 0 and s["ours"] is None


def test_cache_hit_avoids_network(tmp_path, monkeypatch):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("network should not be called")
    monkeypatch.setattr(api, "_fetch", boom)
    api.search("HD223")                  # served from cache
    assert calls["n"] == 0
    assert (tmp_path / "c.json").exists()


def test_refresh_bypasses_cache(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    api2 = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json", refresh=True)
    r = api2.search("HD223")
    assert r["meta"]["total"] == 6


def test_missing_token_names_keychain_item():
    with pytest.raises(bb.BrokerBinError) as e:
        bb.BrokerBinAPI(token=None, mock=False)
    assert "brokerbin-mtgi-api-token" in str(e.value)


def test_last_quota_surfaced(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    assert api.last_quota == {"count": 1, "limit": 50}
