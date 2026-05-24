"""Tests for the eBay Browse API client (v0.8 Change 2).

Network is mocked by monkeypatching the raw fetchers, so no token/HTTP is hit.
"""
from __future__ import annotations

import ebay_browse_client
from ebay_browse_client import EbayBrowseClient


def _client():
    return EbayBrowseClient(app_id="x", cert_id="y")


def _detail(aspects, condition=None):
    d = {"localizedAspects": [{"name": n, "value": v} for n, v in aspects.items()]}
    if condition:
        d["condition"] = condition
    return d


def test_consensus_across_listings(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_search_raw", lambda q, limit: [
        {"itemId": "1", "title": "ST9300603SS Seagate"},
        {"itemId": "2", "title": "ST9300603SS"},
        {"itemId": "3", "title": "ST9300603SS drive"},
    ])
    details = {
        "1": _detail({"Brand": "Seagate", "Capacity": "300 GB", "Interface": "SAS",
                      "Form Factor": "2.5 in", "Type": "Hard Drive"}, condition="Used"),
        "2": _detail({"Brand": "Seagate", "Capacity": "300 GB", "Interface": "SAS",
                      "Form Factor": "2.5 in", "Type": "Hard Drive"}, condition="Used"),
        "3": _detail({"Brand": "Seagate", "Capacity": "300 GB"}),
    }
    monkeypatch.setattr(c, "_item_raw", lambda iid: details[iid])

    out = c.search_specs("ST9300603SS")
    f = out["fields"]
    assert f["manufacturer"] == "Seagate"
    assert f["size"] == "300 GB"
    assert f["interface"] == "SAS"
    assert f["form_factor"] == "2.5 in"
    assert f["drive_type"] == "Hard Drive"
    assert f["condition"] == "used_good"   # eBay "Used" → MTGI enum
    # confidence is an agreement ratio, capped at 0.95
    assert 0 < out["field_confidence"]["manufacturer"] <= 0.95


def test_manufacturer_aliases_collapse_before_voting(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_search_raw", lambda q, limit: [
        {"itemId": str(i), "title": "HUS726040ALE610"} for i in range(3)
    ])
    variants = {"0": "WD", "1": "Western Digital", "2": "HGST"}
    monkeypatch.setattr(c, "_item_raw", lambda iid: _detail({"Brand": variants[iid]}))
    out = c.search_specs("HUS726040ALE610")
    # All three collapse to Western Digital → unanimous.
    assert out["fields"]["manufacturer"] == "Western Digital"
    assert out["field_confidence"]["manufacturer"] == 0.95


def test_singleton_value_not_reported(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_search_raw", lambda q, limit: [
        {"itemId": "1", "title": "X"}, {"itemId": "2", "title": "X"},
    ])
    details = {
        "1": _detail({"Capacity": "300 GB", "Interface": "SAS"}),
        "2": _detail({"Capacity": "300 GB"}),  # interface only in 1 listing
    }
    monkeypatch.setattr(c, "_item_raw", lambda iid: details[iid])
    out = c.search_specs("X")
    assert out["fields"]["size"] == "300 GB"      # 2 listings → reported
    assert "interface" not in out["fields"]        # 1 listing → withheld


def test_bad_item_does_not_crash(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_search_raw", lambda q, limit: [
        {"itemId": "1", "title": "X"}, {"itemId": "2", "title": "X"},
    ])

    def _item(iid):
        if iid == "1":
            raise ebay_browse_client.EbayError("boom")
        return _detail({"Capacity": "300 GB"})
    monkeypatch.setattr(c, "_item_raw", _item)
    out = c.search_specs("X")  # must not raise
    assert "size" not in out["fields"]  # only 1 good listing < min corroboration


def test_module_level_degrades_without_credentials(monkeypatch):
    # No app keyset, no mock → client is None → empty result, no crash.
    monkeypatch.delenv("EBAY_MOCK", raising=False)
    monkeypatch.setattr("credentials.get", lambda name: None)
    out = ebay_browse_client.search_specs("ST9300603SS")
    assert out["fields"] == {}
    assert out["raw"]["note"] == "not_configured"
