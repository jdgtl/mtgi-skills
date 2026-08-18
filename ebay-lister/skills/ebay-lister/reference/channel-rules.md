# Channel rules — how the channel check decides

`scripts/channel_check.py` compares three ways to sell a SKU and recommends
one. It is advice; the operator decides. Constants below are mirrored in the
script's `RULES` dict — change both together, and date the change here.

## Inputs
- eBay: `market/<MPN>.json` (exact-SKU figures the AI filters from the operator's
  Seller Hub → Research → Product Research screenshots; see `market-json.md`).
- BrokerBin: live Search API v2 (`brokerbin_api.py`), cached 60 days:
  priced asks by seller (median excludes Micro Technologies), quote requests
  in the last 90 days (`rfqs`), supply/demand histogram (`searches`,
  `avg_total_qty`).
- Draft: `quantity`, `price`, `packageWeightAndSize`, optional `unit_cost`,
  optional `eol_date`.

## Constants (defaults, 2026-08-18)
| Name | Default | Meaning |
|---|---|---|
| fvf | 0.13 | eBay final value fee share |
| label_by_lb | ≤1 lb $8 · ≤3 lb $11 · ≤5 lb $14 · else $28 | per-unit label estimate when no `--label` |
| share_no_competitor | 0.70 | our share of eBay pace when no exact-SKU active |
| share_volume_seller | 0.30 | a volume seller sits at/below our ask |
| share_at_clearing | 0.50 | our ask ≤ sold median and watchers ≤ 2 |
| share_default | 0.40 | none of the above |
| bb_single_haircut | 0.65 | realized single-unit price as share of BrokerBin median ask |
| bb_lot_haircut | 0.55 | realized lot price as share of median ask |
| rfq_conversion | 0.25 | share of 90-day RFQs that become one unit sold |
| salvage / salvage_eol | 0.50 / 0.25 | value of leftovers at horizon, as share of n_b_lot |
| lot_min_qty | 5 | print the "lot of Q" line only from this qty |
| combo_tie_pct | 0.10 | prefer combo when top two are within this |
| thin_solds | 5 | flag when eBay exact-SKU solds are fewer |
| horizons | 3, 6 | months |

Share rules fire in this order (first wins): no competitor → volume seller
at/below our ask → at/below clearing price with watchers ≤ 2 → default.

## Scenarios
- eBay only: sold = min(Q, pace × H); net = sold × n_e + leftover × salvage.
- BrokerBin only: sold = min(Q, rfq pace × H); net = sold × n_b_single +
  leftover × salvage; plus a separate "lot of Q" line at n_b_lot (weight 1.0
  if any RFQs, else 0.5). The lot line is not summed into the scenario.
- Combo: eBay singles for H months, remainder as a BrokerBin lot.
- Unbounded footnote: months to clear at pace, total net.
- EOL cap: `eol_date` clips H and drops salvage to 25%.
- No BrokerBin asks: BrokerBin cells n/a, verdict eBay, salvage 25% of n_e.

## Verdict
Highest 6-month net; tie-break 3-month; if the top two are within
`combo_tie_pct`, combo wins (diversifies). Rationale is one generated sentence.

## Tuning
After the first real BrokerBin trades, replace `bb_*_haircut` and
`rfq_conversion` with observed values (realized / median ask; units sold /
RFQs). After 60 days of eBay sales on a SKU, replace `share_*` with observed
(our sold / market sold in the window). Record changes here with a date.

## What it cannot see
BrokerBin does not report completed sales; its numbers are asks and demand
signals, and `priced=1` hides "CALL"-priced listings (a SKU can show 0 priced
sellers and still be traded). eBay figures are only as good as the screenshot
filtering. Neither side knows MTGI's cost basis unless `unit_cost` is on the
draft.
