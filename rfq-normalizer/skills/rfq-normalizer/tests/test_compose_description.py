"""Tests for compose_description — a fallback Description built from confirmed
canonical spec fields (v0.9.3). Never invents; fill-blank-only; preserves the
vendor-MPN audit tag and any real vendor description."""
from __future__ import annotations

from compose_description import compose_description, fill_description


# ── compose_description (pure) ────────────────────────────────────────────────

def test_composes_in_readable_order():
    out = compose_description({
        "Manufacturer": "Western Digital", "Capacity": "6TB",
        "Drive Type": "HDD", "Interface": "SATA", "Form Factor": "3.5in",
    })
    assert out == "Western Digital 6TB HDD SATA 3.5in"


def test_appends_speed_when_present():
    out = compose_description({
        "Manufacturer": "Seagate", "Capacity": "300GB", "Drive Type": "HDD",
        "Interface": "SAS", "Form Factor": "2.5in", "Speed": "10000",
    })
    assert out == "Seagate 300GB HDD SAS 2.5in 10000 RPM"


def test_too_few_fields_returns_empty():
    assert compose_description({"Manufacturer": "Intel"}) == ""
    assert compose_description({}) == ""


def test_skips_blank_fields():
    out = compose_description({"Capacity": "1TB", "Drive Type": "SSD",
                               "Interface": None, "Form Factor": ""})
    assert out == "1TB SSD"


# ── fill_description (fill-blank-only, audit-tag aware) ────────────────────────

def _storage_row(**over):
    row = {"MPN": "ST6000NM0004", "Capacity": "6TB", "Drive Type": "HDD",
           "Interface": "SATA", "Form Factor": "3.5in", "Manufacturer": "Seagate"}
    row.update(over)
    return row


def test_fills_when_description_blank():
    row = fill_description(_storage_row(Description=None))
    assert row["Description"] == "Seagate 6TB HDD SATA 3.5in"
    assert row["_provenance"]["Description"]["source"] == "composed"


def test_fills_when_only_audit_tag_present_and_preserves_tag():
    row = fill_description(_storage_row(Description="(vendor MPN: ST6000NM0004)"))
    assert row["Description"] == "Seagate 6TB HDD SATA 3.5in (vendor MPN: ST6000NM0004)"


def test_does_not_overwrite_real_vendor_description():
    row = fill_description(_storage_row(
        Description="Seagate Exos enterprise drive, tested (vendor MPN: ST6000NM0004)"))
    assert row["Description"] == "Seagate Exos enterprise drive, tested (vendor MPN: ST6000NM0004)"
    assert "Description" not in row.get("_provenance", {})  # untouched → no composed provenance


def test_too_few_fields_leaves_description_as_is():
    row = fill_description({"MPN": "X", "Manufacturer": "Intel",
                            "Description": "(vendor MPN: X)"})
    # only 1 confirmed field → nothing composed; audit tag preserved
    assert row["Description"] == "(vendor MPN: X)"
