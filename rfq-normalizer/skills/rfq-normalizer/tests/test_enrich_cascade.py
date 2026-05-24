"""Tests for the v0.8 enrichment cascade — eBay replaces BrokerBin."""
from __future__ import annotations

import enrich_mpn
from enrich_mpn import TIERS, enrich


def test_tier_order_has_ebay_not_brokerbin():
    names = [name for name, _ in TIERS]
    assert names == ["mtgi_catalog", "ebay", "web_search"]
    assert "brokerbin" not in names


def test_enrich_fills_from_ebay_and_cites_tier(monkeypatch):
    # eBay mock provides manufacturer + drive_type at high confidence; Brave and
    # MTGI are unconfigured and skip. No BrokerBin tier exists.
    monkeypatch.setenv("EBAY_MOCK", "1")
    monkeypatch.setattr("credentials.get", lambda name: None)
    for var in ("MTGI_API_URL", "MTGI_API_TOKEN", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    out = enrich("ST9300603SS", ["manufacturer", "drive_type", "interface"], use_cache=False)

    assert out["fields"]["manufacturer"] == "Seagate"
    assert out["provenance"]["manufacturer"]["source"] == "ebay"
    # interface absent from the eBay mock → stays unfilled (never invented).
    assert out["fields"]["interface"] is None
    assert "interface" in out["unfilled"]
    # No tier named brokerbin ran.
    assert all(entry["tier"] != "brokerbin" for entry in out["tier_log"])
