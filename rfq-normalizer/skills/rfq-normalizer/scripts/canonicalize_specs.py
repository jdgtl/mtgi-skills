#!/usr/bin/env python3
"""Canonicalize internal spec values into the five typed MTGI output columns.

The pipeline's extraction (`split_description`) and enrichment (`enrich_mpn`)
deliberately produce *richer* spec values than the MTGI intake wizard accepts —
that richness powers BrokerBin/Brave consensus voting. This module is the final
mapping step: it collapses those internal values into the constrained canonical
sets the wizard maps to typed `rfq_lines` columns, and gates the storage-only
columns so non-storage parts (NICs, switches, RAM) don't carry bogus specs.

Internal input keys → canonical output columns:
    size        → "Capacity"      (verbatim; e.g. "1.6TB", "960GB")
    interface   → "Interface"     (one of SATA | SAS | NVMe, else blank)
    drive_type  → "Drive Type"    (one of SSD | HDD, else blank)
    form_factor → "Form Factor"   (one of 2.5in | 3.5in | M.2 | U.2 | PCIe)
    manufacturer→ "Manufacturer"  (canonical brand; universal — every part)

Hard rule (shared with the rest of the skill): never invent a value. Anything
not confidently derivable from the input is left blank, and every output column
carries provenance — including a reason when a value was blanked by the gate.

Usage:
    echo '{"size":"1.92TB","interface":"PCIe x4 NVMe","drive_type":"U.2 SSD"}' \\
        | python canonicalize_specs.py
    # → {"Capacity":"1.92TB","Interface":"NVMe","Drive Type":"SSD",
    #    "Form Factor":"U.2","Manufacturer":null,"_provenance":{...}}

    # Row mode: canonicalize the spec fields of each row, preserving pass-through
    # columns (MPN, Quantity, …) and merging provenance under output headers.
    echo '{"rows":[{...}]}' | python canonicalize_specs.py
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Output column headers, in template order (cols 9–13 of the MTGI template).
OUTPUT_COLUMNS = ["Capacity", "Interface", "Drive Type", "Form Factor", "Manufacturer"]

# Internal spec keys consumed from a row.
INTERNAL_KEYS = ["size", "interface", "drive_type", "form_factor", "manufacturer"]

# drive_type extraction labels that positively indicate a NON-storage part.
# When any of these is the detected class, the four storage spec columns are
# blanked (Manufacturer is universal and survives).
_NON_STORAGE_DRIVE_TYPES = {
    "NIC", "HBA", "RAID CONTROLLER", "MEMORY", "CPU", "GPU", "SWITCH",
}


def _canon_interface(value: str | None) -> str | None:
    """Collapse any interface string to one of SATA | SAS | NVMe.

    Priority NVMe > SAS > SATA so an NVMe drive reported as "PCIe x4 NVMe"
    resolves to NVMe. Non-storage buses (bare PCIe, GbE, FC) → blank.
    """
    if not value:
        return None
    u = value.upper()
    if "NVME" in u:
        return "NVMe"
    if "SAS" in u:
        return "SAS"
    if "SATA" in u:
        return "SATA"
    return None


def _canon_drive_type(value: str | None) -> tuple[str | None, bool]:
    """Return (canonical_drive_type, is_non_storage).

    canonical_drive_type is "SSD", "HDD", or None. is_non_storage is True only
    when the input positively identifies a non-storage part class — None/unknown
    is NOT treated as non-storage (an unclassified drive keeps its other specs).
    """
    if not value:
        return None, False
    u = value.strip().upper()
    if "SSD" in u:  # also covers "U.2 SSD", "M.2 SSD"
        return "SSD", False
    if "HDD" in u:
        return "HDD", False
    if u in _NON_STORAGE_DRIVE_TYPES:
        return None, True
    return None, False


def _canon_form_factor(form_factor: str | None, drive_type_raw: str | None) -> tuple[str | None, str | None]:
    """Return (canonical_form_factor, derived_from).

    Prefers the form_factor field; if it yields nothing canonical, derives U.2/M.2
    from the raw drive_type signal (the splitter classifies "U.2 SSD"/"M.2 SSD" as
    drive types). `derived_from` names where a non-form_factor value came from, for
    provenance — None when it came from the form_factor field itself.
    """
    if form_factor:
        u = form_factor.upper()
        if u.startswith("2.5"):
            return "2.5in", None
        if u.startswith("3.5"):
            return "3.5in", None
        if u.startswith("M.2"):
            return "M.2", None
        if "U.2" in u:
            return "U.2", None
        if "PCIE" in u:  # "LP PCIe", "FH PCIe", "add-in card"
            return "PCIe", None
        # else: non-canonical (e.g. "2U" rack unit) — fall through to drive_type.

    if drive_type_raw:
        u = drive_type_raw.upper()
        if "U.2" in u:
            return "U.2", "drive_type"
        if "M.2" in u:
            return "M.2", "drive_type"

    return None, None


def _normalize_manufacturer(value: str | None) -> str | None:
    try:
        from manufacturer_aliases import normalize_manufacturer
    except ImportError:
        # Fallback: trim + collapse internal whitespace. Keeps the module usable
        # in harnesses that don't expose the aliases module.
        if not value:
            return None
        cleaned = " ".join(str(value).split())
        return cleaned or None
    return normalize_manufacturer(value)


def canonicalize(specs: dict[str, Any]) -> dict[str, Any]:
    """Map internal spec values to the five canonical output columns + provenance.

    `specs` accepts internal keys (size, interface, drive_type, form_factor,
    manufacturer) and an optional `provenance` dict keyed by those internal names.
    Returns a dict with the OUTPUT_COLUMNS headers and a `_provenance` dict keyed
    by output header.
    """
    in_prov: dict[str, Any] = specs.get("provenance") or {}

    def base_prov(internal_key: str) -> dict[str, Any]:
        p = in_prov.get(internal_key)
        if isinstance(p, dict):
            return dict(p)
        return {"source": None, "confidence": 0}

    raw_size = specs.get("size")
    raw_interface = specs.get("interface")
    raw_drive_type = specs.get("drive_type")
    raw_form_factor = specs.get("form_factor")
    raw_manufacturer = specs.get("manufacturer")

    # ── Compute canonical values ──────────────────────────────────────────
    capacity = " ".join(str(raw_size).split()) if raw_size else None

    interface = _canon_interface(raw_interface)
    drive_type, is_non_storage = _canon_drive_type(raw_drive_type)
    form_factor, ff_derived_from = _canon_form_factor(raw_form_factor, raw_drive_type)
    manufacturer = _normalize_manufacturer(raw_manufacturer)

    out: dict[str, Any] = {
        "Capacity": capacity,
        "Interface": interface,
        "Drive Type": drive_type,
        "Form Factor": form_factor,
        "Manufacturer": manufacturer,
    }

    # ── Provenance ────────────────────────────────────────────────────────
    prov: dict[str, Any] = {
        "Capacity": base_prov("size"),
        "Interface": base_prov("interface"),
        "Drive Type": base_prov("drive_type"),
        "Form Factor": base_prov("form_factor"),
        "Manufacturer": base_prov("manufacturer"),
    }

    # Record normalization when the displayed value differs from the raw input,
    # so the provenance log still shows where each value came from.
    if interface and raw_interface and interface != raw_interface:
        prov["Interface"]["normalized_from"] = raw_interface
    if drive_type and raw_drive_type and drive_type != raw_drive_type:
        prov["Drive Type"]["normalized_from"] = raw_drive_type
    if ff_derived_from == "drive_type":
        # Form Factor came from the drive_type signal, not the form_factor field.
        prov["Form Factor"] = base_prov("drive_type")
        prov["Form Factor"]["normalized_from"] = raw_drive_type
    elif form_factor and raw_form_factor and form_factor != raw_form_factor:
        prov["Form Factor"]["normalized_from"] = raw_form_factor
    if manufacturer and raw_manufacturer and manufacturer != raw_manufacturer:
        prov["Manufacturer"]["normalized_from"] = raw_manufacturer

    # ── Storage-domain gate ───────────────────────────────────────────────
    # Non-storage parts carry no storage specs. Manufacturer is universal.
    if is_non_storage:
        reason = f"blanked — non-storage part (drive_type={raw_drive_type})"
        for col in ("Capacity", "Interface", "Drive Type", "Form Factor"):
            out[col] = None
            prov[col] = {"source": None, "confidence": 0, "note": reason}

    out["_provenance"] = prov
    return out


def canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize the spec fields of a full pipeline row in place.

    Reads internal spec keys + `_provenance` from the row, writes the five output
    columns, and merges canonical provenance into `row["_provenance"]` under the
    output headers. Pass-through columns (MPN, Quantity, …) are preserved.
    """
    specs = {k: row.get(k) for k in INTERNAL_KEYS}
    specs["provenance"] = row.get("_provenance") or {}
    result = canonicalize(specs)

    merged_prov = dict(row.get("_provenance") or {})
    for col in OUTPUT_COLUMNS:
        row[col] = result[col]
        merged_prov[col] = result["_provenance"][col]
    row["_provenance"] = merged_prov
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=None, help="JSON file (default: stdin)")
    args = ap.parse_args()

    raw = json.load(open(args.input) if args.input else sys.stdin)

    if isinstance(raw, list):
        out: Any = [canonicalize(item) for item in raw]
    elif isinstance(raw, dict) and "rows" in raw:
        out = {"rows": [canonicalize_row(r) for r in raw["rows"]]}
    else:
        out = canonicalize(raw)

    json.dump(out, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
