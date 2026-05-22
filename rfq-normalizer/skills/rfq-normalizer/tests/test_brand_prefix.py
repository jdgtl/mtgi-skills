"""End-to-end coverage that strip_brand_prefix is wired into enrich()."""
import os
from mpn_patterns import strip_brand_prefix, score_mpn
from enrich_mpn import enrich


def test_strip_returns_brand_only_for_known_prefix():
    cleaned, brand = strip_brand_prefix("MICRON MTFDDAK480TDS")
    assert cleaned == "MTFDDAK480TDS"
    assert brand == "MICRON"


def test_cleaned_mpn_scores_as_known_prefix():
    # Sanity: bare MPN scores high; that's the whole reason to strip.
    s_raw = score_mpn("INTEL SSDSC2BB012T6")
    s_clean = score_mpn("SSDSC2BB012T6")
    assert s_clean.has_known_prefix
    # The raw form does NOT score as a known prefix — that's the bug we fix downstream.
    assert not s_raw.has_known_prefix


def test_enrich_strips_brand_and_preserves_original(monkeypatch, tmp_path):
    # Disable all tiers so enrich() runs without network.
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RFQ_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("RFQ_CREDS_FILE", raising=False)

    result = enrich("INTEL SSDSC2BB012T6", needed_fields=[], use_cache=False)
    assert result["mpn"] == "SSDSC2BB012T6"
    assert result.get("original_mpn") == "INTEL SSDSC2BB012T6"


def test_enrich_no_brand_prefix_no_original_mpn(monkeypatch, tmp_path):
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RFQ_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("RFQ_CREDS_FILE", raising=False)

    result = enrich("SSDSC2BB012T6", needed_fields=[], use_cache=False)
    assert result["mpn"] == "SSDSC2BB012T6"
    # No brand prefix → no original_mpn key
    assert "original_mpn" not in result
