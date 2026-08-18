# market/<MPN>.json — exact-SKU eBay figures

Written by the AI from the operator's two Seller Hub screenshots (Research →
Product Research → **Sold** and **Active**, category **All Categories**, 3 years
for slow enterprise gear / 6 months for fast-moving parts). File name is the
MPN verbatim. Lives in the client workspace:
`01_Clients/mtgi/work/ebay/market/`.

## Filtering rules (the AI does this, never the operator)
1. Keep only rows for the exact SKU and its condition family; drop variants
   (-XL, other port counts), accessories (adapters, transceivers), unrelated
   keyword hits, and "as-is / issue / for parts" rows unless that is our
   condition. List every exclusion in `exclusions`.
2. Unit-weight everything: a row with "total sold 17" counts 17 units.
3. All-in = item price + buyer-paid shipping.
4. Lots: record per-unit all-in in `lots_per_unit`, not in the singles pool.
5. Note the biggest single seller as `volume_seller` (all-in price, units).

## Schema
```json
{
  "mpn": "HD223",
  "condition_scope": "used, unit only",
  "captured": "2026-08-18",
  "ebay": {
    "window_months": 6,
    "sold_units": 51,
    "sold_avg_allin": 59.83,
    "sold_median_allin": 50.70,
    "volume_seller": {"price_allin": 50.70, "units": 24},
    "lots_per_unit": [35, 43, 45],
    "active_count": 40,
    "active_bare_range": [40, 65],
    "watchers_max": 4,
    "exclusions": "9 adapter rows, 3 HD1023, cross-stitch, Allison filter, Massey starter, 1 removed"
  },
  "notes": "Series 3 leaves BrightSign Author Dec 2026"
}
```
`volume_seller` may be `null`. `active_count` counts exact-SKU actives only.
Refresh the file whenever the operator pastes new screenshots; `captured` is
the screenshot date.
