"""Self-building cross-ref cache for nonstandard SKUs (v0.9 Change 7)."""
from __future__ import annotations

import json

import pytest

import enrich_engine
from enrich_engine import enrich_row, _search_key


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("MPN_CACHE", str(tmp_path / "mpn_cache.json"))
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("ICECAT_TOKEN", raising=False)
    monkeypatch.setattr(enrich_engine, "_cred", lambda name: None)
    # No exact-MPN capacity lookups in these tests.
    monkeypatch.setattr(enrich_engine, "_search_exact_capacity", lambda mpn: "")


def test_sku_searched_once_then_cache_hit_across_formats(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_search(brand, model):
        calls["n"] += 1
        return {"type": "SSD", "interface": "SAS", "form_factor": '2.5"'}, "OK"
    monkeypatch.setattr(enrich_engine, "search_lookup", fake_search)

    # Two different formats of the same nonstandard SKU share one cross-ref key.
    assert _search_key("Samsung", "PA33N3T8", []) == _search_key("SAMSUNG", "PA33N3T8 3.84TB", [])

    r1 = enrich_row("Samsung", "PA33N3T8")
    r2 = enrich_row("SAMSUNG", "PA33N3T8 3.84TB")   # 2nd occurrence, different format
    assert calls["n"] == 1                          # Brave hit once; 2nd was a cache hit
    assert r1["interface"] == "SAS" and r2["interface"] == "SAS"
    assert "cache" in r2["_source"]

    cache = json.loads((tmp_path / "mpn_cache.json").read_text())
    assert "xref:PA33N3T8" in cache
    assert cache["xref:PA33N3T8"]["ttl_days"] == 60   # confident hit → durable


def test_search_miss_is_short_ttl_not_durable(monkeypatch, tmp_path):
    monkeypatch.setattr(enrich_engine, "search_lookup", lambda b, m: (None, "NO_RESULTS"))
    enrich_row("Toshiba", "5SRB384CCLAR3840")
    cache = json.loads((tmp_path / "mpn_cache.json").read_text())
    key = "xref:" + _search_key("Toshiba", "5SRB384CCLAR3840", [])
    assert cache[key]["fields"] == {}
    assert cache[key]["ttl_days"] == 7   # unconfirmed → re-verify soon, not sticky-wrong
