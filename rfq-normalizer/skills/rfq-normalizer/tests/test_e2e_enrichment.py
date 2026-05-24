"""Representative end-to-end enrichment (Brass-Valley-style), offline.

Decodable Seagate/HGST HDD rows resolve HIGH from the part number alone; the
nonstandard Samsung/Toshiba SSD-looking rows can't be decoded and fall to
needs-review (no Brave in this test). Capacity-distribution audit must be clean.
"""
from __future__ import annotations

import pytest

import enrich_engine
from enrich_engine import enrich_row, capacity_audit

# (brand, model) pairs mirroring the real file's shape.
HDD_ROWS = [
    ("Seagate", "ST9300603SS"),
    ("Seagate", "ST9500620NS"),
    ("Seagate", "ST91000640SS"),
    ("HGST", "600GB HUC109060CSS600"),     # capacity from text + decoder for the rest
    ("HGST", "900GB HUC109090CSS600"),
]
SSD_NONSTANDARD = [
    ("Samsung", "PA33N3T8"),
    ("Samsung", "P1633N3T8"),
    ("Toshiba", "5SRB384CCLAR3840"),
]


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("MPN_CACHE", str(tmp_path / "mpn_cache.json"))
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("ICECAT_TOKEN", raising=False)
    monkeypatch.setattr(enrich_engine, "_cred", lambda name: None)


def test_hdd_rows_resolve_high():
    for brand, model in HDD_ROWS:
        r = enrich_row(brand, model)
        assert r["_confidence"] == "HIGH", (brand, model, r)
        assert r["drive_type"] == "HDD"


def test_nonstandard_ssd_rows_go_to_review():
    for brand, model in SSD_NONSTANDARD:
        r = enrich_row(brand, model)
        # Offline they can't be fully resolved → not HIGH → needs-review.
        assert r["_confidence"] != "HIGH"
        assert "NONSTANDARD_MPN" in r["_flags"]


def test_capacity_audit_clean():
    rows = [enrich_row(b, m) for b, m in HDD_ROWS + SSD_NONSTANDARD]
    audit = capacity_audit(rows)
    assert audit["impossible"] == [], audit
