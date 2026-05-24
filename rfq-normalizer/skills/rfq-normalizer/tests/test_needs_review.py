"""Tests for the needs-review report (v0.8 Change 5)."""
from __future__ import annotations

import csv

from write_template import (
    needs_review, review_summary, write_needs_review_csv, _needs_review_path,
)


def _full_row(**over):
    row = {
        "MPN": "ST9300603SS", "Manufacturer": "Seagate", "Condition": "used_good",
        "Capacity": "300GB", "Interface": "SAS", "Drive Type": "HDD",
        "Form Factor": "2.5in", "_provenance": {},
    }
    row.update(over)
    return row


def test_fully_filled_row_not_flagged():
    review = needs_review([_full_row()])
    assert review == []
    assert review_summary([_full_row()], review).startswith("0 of 1 rows need review")


def test_blank_storage_spec_flagged():
    review = needs_review([_full_row(**{"Form Factor": None})])
    assert len(review) == 1
    assert review[0]["missing_fields"] == ["Form Factor"]


def test_non_storage_gated_specs_not_flagged():
    # NIC: storage specs blanked by the gate (provenance note) → not gaps.
    row = _full_row(**{
        "Drive Type": None, "Capacity": None, "Interface": None, "Form Factor": None,
        "Manufacturer": "Nvidia",
        "_provenance": {c: {"source": None, "note": "blanked — non-storage part (drive_type=NIC)"}
                        for c in ("Capacity", "Interface", "Drive Type", "Form Factor")},
    })
    assert needs_review([row]) == []


def test_low_confidence_field_flagged():
    row = _full_row(**{"_provenance": {"Form Factor": {"tagged_low_confidence": True}}})
    review = needs_review([row])
    assert review[0]["low_confidence_fields"] == ["Form Factor"]
    assert review[0]["missing_fields"] == []


def test_unresolved_mpn_flagged():
    row = _full_row(_candidate_real_mpn="MZILS3T8HMLH")
    review = needs_review([row])
    assert review[0]["unresolved_mpn"] is True
    assert review[0]["candidate_real_mpn"] == "MZILS3T8HMLH"


def test_missing_required_manufacturer_flagged():
    review = needs_review([_full_row(Manufacturer=None)])
    assert review[0]["missing_fields"] == ["Manufacturer"]


def test_csv_written(tmp_path):
    rows = [_full_row(), _full_row(**{"Form Factor": None, "MPN": "X"})]
    review = needs_review(rows)
    path = tmp_path / "f-needs-review.csv"
    write_needs_review_csv(review, path)
    with path.open() as f:
        parsed = list(csv.DictReader(f))
    assert len(parsed) == 1
    assert parsed[0]["MPN"] == "X"
    assert parsed[0]["missing_fields"] == "Form Factor"


def test_needs_review_path_derives_from_normalized():
    from pathlib import Path
    assert _needs_review_path(Path("/x/vendor-normalized.xlsx")).name == "vendor-needs-review.csv"
