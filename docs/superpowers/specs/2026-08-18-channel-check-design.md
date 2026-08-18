# Channel check — eBay vs BrokerBin vs combo (ebay-lister step 1c)

Status: approved design, 2026-08-18. Owner: ebay-lister plugin.

## Problem

MTGI's lot SO87579 (43 MPNs, 491 units) contains SKUs that clear on eBay in
weeks (HD223, C6800-16P10G) and SKUs that would take 5+ years as eBay singles
(ET91000SM20 ×15, Enable-IT 828 ×8, 4K1042-WW ×19). BrokerBin — a broker-to-
broker marketplace MTGI already uploads inventory to — is the outlet for bulk.
Today the channel choice is a judgment call made in chat. It should be a
scripted comparison with an explicit recommendation.

## Decision summary

- One script inside ebay-lister: `channel_check.py`, stdlib only, Keychain token.
- Recommend only. Three scenarios (eBay-only, BrokerBin-only, combo) × two
  horizons (3, 6 months) + an unbounded footnote. Verdict = highest net at 6
  months; operator confirms; `--apply` writes the verdict into the draft JSON.
- eBay market figures come from Seller Hub Product Research screenshots the
  operator pastes; the AI filters to the exact SKU and writes
  `work/ebay/market/<MPN>.json`. BrokerBin figures come from the API v2, cached.
  Firecrawl-driven capture of Seller Hub is a follow-up, not v0.1.

## Data model

`01_Clients/mtgi/work/ebay/market/<MPN>.json` (written by the AI from the
operator's Sold + Active screenshots; exact-SKU filtered):

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
    "volume_seller": { "price_allin": 50.70, "units": 24 },
    "lots_per_unit": [35, 43, 45],
    "active_count": 40,
    "active_bare_range": [40, 65],
    "watchers_max": 4,
    "exclusions": "9 adapter rows, 3 HD1023, cross-stitch, Allison filter, Massey starter, 1 removed"
  },
  "notes": "Series 3 leaves BrightSign Author Dec 2026"
}
```

From the draft JSON (`work/ebay/drafts/<SKU>.json`): `quantity`, `price`,
`autoAcceptPrice`, `condition`, `packageWeightAndSize`; optional `unit_cost`
(shows margin when present), optional `eol_date` (`YYYY-MM-DD`).

BrokerBin (live, cached 60 days at `work/ebay/market/.brokerbin-cache.json`):
`/part/search?query=<MPN>&priced=1&size=50` → priced asks by condition, seller
count, total qty, whether Micro Technologies is listed and at what price/qty;
`/part/history/rfq?query=<MPN>&from=<90d ago>` → quote-request count;
`/part/history/supply-demand?query=<MPN>&interval=month&from=<12mo ago>` →
qty listed vs. search matches. Three calls per MPN, 50/day quota → the whole
lot in one pass.

Written back to the draft on `--apply`:

```json
"channel": {
  "verdict": "combo",
  "checked_at": "2026-08-18",
  "horizon_months": 6,
  "net": { "ebay": 612, "brokerbin": 340, "combo": 705 },
  "rationale": "eBay pace 3.4/mo x 30% share cannot clear 17 before 2026-12; BrokerBin shows 2 RFQs/90d; combo nets $705 vs $612.",
  "assumptions": { "share": 0.30, "rfq_conversion": 0.25, "bb_single_haircut": 0.65, "bb_lot_haircut": 0.55, "fvf": 0.13 }
}
```

## Scenario math (constants in `reference/channel-rules.md`)

Inputs: `Q` on hand; eBay pace `p_e = sold_units / window_months × share`;
eBay net/unit `n_e = ask − FVF×ask − label`; BrokerBin `ask_med` (median priced
ask, condition-matched, other sellers only), `rfq90`, `supply_qty`.

- **share**, first rule that fires wins: 0.70 if `active_count = 0` (no
  exact-SKU competitor); 0.30 if a volume seller sits at/below our ask;
  0.50 if our ask ≤ `sold_median_allin` and `watchers_max ≤ 2`; else 0.40.
  The fired rule is printed.
- **No BrokerBin asks** (`ask_med` undefined): BrokerBin-only and the combo
  remainder are shown as `n/a`, salvage falls back to 0.25 × `n_e`, and the
  flag "no BrokerBin asks for this MPN" prints; verdict is then eBay-only.
- **BrokerBin realized price**: `n_b_single = ask_med × 0.65`,
  `n_b_lot = ask_med × 0.55`; no fees. **Pace** `p_b = rfq90 / 3 × 0.25`
  units/month; 0 if `rfq90 = 0`.
- **Label**: mode from `sales_history.py shipping` when available, else a
  per-weight estimate from `packageWeightAndSize` (≤1 lb $8, ≤3 lb $11,
  ≤5 lb $14, else $28); FVF 0.13 default, override per category in rules.
- **eBay-only** at horizon H: `sold = min(Q, p_e·H)`, `net = sold·n_e +
  (Q−sold)·salvage`, `salvage = 0.5·n_b_lot` (0.25 if EOL-capped).
- **BrokerBin-only**: `sold = min(Q, p_b·H)`, `net = sold·n_b_single +
  (Q−sold)·salvage`. If `Q ≥ 5` also print a **lot line**: `Q·n_b_lot`,
  weight 1.0 if `rfq90 > 0` else 0.5, clearing assumed ≤60 days. Reported as
  its own row, not summed into the scenario.
- **Combo**: eBay singles for H months as above; remainder as a BrokerBin lot at
  `n_b_lot × (1.0 if rfq90 > 0 else 0.5)`.
- **Unbounded** footnote per scenario: months to clear at pace, total net.
- **EOL cap**: `H = min(H, months_to_eol)`; salvage → 0.25.
- **Verdict**: highest net at H=6; tie-break H=3; if the top two are within
  10%, prefer combo and say why. Rationale is one generated sentence.
- **Flags** under the table: `sold_units < 5` → "thin eBay data";
  `rfq90 = 0` → "no BrokerBin demand signal"; "MTGI already on BrokerBin at
  $X × N — sync qty after eBay sales" when applicable; assumptions list.

## BrokerBin client

`scripts/brokerbin_api.py` — thin, stdlib: `search(mpn, priced=True, size=50)`,
`rfq(mpn, days=90)`, `supply_demand(mpn, months=12)`, `stats(mpn)` (unused in
v0.1, kept for the trading desk). Bearer token from `credentials.py`
(Keychain `brokerbin-mtgi-api-token`; optional `login` header from
`brokerbin-mtgi-login`), 500 ms throttle, 3 retries, 15 s timeout, 401/403 →
clear error naming the Keychain item. File cache keyed by
`endpoint|mpn|params`, 60-day TTL, `--refresh` bypasses. Every response's
`meta.request` (`count`/`limit`) is surfaced so the operator sees quota.
`BROKERBIN_MOCK=1` returns fixtures for tests.

## Output and skill step

`channel_check.py <SKU-or-MPN> [--apply] [--refresh] [--json]`:

```
CHANNEL CHECK — HD223 (17 units, ask $49.95, used/unit only)   checked 2026-08-18
eBay      51 sold / 6 mo · avg $59.83 · median $50.70 · vol-seller $50.70×24 · 40 active · share 30% (rule: volume seller at/below price)
BrokerBin 12 sellers · med ask $38 · qty 210 · RFQ/90d 2 · Micro Technologies: not listed
                       3 mo net     6 mo net     unbounded
  eBay only            $ 388        $ 612        17 units in 5.0 mo → $ 646
  BrokerBin only       $  49        $  98        17 units in 102 mo → $ 425
    lot of 17          $ 355 (weight 1.0, ≤60 d)
  Combo                $ 611        $ 705        —
VERDICT combo — eBay pace 3.4/mo × 30% cannot clear 17 before 2026-12 (EOL cap 3.5 mo); BrokerBin shows 2 RFQs/90d; combo nets $705 vs $612.
flags: EOL cap active (2026-12-01); assumptions share .30 · rfq conv .25 · bb haircut .65/.55 · fvf .13 · label $8
```

`--apply` writes the `channel` block into the draft; `--json` emits the full
computation. Exit 0 always (advice, not a gate).

SKILL.md gains **step 1c — Marketplace check** between 1b (price) and 2
(facts): ask the operator for the Sold + Active Product Research screenshots
(All Categories, 3 years for slow gear / 6 months for fast), filter to the
exact SKU, write `market/<MPN>.json`, run `channel_check.py`, present the
table, and record the operator's decision with `--apply`. `reference/
channel-rules.md` documents constants and how to tune them. `spec.md`
documents the `channel`, `unit_cost`, `eol_date` fields.

## Testing

`tests/test_channel_check.py` (pytest, `BROKERBIN_MOCK=1`): share rule
selection; eBay-only / BrokerBin-only / combo math on a fixture (HD223 numbers
above); EOL cap clips horizon and salvage; verdict tie-break prefers combo
within 10%; `--apply` writes the block and is idempotent; cache hit avoids a
network call. One live smoke test behind `BROKERBIN_LIVE=1` (skipped by
default) that asserts a 200 and a `meta.request.limit`.

## Out of scope (v0.1)

BrokerBin inventory upload (file process MTGI already runs; API v2 has no
inventory endpoints; RTI needs Premier); Firecrawl capture of Seller Hub;
eBay lot listings; a UI in mtgi-web-app; any change to publish.py gating.

## Rollout

Calibrate on the five SKUs already researched (ET91000SM20, C6800-16P10G,
828, HD223, 4K1042-WW): write their `market/*.json` from the screenshots on
file, run the check, sanity-check verdicts against the manual analysis of
2026-08-18, tune constants if a verdict is obviously wrong, then apply.
