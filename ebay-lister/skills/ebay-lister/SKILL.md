---
name: ebay-lister
description: Build and publish an eBay listing through conversation. Use when the user wants to post something to the MTGI eBay store, list a product, create or revise a listing, stage product photos for eBay, or inspect/create/edit the eBay business policies and inventory locations a listing depends on.
---

Build an eBay listing by talking it through, then publish it. You are the
controller: the Python scripts are thin API wrappers, and every judgement call
— title wording, category choice, aspect values, condition phrasing — is
yours to draft and the operator's to approve.

**Never publish without explicit confirmation.** A published listing is public
and costs money to unwind.

## Scripts

All paths below are relative to `${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/`.
Run them with `python3`. They import each other, so always invoke by full path
and let Python put the scripts directory on `sys.path`.

| Script | Purpose |
|---|---|
| `check_setup.py` | Pre-flight. Run FIRST, every session. |
| `r2_upload.py` | `scan` a photo folder, `stage` one group to R2. |
| `ebay_api.py` | Category suggestions, required aspects, policies, locations. |
| `publish.py` | `validate` / `dry-run` / `publish` a listing spec. |
| `sales_history.py` | MTGI's own realized economics — what cleared, net of fees and labels. |
| `auth.py` | OAuth. Only `/ebay-setup` should need it. |

## Workflow

### 0. Pre-flight — always

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/check_setup.py" --json
```

- Any `fail` on credentials or token → stop, route to `/ebay-setup`.
- A `fail` on a policy or location → do NOT route to setup. Offer to create it
  now (see **Account prerequisites** below), then re-run pre-flight.
- Warnings are informational. Mention refresh-token expiry only if under 30 days.

### 1. Find the photos

Photos live in a flat folder — for MTGI that is
`~/Documents/01_Clients/mtgi/work/product-images/`. Ask if you don't know it.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/r2_upload.py" scan <folder>
```

Filenames follow `<product-slug>-<unit>-<image#>.<ext>`, so
`corsair-64gb-ram-01-1.png` belongs to group `corsair-64gb-ram-01`, image 1.

**One group is one physical unit and therefore one listing.** Three groups of
the same product means three separate listings, not one listing with quantity 3
— unless the operator says they are identical and wants a single multi-quantity
listing. Ask when there is more than one group.

Report `skipped` files and any per-file `warnings` (oversized, or a format eBay
rejects for self-hosted images). Do not proceed with a group that has warnings.

### 1b. Price from realized data, not asking prices

Before proposing a price, check what MTGI has actually cleared:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/sales_history.py" summary
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/sales_history.py" shipping
```

`summary` gives net-per-unit after fees and labels for anything MTGI has sold
before. `shipping` gives the real label-cost profile — use the **mode**, not the
mean, since one oversized shipment drags the mean badly.

**Asking prices are not evidence.** On slow-moving enterprise gear, active
listings routinely sit 3-4x above anything that has ever sold, with zero
watchers. Market-wide sold data comes from Seller Hub -> Research -> Product
Research (free, 3 years, includes accepted Best Offer prices); eBay's
Marketplace Insights API returns 403 for this app and public sold-search
scraping is walled off. If the operator has not pulled Product Research for the
part, say so and price conservatively rather than anchoring on active asks.

### 1c. Marketplace check — eBay, BrokerBin, or both

Before drafting, decide where the units should sell. This is scripted advice,
not a gate.

1. Ask the operator for two Seller Hub screenshots: Research → Product
   Research → **Sold** and **Active** for the MPN, category **All Categories**,
   window 3 years (slow enterprise gear) or 6 months (fast movers).
2. **You filter, never the operator**: keep only exact-SKU rows, drop
   variants/accessories/unrelated hits, unit-weight the counts, compute
   all-in prices, and write `01_Clients/mtgi/work/ebay/market/<MPN>.json`
   (schema and rules in `reference/market-json.md`). Show the exclusions in
   one line so the operator can sanity-check.
3. Run the check (BrokerBin is fetched live and cached; ~3 calls per MPN of a
   50/day quota):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/channel_check.py" <SKU-or-MPN>
```

4. Present the table as printed: eBay-only / BrokerBin-only / combo net at 3
   and 6 months, the unbounded footnote, the verdict and its one-line
   rationale, and the flags. Say which assumptions drove it
   (`reference/channel-rules.md`).
5. The operator decides. Record it with `--apply` (writes a `channel` block
   into the draft). If the verdict is `brokerbin` or `combo`, tell the operator
   what to change on MTGI's BrokerBin line (price/qty) — BrokerBin upload is
   MTGI's existing file process, not this skill — and note that eBay sales
   must be mirrored to BrokerBin qty.

If `market/<MPN>.json` does not exist the script says so and exits cleanly;
do not guess figures. If BrokerBin is unreachable it prints why and runs the
eBay-only side.

### 2. Gather the listing facts

Ask for whatever the operator hasn't already given. Required:

- **What it is** — enough detail to resolve a category and write a title
- **Condition** — `new`, `used_good`, `for_parts`, etc. (see `reference/conditions.md`)
- **Price** and **quantity**
- **MPN** and **brand** where known

**MPN strings are preserved verbatim** — exact case and hyphens. `WDC-SN850` is
not `WDC SN850`. Never normalize, never guess one.

### 3. Resolve the category

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/ebay_api.py" suggest-category "<product description>"
```

Present the top suggestions with their full paths and recommend one. Let the
operator override. Never hardcode a category ID — eBay reorganizes them, and
required aspects are per-category.

### 4. Fill the required aspects

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/ebay_api.py" aspects <categoryId>
```

Every entry under `required` must have a value or publish fails. Fill what you
can infer from the operator's description and the MPN; **ask for the rest
rather than inventing values**. When an aspect has a constrained value list,
choose from it exactly — free text is rejected.

### 5. Draft the listing

Write and show the operator:

- **Title** — 80 chars max, hard limit. Lead with the specifics buyers search:
  brand, model, capacity/spec, form factor, condition. No ALL CAPS, no filler
  like "L@@K" or "WOW".
- **Description** — plain, factual, what's included, tested state, cosmetic
  condition. No invented claims about testing you weren't told about.
- **Listing body (`listingDescription`)** — the same facts in MTGI's HTML house
  template, `reference/description-template.md`. Every live listing uses it;
  do not freestyle the layout.
- **Item specifics** — the aspects from step 4.
- **Condition description** — the honest specifics for a used item.

Show it as a compact block and invite edits before anything is uploaded.

### 6. Stage the images

Only after the operator approves the draft. Pick a SKU first — the convention is
`MTGI-<MPN-or-slug>-<unit>`, MPN verbatim.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/r2_upload.py" stage <folder> --group <group> --sku <sku>
```

This uploads to Cloudflare R2 and verifies each public URL with a HEAD request.
If `verified` is false, **stop** — eBay fetches these server-side, so a failed
check means the listing would go live with broken images.

Image 1 becomes the eBay gallery photo. Order is load-bearing.

### 7. Dry-run, then publish

Write the spec to a temp JSON file (fields in `reference/spec.md`), then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/publish.py" dry-run /tmp/<sku>.json
```

Show the operator the resolved payloads and any problems. Fix problems, re-run.

Then ask for explicit confirmation — quote the title, price, quantity, and
category back. Only on a clear yes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/publish.py" publish /tmp/<sku>.json
```

Report the `listingUrl`. Surface any `warnings` from eBay verbatim — they often
flag policy or aspect issues that will affect visibility.

`publish` is idempotent by SKU: an already-published offer is returned rather
than duplicated, so a retry after a network failure is safe.

## Account prerequisites

`publishOffer` fails without an enabled inventory location and all three
business policies. When pre-flight flags one missing, offer to create it in
conversation rather than sending the operator elsewhere.

Inspect what exists:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/ebay_api.py" policies
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/ebay_api.py" locations
```

Create or edit — see `reference/account-setup.md` for payload shapes:

```bash
python3 ".../ebay_api.py" create-policy fulfillment '<json>'
python3 ".../ebay_api.py" edit-policy   fulfillment <policyId> '<json>'
python3 ".../ebay_api.py" create-location <key> '<json>'
```

`edit-policy` is a **full replace**, not a patch. Read the existing policy
first, merge the change into the complete object, and send the whole thing —
otherwise unmentioned fields are wiped.

Always show a policy or location payload to the operator before creating it.
These are account-level settings that affect every listing, not just this one.

## Invariants

- **Never publish without explicit confirmation.**
- **Never invent** an MPN, a spec, a test result, or an aspect value. Ask.
- **MPN verbatim** — exact case and hyphens, always.
- **One image group = one listing** unless the operator says otherwise.
- **Stop on failed image verification.** Broken images beat no listing.
- **Titles are capped at 80 characters.** Count them.
- Policy and location writes are account-wide. Confirm before writing.

## Recovering from a failed publish

eBay returns detailed errors. Common ones:

| Error | Cause | Fix |
|---|---|---|
| Missing required aspect | Step 4 incomplete | Re-run `aspects`, fill, re-publish |
| A mixture of Self Hosted and EPS pictures | Some images came from elsewhere | Use only R2-staged URLs for the whole listing |
| Invalid merchantLocationKey | Location missing or disabled | `locations`, then create/enable |
| Listing policies not found | Policy ID wrong or deleted | `policies`, re-select |

The offer survives a failed publish. Fix the spec and re-run `publish` — it
reuses the existing offer rather than creating a second one.
