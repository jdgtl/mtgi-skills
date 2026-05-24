# MPN Patterns & Vendor-SKU Detection

When a vendor file gives you a "Model Number" that doesn't actually match
the manufacturer's MPN format, enrichment can't resolve it — marketplace
listings are keyed on real MPNs, not vendor-internal SKUs.

`scripts/mpn_patterns.py` implements a two-signal heuristic:

1. **Local prefix score** — does the MPN start with a known manufacturer prefix?
2. **Listing result** — did any enrichment source (eBay / web) return listings for this MPN?

If both signals are negative → flag as `likely_vendor_sku` and ask the operator.

## Known prefixes (from `mpn_patterns.PATTERNS`)

### Storage (drives)

| Prefix | Manufacturer | Examples |
|---|---|---|
| `ST*` | Seagate | `ST6000NM0004`, `ST1000NX0313` |
| `HUS*`, `HUC*`, `HUH*`, `HMS*` | HGST / Western Digital (post-acquisition) | `HUS726060ALA640` |
| `WD*`, `WUH*`, `WUS*` | Western Digital | `WD40EFRX` |
| `MG*` | Toshiba enterprise | `MG07ACA12TE` |
| `AL*` | Toshiba enterprise SAS | `AL15SEB18EQ` |
| `MK*`, `MQ*`, `DT*` | Toshiba mobile/desktop | |
| `MZ*` | Samsung enterprise SSD | `MZ7L3960HCJR-00A07` |
| `SSDPED*`, `SSDS*` | Intel/Solidigm SSD | |

### Networking

| Prefix | Manufacturer | Examples |
|---|---|---|
| `X710-`, `X550-`, `X520-`, `X540-` | Intel Ethernet | `X710-DA2` |
| `N*K-`, `WS-`, `CSCO-`, `UCS-`, `PWR-`, `SFP-`, `GLC-`, `CAB-` | Cisco | `PWR-C1-1100WAC`, `UCS-SD16TBKS4-EV` |

### Servers

| Prefix | Manufacturer | Examples |
|---|---|---|
| `P#####-A##`, `7#####-A##`, `8#####-A##` | HPE | `P40504-B21` |
| `###-AAAA` | Dell | `400-AUTM` |

### Memory

| Prefix | Manufacturer | Examples |
|---|---|---|
| `M3*` | Samsung DRAM | |
| `HMA*` | SK Hynix | |
| `KSM*`, `KVR*` | Kingston | |

## Scoring

| Score | Meaning |
|---|---|
| `0.92` | Matched a specific manufacturer prefix → high confidence real MPN |
| `0.50` | Matched the generic alphanumeric catch-all → could be real, no strong signal |
| `0.30` | No pattern matched → likely vendor SKU |
| `0.10` – `0.20` | Disqualified (too short, too long, all-letter, all-digit) |

`is_likely_vendor_sku(score, listings_found)` returns True only when no
enrichment source found listings AND the score is below 0.85. A real-but-rare
MPN that a source happens to have listings for won't be flagged.

## Adding more prefixes

`PATTERNS` is order-sensitive — first match wins. When adding:

1. Put more-specific patterns above more-generic ones.
2. Use case-insensitive regexes (always set `re.I`).
3. Anchor with `^` so they only match at the start.
4. Keep the generic catch-all (`^[A-Z0-9]{2,4}[-/]?[A-Z0-9]{4,}.*$`) as the last entry so unknown-but-plausible MPNs still score 0.50.

When the team encounters a new manufacturer with weird-looking MPNs, add a
pattern and re-test against the Brass Valley test file (in `examples/`)
plus any other real samples.
