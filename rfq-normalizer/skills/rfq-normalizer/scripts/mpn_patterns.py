#!/usr/bin/env python3
"""Manufacturer MPN pattern detection.

Used to spot "this isn't a real manufacturer MPN — it's probably a vendor
internal SKU" so the agent can prompt the operator instead of burning a
BrokerBin API call that will return 0 results.

The lists below are NOT exhaustive — IT-equipment MPN space is enormous.
They're tuned for the common cases that come through MTGI's vendors:
storage drives, server/network gear from the big OEMs.

False positives (real MPN scored low) are tolerable — we'll still try
BrokerBin and only flag if BOTH the local pattern check fails AND the
API returns 0 results. False negatives (vendor SKU scored high) just
mean we waste one API call before flagging.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# ─── Prefix patterns ─────────────────────────────────────────────────────────
# Format: (regex, suggested_manufacturer, description). Order matters when
# multiple could match — first match wins.

PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # ── Storage: drives ─────────────────────────────────────────────────────
    (re.compile(r"^ST[0-9]{2,}.*", re.I),       "Seagate",          "Seagate (all consumer/enterprise drives)"),
    (re.compile(r"^HUS[0-9].*", re.I),          "Western Digital",  "HGST/WD enterprise SATA (acquired by WD)"),
    (re.compile(r"^HUC[0-9].*", re.I),          "Western Digital",  "HGST/WD enterprise SAS"),
    (re.compile(r"^HUH[0-9].*", re.I),          "Western Digital",  "HGST/WD He-filled drives"),
    (re.compile(r"^HMS[0-9].*", re.I),          "Western Digital",  "HGST/WD mobile"),
    (re.compile(r"^WD[0-9].*", re.I),           "Western Digital",  "WD consumer drives"),
    (re.compile(r"^WUH[0-9].*|^WUS[0-9].*", re.I), "Western Digital", "WD enterprise (post-HGST rebrand)"),
    (re.compile(r"^MG[0-9]{2}.*", re.I),        "Toshiba",          "Toshiba enterprise drives (MG04/MG06/MG07/MG08)"),
    (re.compile(r"^MK[0-9].*", re.I),           "Toshiba",          "Toshiba mobile (older)"),
    (re.compile(r"^MQ[0-9].*", re.I),           "Toshiba",          "Toshiba mobile (newer)"),
    (re.compile(r"^AL[0-9]{2}.*", re.I),        "Toshiba",          "Toshiba enterprise SAS (AL13/AL14/AL15)"),
    (re.compile(r"^DT[0-9].*", re.I),           "Toshiba",          "Toshiba desktop"),
    # ── Storage: SSDs ───────────────────────────────────────────────────────
    (re.compile(r"^MZ[0-9A-Z].*", re.I),        "Samsung",          "Samsung enterprise SSD (PM/SM series)"),
    (re.compile(r"^SSDPE[A-Z].*", re.I),        "Intel",            "Intel/Solidigm DC SSD (SSDPE series)"),
    (re.compile(r"^SSDS[A-Z][0-9].*", re.I),    "Intel",            "Intel client/server SSD (SSDSC/SSDSA)"),
    (re.compile(r"^MTFDD[A-Z].*", re.I),        "Micron",           "Micron client/enterprise SSD"),
    (re.compile(r"^MTFDH[A-Z].*", re.I),        "Micron",           "Micron mainstream SSD"),
    (re.compile(r"^THNSF[0-9A-Z].*", re.I),     "Toshiba",          "Toshiba/Kioxia client SSD"),
    (re.compile(r"^KPM[0-9A-Z].*", re.I),       "Kioxia",           "Kioxia datacenter SAS SSD (KPM5/KPM6)"),
    (re.compile(r"^KXG[0-9A-Z].*", re.I),       "Kioxia",           "Kioxia datacenter NVMe SSD"),
    (re.compile(r"^SDFA[A-Z]?[0-9-].*|^SDLF[A-Z]?[0-9-].*", re.I),
                                                "SanDisk",          "SanDisk/WD enterprise SSD"),
    (re.compile(r"^0F[0-9]{4,}.*", re.I),       "HGST",             "HGST OEM part numbers (0F22811 etc.)"),
    # ── Networking ──────────────────────────────────────────────────────────
    (re.compile(r"^X710-|^X550-|^X520-|^X540-", re.I), "Intel",     "Intel Ethernet adapters"),
    (re.compile(r"^N[0-9]K-|^WS-|^CSCO-|^UCS-|^PWR-|^SFP-|^GLC-|^CAB-", re.I),
                                                "Cisco",            "Cisco networking + UCS"),
    # ── Servers / generic OEM ──────────────────────────────────────────────
    (re.compile(r"^P[0-9]{5}-[A-Z][0-9]+$|^[78][0-9]{5}-[A-Z][0-9]+$", re.I),
                                                "HPE",              "HPE/HP server SKUs (Pxxxxx-B21, 7xxxxx-B21)"),
    (re.compile(r"^[0-9]{3}-[A-Z]{4}$|^[0-9]{2}[A-Z]{4}[0-9]+$", re.I),
                                                "Dell",             "Dell parts (400-AUTM style)"),
    # ── Memory ──────────────────────────────────────────────────────────────
    (re.compile(r"^M3[0-9][A-Z][0-9].*", re.I), "Samsung",          "Samsung DRAM modules"),
    (re.compile(r"^HMA[A-Z]?[0-9].*", re.I),    "SK Hynix",         "Hynix memory"),
    (re.compile(r"^KSM[0-9].*|^KVR[0-9].*",     re.I), "Kingston",  "Kingston server memory"),
    # ── Catch-all "looks like a real MPN" ──────────────────────────────────
    # Mostly alphanumeric, 6-30 chars, has at least one letter AND one digit,
    # plausible hyphens/slashes allowed.
    (re.compile(r"^[A-Z0-9]{2,4}[-/]?[A-Z0-9]{4,}.*$", re.I),
                                                "",                 "generic alphanumeric — unknown manufacturer"),
]


@dataclass
class MpnPatternScore:
    """Score for "does this look like a real manufacturer MPN?"

    Scoring tiers:
      0.92 — matched a specific known manufacturer prefix (Seagate ST*,
             Hitachi/WD HUS*, Toshiba MG*, Cisco UCS-/PWR-/SFP-, etc.)
      0.50 — matched the generic alphanumeric catch-all (could be real
             but no strong manufacturer signal)
      0.30 — no pattern matched (likely a vendor internal SKU)
      0.10 — disqualified (too short, too long, all letters, all digits)

    Callers should combine this score with the BrokerBin lookup result:
    a 0.50 MPN that BrokerBin found is fine; a 0.50 MPN that BrokerBin
    can't find is probably a vendor SKU and the operator should be asked
    to provide the real manufacturer MPN.
    """
    score: float
    matched_pattern: str | None
    suggested_manufacturer: str | None

    @property
    def has_known_prefix(self) -> bool:
        return self.score >= 0.85

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "matched_pattern": self.matched_pattern,
            "suggested_manufacturer": self.suggested_manufacturer,
            "has_known_prefix": self.has_known_prefix,
        }


def score_mpn(mpn: str) -> MpnPatternScore:
    """Score how likely an MPN is to be a real manufacturer part number."""
    if not mpn or not isinstance(mpn, str):
        return MpnPatternScore(0.0, None, None)

    cleaned = mpn.strip()

    # Quick disqualifiers
    if len(cleaned) < 4 or len(cleaned) > 40:
        return MpnPatternScore(0.1, None, None)
    letters = sum(c.isalpha() for c in cleaned)
    digits = sum(c.isdigit() for c in cleaned)
    if letters == 0 or digits == 0:
        # Pure-digit or pure-letter strings are unusual for IT MPNs
        return MpnPatternScore(0.2, None, None)

    for pattern, suggested_mfg, description in PATTERNS:
        if pattern.match(cleaned):
            # Generic catch-all = medium score; specific manufacturer patterns = high.
            score = 0.50 if suggested_mfg == "" else 0.92
            return MpnPatternScore(
                score=score,
                matched_pattern=description,
                suggested_manufacturer=suggested_mfg or None,
            )

    # No pattern matched — most likely a vendor SKU
    return MpnPatternScore(score=0.30, matched_pattern=None, suggested_manufacturer=None)


def is_likely_vendor_sku(score: MpnPatternScore, brokerbin_found_listings: bool) -> bool:
    """Combine the local pattern score with BrokerBin's actual result.

    Returns True only when both signals point the same way: the MPN doesn't
    match a known manufacturer prefix AND BrokerBin couldn't find any listings
    for it. A real-but-rare MPN that BrokerBin has won't be flagged; a
    weird-looking MPN that BrokerBin does have listings for won't be flagged.
    """
    if brokerbin_found_listings:
        return False
    return score.score < 0.85


# Brand-prefix stripping — vendors sometimes prepend the manufacturer name to
# the MPN ("INTEL SSDSC2BB012T6"). When that happens, the part after the
# prefix should be the real MPN. We only strip prefixes we have high
# confidence in.
_BRAND_PREFIX_RE = re.compile(
    r"^(INTEL|TOSHIBA|HGST|WDC|SAMSUNG|MICRON|KIOXIA|SANDISK|SEAGATE)\s+([A-Z0-9][A-Z0-9\-]{3,})$",
    re.I,
)


def strip_brand_prefix(mpn: str) -> tuple[str, str]:
    """Strip a well-known brand prefix from an MPN.

    Returns (cleaned_mpn, original_string). When no known prefix is present,
    cleaned == original. The caller should preserve `original` somewhere
    (description column, provenance) so the swap is auditable.
    """
    if not isinstance(mpn, str):
        return mpn, mpn
    m = _BRAND_PREFIX_RE.match(mpn.strip())
    if not m:
        return mpn, mpn
    return m.group(2), mpn


if __name__ == "__main__":
    import sys
    import json
    test_mpns = sys.argv[1:] or [
        "ST6000NM0004",        # Seagate enterprise — high
        "HUS726060ALA640",     # HGST/WD enterprise — high
        "MZ7L3960HCJR-00A07",  # Samsung SSD — high
        "PA33N3T8",            # vendor SKU from Brass Valley — should flag
        "5SRB384CCLAR3840",    # vendor SKU — should flag
        "X710-DA2",            # Intel NIC
        "PWR-C1-1100WAC",      # Cisco PSU
        "400-AUTM",            # Dell drive
        "P40504-B21",          # HPE drive
        "12345",               # too generic
    ]
    for mpn in test_mpns:
        result = score_mpn(mpn)
        marker = "✓ known prefix" if result.has_known_prefix else ("? unknown" if result.score >= 0.4 else "⚠ likely SKU")
        print(f"  {mpn:25} score={result.score:.2f}  {marker:14}  mfg={result.suggested_manufacturer or '-':18}  ({result.matched_pattern or 'no match'})")
