"""Tests for enrich_row — the decoder-first engine entry point (v0.9 Change 1/2)."""
from __future__ import annotations

import pytest

import enrich_engine
from enrich_engine import enrich_row, capacity_audit


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    # Isolated cache, no network: decoders only.
    monkeypatch.setenv("MPN_CACHE", str(tmp_path / "mpn_cache.json"))
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("ICECAT_TOKEN", raising=False)
    monkeypatch.setattr(enrich_engine, "_cred", lambda name: None)


def test_seagate_sas_high():
    r = enrich_row("Seagate", "ST9300603SS")
    assert r["capacity"] == "300 GB"
    assert r["drive_type"] == "HDD"
    assert r["interface"] == "SAS"
    assert r["form_factor"] == '2.5"'
    assert r["_confidence"] == "HIGH"
    assert r["_mpn"] == "ST9300603SS"


def test_parenthetical_mpn_wins():
    r = enrich_row("HP", "MM1000FBFVR 605832-002 (ST91000640SS)")
    assert r["_mpn"] == "ST91000640SS"
    assert r["capacity"] == "1 TB"
    assert r["drive_type"] == "HDD"
    assert r["_confidence"] == "HIGH"


def test_seagate_sata_legacy():
    r = enrich_row("Seagate", "ST9500620NS")
    assert r["capacity"] == "500 GB"
    assert r["interface"] == "SATA"
    assert r["form_factor"] == '2.5"'
    assert r["_confidence"] == "HIGH"


def test_nonstandard_sku_low_and_flagged():
    r = enrich_row("Intel", "DC S3500 Series")
    assert r["drive_type"] == "SSD"        # looks_ssd token
    assert r["capacity"] == ""             # never invented
    assert r["_confidence"] in ("LOW", "MED")
    assert "NONSTANDARD_MPN" in r["_flags"]


def test_known_value_wins_and_conflict_flagged():
    # Decoder says SAS; uploaded row says SATA → keep SATA, flag the disagreement.
    r = enrich_row("Seagate", "ST9300603SS", known={"interface": "SATA"})
    assert r["interface"] == "SATA"
    assert "KNOWN_CONFLICT" in r["_flags"]


def test_known_fills_blank_without_conflict():
    r = enrich_row("Intel", "DC S3500 Series", known={"capacity": "480GB"})
    assert r["capacity"] == "480GB"
    assert "KNOWN_CONFLICT" not in r["_flags"]


def test_capacity_audit_clean_on_decoded_rows():
    rows = [enrich_row("Seagate", m) for m in
            ("ST9300603SS", "ST91000640SS", "ST9500620NS")]
    audit = capacity_audit(rows)
    assert audit["impossible"] == []


def test_capacity_audit_form_factor_aware():
    # Legit large 3.5" drive is NOT flagged (real-file validation false positive).
    assert capacity_audit([{"capacity": "6 TB", "form_factor": '3.5"'}])["impossible"] == []
    assert capacity_audit([{"capacity": "8 TB", "form_factor": '3.5"'}])["impossible"] == []
    # The greedy-match phantom (large capacity on a 2.5" drive) IS flagged.
    assert capacity_audit([{"capacity": "5 TB", "form_factor": '2.5"'}])["impossible"] == ["5 TB"]
    # Absurd capacity anywhere is flagged.
    assert capacity_audit([{"capacity": "99 TB", "form_factor": '3.5"'}])["impossible"] == ["99 TB"]


def test_engine_cache_path_honors_rfq_cache_dir(monkeypatch, tmp_path):
    # The engine must resolve the same cache file as cache.py given RFQ_CACHE_DIR,
    # so they share one store (Change 7 / Q4).
    monkeypatch.delenv("MPN_CACHE", raising=False)
    monkeypatch.setenv("RFQ_CACHE_DIR", str(tmp_path / "shared"))
    assert enrich_engine._cache_path() == str(tmp_path / "shared" / "mpn_cache.json")
