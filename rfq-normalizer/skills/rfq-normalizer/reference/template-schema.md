# MTGI Historical Import Template — Schema

The output xlsx must have these columns in this order. Required columns are marked.

| # | Column header (exact text) | Required | Type | Notes |
|---|---|---|---|---|
| 1 | `MPN` | **YES** | text | Manufacturer part number. Trim whitespace; preserve case. |
| 2 | `Quantity` | **YES** | integer | Whole number > 0 |
| 3 | `Bid Price (USD)` | **YES** | currency | Per-unit USD price. Accepts `$1,234.56` or `1234.56`. |
| 4 | `Condition` | optional | enum | See `condition-mapping.md` |
| 5 | `Description` | optional | text | Free-text. Used as fallback when split columns are blank. |
| 6 | `Outcome` | optional | enum | See `outcome-mapping.md` |
| 7 | `Outcome Date` | optional | date | `YYYY-MM-DD` preferred |
| 8 | `Winning Bid (USD)` | optional | currency | Per-unit USD price for whoever won |
| 9 | `Size` | optional | text | e.g. `1.6TB`, `32GB`, `480GB` |
| 10 | `Interface` | optional | text | e.g. `SATA`, `SAS`, `NVMe`, `PCIe Gen4 x4` |
| 11 | `Drive Type` | optional | text | e.g. `SSD`, `HDD`, `M.2`, `U.2`, `NIC`, `Switch` |
| 12 | `Form Factor` | optional | text | e.g. `2.5in`, `3.5in`, `M.2 2280`, `LP PCIe` |

Columns 9–12 are NOT in the original MTGI template (which has columns 1–8). They are added by this skill because splitting them out is more useful than keeping a single free-text description. The MTGI wizard's column mapper will let the user map them through as optional fields on import, or ignore them.

## Header-row formatting

- Required columns: **bold**, white text, teal fill (`#0D9488`)
- Optional columns: normal weight, dark gray text, light gray fill (`#E5E7EB`)
- Row 1 frozen
- Header row height: 24pt
