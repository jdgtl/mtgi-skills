# MTGI Historical Import Template — Schema

The output xlsx must have these columns in this order. Required columns are marked.

| # | Column header (exact text) | Required | Type | Notes |
|---|---|---|---|---|
| 1 | `MPN` | **YES** | text | Manufacturer part number. Trim whitespace; preserve case. |
| 2 | `Quantity` | **YES** | integer | Whole number > 0 |
| 3 | `Bid Price (USD)` | **YES** | currency | Per-unit USD price. Accepts `$1,234.56` or `1234.56`. |
| 4 | `Condition` | optional | enum | See `condition-mapping.md` |
| 5 | `Description` | optional | text | Free-text. Vendor description if present; otherwise composed from confirmed specs (`compose_description.py`, fill-blank-only) with the `(vendor MPN: …)` audit tag appended. |
| 6 | `Outcome` | optional | enum | See `outcome-mapping.md` |
| 7 | `Outcome Date` | optional | date | `YYYY-MM-DD` preferred |
| 8 | `Winning Bid (USD)` | optional | currency | Per-unit USD price for whoever won |
| 9 | `Capacity` | optional | enum-ish | Clean human string, uppercase unit, no spaces. Decimal-TB (1TB = 1000GB). e.g. `1.6TB`, `960GB`, `480GB`, `30GB` |
| 10 | `Interface` | optional | enum | **Exactly one of** `SATA`, `SAS`, `NVMe`. Derived from a `Protocol` column when present. Other buses (PCIe/GbE/FC) are not storage interfaces → blank. |
| 11 | `Drive Type` | optional | enum | **Exactly one of** `SSD`, `HDD`. Strip qualifiers (`U.2 SSD` → `SSD`). Non-storage classes → blank. |
| 12 | `Form Factor` | optional | enum | **One of** `2.5in`, `3.5in`, `M.2`, `U.2`, `PCIe`. Normalize variants (`2.5"`/`2.5 inch` → `2.5in`; `M.2 2280` → `M.2`; `LP PCIe`/add-in card → `PCIe`). |
| 13 | `Manufacturer` | optional | text | Canonical brand spelling, trimmed, single spaces (Intel, Samsung, Toshiba, Micron, Seagate, HGST, Western Digital, Dell, Kioxia, SK Hynix). Blank if unknown — never guessed. Applies to **all** parts. |

Columns 9–13 are emitted by this skill so the MTGI intake wizard can route them into **first-class typed columns** on `rfq_lines` (rather than the generic `custom_fields` JSONB bucket). Headers and values must match this table exactly, or the wizard falls back to `custom_fields`.

Any *other* vendor field this skill emits (Serial, Location, R2 Designation, UID, Notes, Protocol, etc.) is fine — the wizard captures it as `custom_fields`. Do **not** rename those extra columns to the canonical headers above.

**Storage-domain gating.** Columns 9–12 are storage specs (SSD/HDD domain). For non-storage part types (NIC, switch, HBA, RAID controller, RAM, CPU, GPU) these are left blank — the canonicalization step (`scripts/canonicalize_specs.py`) enforces this. `Manufacturer` (col 13) is universal and is populated regardless of part type.

## Header-row formatting

- Required columns: **bold**, white text, teal fill (`#0D9488`)
- Optional columns: normal weight, dark gray text, light gray fill (`#E5E7EB`)
- Row 1 frozen
- Header row height: 24pt
