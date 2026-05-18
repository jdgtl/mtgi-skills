#!/usr/bin/env python3
"""Extract structured specs from a free-text description.

Patterns codified from reference/description-patterns.md.

Usage:
    echo '{"description": "1.6TB SATA SSD 2.5\""}' | python split_description.py
    -> {"size": "1.6TB", "interface": "SATA", "drive_type": "SSD",
        "form_factor": "2.5in", "provenance": {...}}
"""
from __future__ import annotations
import argparse
import json
import re
import sys

# ─── Patterns ─────────────────────────────────────────────────────────────────

SIZE_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.I), "TB"),
    (re.compile(r"(\d+)\s*GB\b", re.I),           "GB"),
    (re.compile(r"(\d+)\s*MB\b", re.I),           "MB"),
]

INTERFACE_PATTERNS = [
    (re.compile(r"\bSAS[\s-]*\d{0,2}G?b?\b", re.I), "SAS"),
    (re.compile(r"\bSATA(?:[\s-]*(?:III|3|6Gb?))?", re.I), "SATA"),
    (re.compile(r"\bNVMe?\b", re.I), "NVMe"),
    (re.compile(r"\bPCIe?\s*Gen\s*(\d)\b", re.I), "PCIe Gen{0}"),
    (re.compile(r"\bPCIe?\s*x(\d+)\b", re.I), "PCIe x{0}"),
    (re.compile(r"\b(10|25|40|100)\s*GbE\b", re.I), "{0}GbE"),
    (re.compile(r"\bFibre?\s*Channel\b|\bFC\b(?![A-Z])", re.I), "FC"),
]

DRIVE_TYPE_PATTERNS = [
    (re.compile(r"\bSSD\b|\bSolid\s*State\s*Drive\b", re.I), "SSD"),
    (re.compile(r"\bHDD\b|\bHard\s*Drive\b|\bHard\s*Disk\b", re.I), "HDD"),
    (re.compile(r"\bU\.2\b", re.I), "U.2 SSD"),
    (re.compile(r"\bM\.2\b", re.I), "M.2 SSD"),
    (re.compile(r"\bNIC\b|\bNetwork\s*(Card|Adapter)\b|\bEthernet\s*Adapter\b", re.I), "NIC"),
    (re.compile(r"\bHBA\b|\bHost\s*Bus\s*Adapter\b", re.I), "HBA"),
    (re.compile(r"\bRAID\s*(Controller|Card)\b", re.I), "RAID Controller"),
    (re.compile(r"\b(RDIMM|LRDIMM|DIMM|Memory|RAM)\b", re.I), "Memory"),
    (re.compile(r"\bCPU\b|\bProcessor\b", re.I), "CPU"),
    (re.compile(r"\bGPU\b|\bGraphics\s*Card\b", re.I), "GPU"),
    (re.compile(r"\bSwitch\b", re.I), "Switch"),
]

FORM_FACTOR_PATTERNS = [
    (re.compile(r"\b2\.5\s*(?:\"|inch|in)\b|\bSFF\b", re.I), "2.5in"),
    (re.compile(r"\b3\.5\s*(?:\"|inch|in)\b|\bLFF\b", re.I), "3.5in"),
    (re.compile(r"\bM\.2\s*22(?:80|30|110)\b|\b22(?:80|30|110)\b", re.I), "M.2 {0}"),
    (re.compile(r"\bLow\s*Profile\b|\bLP\b|\bHalf-Height\b", re.I), "LP PCIe"),
    (re.compile(r"\bFull\s*Height\b|\bFH\b(?![A-Z])", re.I), "FH PCIe"),
    (re.compile(r"\b([12])U\b", re.I), "{0}U"),
]


def extract_size(desc: str) -> str | None:
    for pattern, unit in SIZE_PATTERNS:
        m = pattern.search(desc)
        if not m:
            continue
        val = float(m.group(1))
        # Sanity bounds
        if unit == "TB" and (val < 0.001 or val > 1000): continue
        if unit == "GB" and (val < 1 or val > 1_000_000): continue
        # Format: trim trailing .0 from TB
        if unit == "TB" and val == int(val):
            return f"{int(val)}TB"
        if unit == "TB":
            return f"{val}TB"
        return f"{int(val)}{unit}"
    return None


def extract_interface(desc: str) -> str | None:
    hits = []
    for pattern, label in INTERFACE_PATTERNS:
        m = pattern.search(desc)
        if m:
            if "{0}" in label:
                hits.append(label.format(m.group(1)))
            else:
                hits.append(label)
    if not hits:
        return None
    # Dedupe preserving order
    seen = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    return " ".join(seen)


def extract_drive_type(desc: str) -> str | None:
    for pattern, label in DRIVE_TYPE_PATTERNS:
        if pattern.search(desc):
            return label
    return None


def extract_form_factor(desc: str) -> str | None:
    for pattern, label in FORM_FACTOR_PATTERNS:
        m = pattern.search(desc)
        if m:
            if "{0}" in label and m.groups():
                return label.format(m.group(1) if m.group(1) else "")
            return label
    return None


def split(description: str) -> dict:
    if not description or len(description.strip()) < 4:
        return {
            "size": None, "interface": None, "drive_type": None, "form_factor": None,
            "provenance": {"reason": "description too short"},
        }

    desc = description.strip()
    result = {
        "size": extract_size(desc),
        "interface": extract_interface(desc),
        "drive_type": extract_drive_type(desc),
        "form_factor": extract_form_factor(desc),
    }
    provenance = {
        field: {"source": "regex", "confidence": 0.95} if val else {"source": None, "confidence": 0}
        for field, val in result.items()
    }
    result["provenance"] = provenance
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--description", help="Single description to split (skip stdin)")
    args = ap.parse_args()

    if args.description:
        out = split(args.description)
    else:
        raw = json.load(sys.stdin)
        out = split(raw.get("description", ""))

    json.dump(out, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
