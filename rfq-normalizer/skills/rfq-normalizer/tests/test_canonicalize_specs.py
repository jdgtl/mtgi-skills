"""Tests for canonicalize_specs — internal extraction values → the five
canonical MTGI output columns (Capacity, Interface, Drive Type, Form Factor,
Manufacturer), with storage-domain gating and provenance carry-through.
"""
from __future__ import annotations

from canonicalize_specs import canonicalize

OUTPUT_KEYS = ["Capacity", "Interface", "Drive Type", "Form Factor", "Manufacturer"]


# ─── Capacity ───────────────────────────────────────────────────────────────

def test_capacity_passthrough():
    out = canonicalize({"size": "1.6TB", "drive_type": "SSD"})
    assert out["Capacity"] == "1.6TB"


def test_capacity_strips_internal_whitespace():
    out = canonicalize({"size": " 960GB ", "drive_type": "SSD"})
    assert out["Capacity"] == "960GB"


def test_capacity_blank_when_absent():
    out = canonicalize({"drive_type": "HDD"})
    assert out["Capacity"] is None


# ─── Interface (collapse to SATA | SAS | NVMe, priority NVMe>SAS>SATA) ────────

def test_interface_plain():
    assert canonicalize({"interface": "SATA", "drive_type": "SSD"})["Interface"] == "SATA"
    assert canonicalize({"interface": "SAS", "drive_type": "HDD"})["Interface"] == "SAS"
    assert canonicalize({"interface": "NVMe", "drive_type": "SSD"})["Interface"] == "NVMe"


def test_interface_collapses_richer_strings():
    assert canonicalize({"interface": "SATA III", "drive_type": "SSD"})["Interface"] == "SATA"
    assert canonicalize({"interface": "SAS-12Gb", "drive_type": "HDD"})["Interface"] == "SAS"


def test_interface_priority_nvme_over_others():
    # NVMe drives often report "PCIe x4 NVMe" — NVMe must win.
    assert canonicalize({"interface": "PCIe x4 NVMe", "drive_type": "SSD"})["Interface"] == "NVMe"
    assert canonicalize({"interface": "SAS SATA", "drive_type": "HDD"})["Interface"] == "SAS"


def test_interface_non_storage_bus_blanks():
    # Bare PCIe / GbE / FC are not storage interfaces in the constrained set.
    assert canonicalize({"interface": "PCIe Gen4", "drive_type": "SSD"})["Interface"] is None
    assert canonicalize({"interface": "10GbE", "drive_type": "SSD"})["Interface"] is None


# ─── Drive Type (SSD | HDD only; strip qualifiers) ───────────────────────────

def test_drive_type_strips_qualifiers():
    assert canonicalize({"drive_type": "U.2 SSD"})["Drive Type"] == "SSD"
    assert canonicalize({"drive_type": "M.2 SSD"})["Drive Type"] == "SSD"
    assert canonicalize({"drive_type": "SSD"})["Drive Type"] == "SSD"
    assert canonicalize({"drive_type": "HDD"})["Drive Type"] == "HDD"


def test_drive_type_blank_when_unknown():
    out = canonicalize({"size": "1.6TB", "interface": "SATA"})
    assert out["Drive Type"] is None


def test_drive_type_vendor_spellings():
    # The Evolution file wrote "Hard Drive" (87% of rows) and "Solid State Drive".
    assert canonicalize({"drive_type": "Hard Drive"})["Drive Type"] == "HDD"
    assert canonicalize({"drive_type": "Hard Disk"})["Drive Type"] == "HDD"
    assert canonicalize({"drive_type": "Hard Disk Drive"})["Drive Type"] == "HDD"
    assert canonicalize({"drive_type": "3.5\" HDD"})["Drive Type"] == "HDD"
    assert canonicalize({"drive_type": "Solid State Drive"})["Drive Type"] == "SSD"
    assert canonicalize({"drive_type": "Solid State"})["Drive Type"] == "SSD"


# ─── Form Factor (2.5in | 3.5in | M.2 | U.2 | PCIe) ──────────────────────────

def test_form_factor_inches():
    assert canonicalize({"form_factor": "2.5in", "drive_type": "SSD"})["Form Factor"] == "2.5in"
    assert canonicalize({"form_factor": "3.5in", "drive_type": "HDD"})["Form Factor"] == "3.5in"


def test_form_factor_m2_variants_collapse():
    assert canonicalize({"form_factor": "M.2 2280", "drive_type": "M.2 SSD"})["Form Factor"] == "M.2"


def test_form_factor_pcie_variants_collapse():
    assert canonicalize({"form_factor": "LP PCIe", "drive_type": "SSD"})["Form Factor"] == "PCIe"
    assert canonicalize({"form_factor": "FH PCIe", "drive_type": "SSD"})["Form Factor"] == "PCIe"


def test_form_factor_derived_from_drive_type():
    # U.2 / M.2 are detected as drive_type by the splitter; the canonical
    # Form Factor must be derived from that signal when no form_factor is set.
    assert canonicalize({"drive_type": "U.2 SSD"})["Form Factor"] == "U.2"
    assert canonicalize({"drive_type": "M.2 SSD"})["Form Factor"] == "M.2"


def test_form_factor_rack_units_not_canonical():
    # "2U" is a chassis rack unit, not a drive form factor — not in the set.
    assert canonicalize({"form_factor": "2U", "drive_type": "SSD"})["Form Factor"] is None


def test_form_factor_drive_type_wins_over_noncanonical_ff():
    # Vendor blob yields form_factor "2U" but drive_type "U.2 SSD" → U.2.
    out = canonicalize({"form_factor": "2U", "drive_type": "U.2 SSD"})
    assert out["Form Factor"] == "U.2"


# ─── Manufacturer (universal, normalized, blank if unknown) ──────────────────

def test_manufacturer_normalized_alias():
    # v0.7: HGST canonicalizes to Western Digital (operator decision).
    assert canonicalize({"manufacturer": "HGST", "drive_type": "HDD"})["Manufacturer"] == "Western Digital"


def test_manufacturer_blank_when_absent():
    assert canonicalize({"drive_type": "SSD"})["Manufacturer"] is None


def test_manufacturer_universal_on_non_storage():
    # Manufacturer applies to every part, even non-storage ones.
    out = canonicalize({"drive_type": "NIC", "manufacturer": "Mellanox"})
    assert out["Manufacturer"] == "Nvidia"


# ─── Storage-domain gating ───────────────────────────────────────────────────

def test_non_storage_blanks_storage_specs():
    out = canonicalize({
        "size": "32GB", "interface": "PCIe", "drive_type": "NIC",
        "form_factor": "LP PCIe", "manufacturer": "Intel",
    })
    assert out["Capacity"] is None
    assert out["Interface"] is None
    assert out["Drive Type"] is None
    assert out["Form Factor"] is None
    # Manufacturer survives the gate.
    assert out["Manufacturer"] == "Intel"


def test_memory_module_capacity_not_leaked_as_storage():
    # A 32GB RDIMM must not land in the storage Capacity column.
    out = canonicalize({"size": "32GB", "drive_type": "Memory"})
    assert out["Capacity"] is None


def test_storage_row_keeps_specs():
    out = canonicalize({
        "size": "1.92TB", "interface": "NVMe", "drive_type": "U.2 SSD",
        "manufacturer": "Intel",
    })
    assert out["Capacity"] == "1.92TB"
    assert out["Interface"] == "NVMe"
    assert out["Drive Type"] == "SSD"
    assert out["Form Factor"] == "U.2"
    assert out["Manufacturer"] == "Intel"


def test_drive_with_unknown_type_keeps_capacity_and_interface():
    # No drive_type signal, but capacity + storage interface present: it's a
    # drive whose SSD/HDD class we don't know — keep specs, leave Drive Type blank.
    out = canonicalize({"size": "480GB", "interface": "SATA"})
    assert out["Capacity"] == "480GB"
    assert out["Interface"] == "SATA"
    assert out["Drive Type"] is None


# ─── Provenance ──────────────────────────────────────────────────────────────

def test_provenance_carried_per_output_column():
    out = canonicalize({
        "size": "1.6TB", "drive_type": "SSD",
        "provenance": {
            "size": {"source": "regex", "confidence": 0.95},
            "drive_type": {"source": "brokerbin", "confidence": 0.9},
        },
    })
    prov = out["_provenance"]
    assert prov["Capacity"]["source"] == "regex"
    assert prov["Drive Type"]["source"] == "brokerbin"


def test_provenance_records_normalization():
    # When the displayed value was collapsed/derived, the raw value is recorded.
    out = canonicalize({
        "interface": "PCIe x4 NVMe", "drive_type": "U.2 SSD",
        "provenance": {"interface": {"source": "regex", "confidence": 0.95}},
    })
    assert out["_provenance"]["Interface"]["normalized_from"] == "PCIe x4 NVMe"


def test_provenance_blank_gate_recorded():
    out = canonicalize({"size": "32GB", "drive_type": "NIC"})
    cap_prov = out["_provenance"]["Capacity"]
    assert cap_prov["source"] is None
    assert "non-storage" in cap_prov.get("note", "").lower()


def test_all_output_keys_present():
    out = canonicalize({"size": "1.6TB", "drive_type": "SSD"})
    for k in OUTPUT_KEYS:
        assert k in out
    assert "_provenance" in out
