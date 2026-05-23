#!/usr/bin/env python3
"""Manufacturer alias normalization.

When BrokerBin returns listings for a part, the `mfg` field often varies
across sellers because:
  - Acquisitions: HGST → Western Digital, Sun → Oracle, Compaq → HP, etc.
  - Naming variants: "Samsung Electronics" vs "Samsung" vs "SAMSUNG"
  - Reseller convenience: "DELL EMC" vs "DELL" vs "EMC"

If we count manufacturer votes raw, a part that everyone agrees is HUS726060
(HGST/WD enterprise) might split 50/50 between "HITACHI" and "WESTERN DIGITAL"
and we'd flag the consensus as low. Normalizing to a canonical name first
collapses these variants and gives us the real agreement signal.

Canonical names are chosen for clarity to humans, not strict legal accuracy.
For ambiguous cases (e.g., "Is HUS726060 still HGST or now WD?") we pick
the most useful name for the operator's mental model — Hitachi-prefixed
drives stay Hitachi, WD-prefixed stay Western Digital, etc.
"""
from __future__ import annotations

# Each entry: variants → canonical. Lowercased keys; whitespace normalized.
_ALIASES: dict[str, str] = {
    # Western Digital / HGST / Hitachi storage. WD acquired Hitachi GST in 2012
    # and these drives now ship under WD/Ultrastar branding, so HGST and the
    # Hitachi-GST variants all canonicalize to Western Digital. In this ITAD
    # context plain "Hitachi"-branded drives are HGST/Ultrastar enterprise units
    # (e.g. HUA723020ALA640), so plain "hitachi" maps to WD too — flip this one
    # line if you ever handle genuine non-drive Hitachi parts.
    "hgst":                       "Western Digital",
    "hitachi":                    "Western Digital",
    "hitachi gst":                "Western Digital",
    "hitachi global storage":     "Western Digital",
    "hitachi global storage technologies": "Western Digital",
    "ibm/hitachi":                "Western Digital",
    "western digital":            "Western Digital",
    "wd":                         "Western Digital",
    "wdc":                        "Western Digital",
    "sandisk":                    "SanDisk",
    # Sun / Oracle (Oracle acquired Sun 2010)
    "sun":                        "Oracle",
    "sun microsystems":           "Oracle",
    "sun/oracle":                 "Oracle",
    # HP / HPE / Compaq (HPE split from HP 2015; HP acquired Compaq 2002)
    "hp":                         "HPE",
    "hp enterprise":              "HPE",
    "hewlett packard":            "HPE",
    "hewlett-packard":            "HPE",
    "hewlett packard enterprise": "HPE",
    "compaq":                     "HPE",
    # Dell / Dell EMC / EMC (Dell acquired EMC 2016)
    "dell emc":                   "Dell",
    "dell technologies":          "Dell",
    "emc":                        "Dell",
    "emc corporation":            "Dell",
    # Lenovo / IBM (Lenovo acquired IBM x86 server biz 2014)
    "ibm":                        "IBM",
    "lenovo":                     "Lenovo",
    # Samsung (consumer storage came back to Samsung from Seagate around 2014)
    "samsung electronics":        "Samsung",
    "samsung semi":               "Samsung",
    "samsung semiconductor":      "Samsung",
    # Toshiba (consumer HDD biz to WD; enterprise stayed)
    "toshiba electronics":        "Toshiba",
    "toshiba america":            "Toshiba",
    # Intel / Solidigm (SK Hynix acquired Intel's NAND business 2021 as Solidigm)
    "solidigm":                   "Intel",  # for historical drive MPNs; flip if your team prefers
    "intel corporation":          "Intel",
    # Mellanox / Nvidia (Nvidia acquired Mellanox 2020)
    "mellanox":                   "Nvidia",
    "mellanox technologies":      "Nvidia",
    "nvidia networking":          "Nvidia",
    # Brocade / Broadcom (Broadcom acquired Brocade 2017)
    "brocade":                    "Broadcom",
    "brocade communications":     "Broadcom",
    # SK Hynix
    "hynix":                      "SK Hynix",
    "sk hynix":                   "SK Hynix",
    # Cisco
    "cisco systems":              "Cisco",
}


def normalize_manufacturer(name: str | None) -> str | None:
    """Return the canonical manufacturer name for any known variant.

    Unrecognized names are returned with consistent capitalization (Title Case)
    but otherwise untouched. None / empty stays None.
    """
    if not name or not isinstance(name, str):
        return None
    key = " ".join(name.strip().lower().split())
    if not key:
        return None
    if key in _ALIASES:
        return _ALIASES[key]
    # Title-case for unrecognized long names ("SEAGATE TECHNOLOGY" →
    # "Seagate Technology") but leave short tokens as uppercase since
    # they're usually acronyms (HPE, IBM, AMD, AWS, etc.).
    if name.isupper() or name.islower():
        if len(name.strip()) <= 4:
            return name.strip().upper()
        return name.title()
    return name.strip()


def manufacturers_match(a: str | None, b: str | None) -> bool:
    """Two manufacturer names match if they normalize to the same canonical form."""
    if not a or not b:
        return False
    return normalize_manufacturer(a) == normalize_manufacturer(b)


if __name__ == "__main__":
    test_cases = [
        ("HGST", "HITACHI"),                  # should match → Western Digital
        ("WESTERN DIGITAL", "WD"),            # should match → Western Digital
        ("Hewlett-Packard", "HPE"),           # should match → HPE
        ("Sun Microsystems", "Oracle"),       # should match → Oracle
        ("Compaq", "HP"),                     # should match → HPE
        ("Samsung Electronics", "SAMSUNG"),   # should match → Samsung
        ("CISCO", "Cisco Systems"),           # should match → Cisco
        ("DELL EMC", "Dell"),                 # should match → Dell
        ("Seagate", "Western Digital"),       # should NOT match
        ("Toshiba", "Toshiba America"),       # should match → Toshiba
    ]
    for a, b in test_cases:
        na = normalize_manufacturer(a)
        nb = normalize_manufacturer(b)
        ok = "✓" if na == nb else "✗"
        print(f"  {ok}  '{a}' / '{b}' → '{na}' / '{nb}'")
