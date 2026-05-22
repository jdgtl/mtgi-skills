---
name: rfq-normalizer
description: Use when an MTGI team member uploads a vendor RFQ spreadsheet that needs to be cleaned up before importing into MTGI. Normalizes any vendor format (xlsx/csv) into the canonical MTGI historical-import template — splits free-text descriptions into structured spec columns, consolidates duplicate MPN rows, and enriches missing fields via API/web lookups. Outputs a template-ready xlsx plus a provenance log showing where every value came from. Never hallucinates values; surfaces ambiguous data for the user to confirm.
---

# RFQ Normalizer

You help the MTGI team turn messy vendor RFQ spreadsheets into the canonical MTGI historical-import template. The team imports these files into their MTGI app, which expects a specific column layout. Vendors send all kinds of formats; your job is to bridge that gap.

## When to invoke

The user uploads a spreadsheet (xlsx or csv) and asks you to clean it up for MTGI import, normalize it, prep it for upload, or anything similar.

## Hard rules (no exceptions)

1. **Never invent values.** If a field is missing and you can't find it in the source data or via an enrichment lookup, leave it blank — never guess.
2. **Exact MPN matches only when consolidating rows.** "WDC SN850" and "WDC-SN850" are NOT the same. If MPN strings differ by even a space or case, treat as separate lines and ask the user.
3. **Cite every enriched value.** The provenance log must record where each filled-in value came from (regex, MTGI catalog, BrokerBin, or user-confirmed).
4. **Ask, don't assume, when in doubt.** Ambiguous descriptions, conflicting data, multiple potential merges — surface them to the user.

## Workflow

Follow these steps in order. Update the user after each step with a one-line status.

### 0. Pre-flight: credentials check

Before parsing anything, run `python scripts/check_setup.py`. If BrokerBin credentials are missing (exit code 1), stop and tell the user:

> The rfq-normalizer skill isn't set up yet. Run `/rfq-setup` to configure BrokerBin credentials, then re-run this skill.

Do not proceed with normalization on an unconfigured plugin — BrokerBin enrichment is the difference between a useful normalized file and a sheet full of blanks. If the MTGI catalog tier is unconfigured but BrokerBin is set up, that's fine; continue (Tier 1 is optional).

### 1. Parse the vendor file

Run `scripts/parse_vendor.py <input>`. This returns raw rows + column headers. Show the user:
- Row count
- Detected column headers
- A 3-row preview

Confirm with the user that this matches what they expected before proceeding.

### 1b. Analyze the sheet structure

Pipe the parse output into `scripts/analyze_columns.py`. This returns:
- Per-column fill rate + uniqueness signal
- **Warnings** — always-blank columns ("the 'Type' column is empty in 158/158 rows — drop or request fresh data?")
- **`suggested_consolidation_mode`** — `count` (one row per physical item) or `sum` (each row has its own Quantity)
- **`suggested_rfq_mode`** — `live` (no Bid Price / Outcome columns → for-bid sourcing list) or `historical` (already-bid record with outcomes)
- Detected role columns (serial, qty, bid_price, outcome)

**Surface the warnings to the operator** before proceeding. Especially for blank-column warnings — vendors often forget to fill required data.

### 2. Map vendor columns to MTGI fields

Read `reference/template-schema.md` for the canonical output columns. For each MTGI field, find the best matching vendor column using:
1. Exact header match (case-insensitive)
2. Common alias patterns (e.g., `Part Number`, `P/N`, `SKU` → MPN)
3. If unmatched, ask the user

Show the user a mapping table and confirm before proceeding.

### 3. Consolidate duplicate rows

Run `scripts/consolidate_duplicates.py` with the `mode` and `rfq_mode` detected by `analyze_columns`:

- `mode='sum'` (default) — each row already has a Quantity column; sum the values
- `mode='count'` — each row is one physical item; count rows per MPN

And, critically, pass `rfq_mode`:

- `rfq_mode='live'` — group by (MPN, condition) only. For sourcing lists.
- `rfq_mode='historical'` — group by (MPN, condition, bid_price, winning_bid, outcome). **Never merges distinct bid events** — preserves pricing history.

`analyze_columns.py` already emits `suggested_rfq_mode` and the relevant column names (`bid_price_column`, `outcome_column`); pass them through.

Returns:
- `consolidated[]` — one row per unique key
- `ambiguous_pairs[]` — MPNs differing only by case/whitespace
- `qty_in`, `qty_out` — total quantity in vs out (must match — script raises if not)

For every ambiguous pair, ask the user: "These look like the same part — should I merge them?" Show both raw strings. Never auto-merge.

### 4. Split descriptions into spec columns

Run `scripts/split_description.py` over each row, mining **all text columns** (the vendor's `Description`, `Size`, `Notes`, etc.), not just the primary description. Vendors frequently hide spec hints in the Size column (e.g., "1.2 TB 10K SAS", "7.68TB SSD NVMe"). Use `split_row(row, text_columns=[...])` from the script's API; pass the list of text columns the column-mapping step identified.

Each extracted value gets a `source: 'regex'` provenance entry. If the regex can't extract a field with high confidence, leave it blank and flag for enrichment.

### 4b. Convert grade letters to MTGI conditions

If the vendor file has a `Grade` column with single letters (A+, A, B+, B, C, D, F) instead of a `Condition` column, run `scripts/normalize_grade.py`. See `reference/condition-mapping.md` for the mapping.

Many lot/refurb vendors use this convention. The Brass Valley HDD list is a typical example: every row has `Grade=B` which maps to `used_good`.

### 5. Enrich missing fields (tiered)

For every row with any missing field, walk this cascade. **Pass `--current` with the fields the row already has filled** so the tier walk skips them entirely — every saved API call counts against the 50/day BrokerBin quota.

**Pass `--vendor-mfg` with the manufacturer name from the vendor file** (e.g. `--vendor-mfg "Hitachi"`). When BrokerBin's modal manufacturer (after alias normalization — see `reference/manufacturer-aliases.md`) matches the vendor-supplied name, confidence is boosted to 0.93 (corroborated by two independent sources). Without this, listings that split between "HGST" and "Hitachi" or "Compaq" and "HPE" will be flagged as low-confidence even when they actually agree.

The skill also keeps a **persistent MPN cache** at `.cache/brokerbin-enrichment.json`. Cache hits return instantly with no API call. Cache TTL: 60 days for successful enrichment, 7 days for "no listings" misses. To inspect or clear: `python scripts/cache.py {stats|clear|show MPN}`.

Stop as soon as a tier fills the gaps with high confidence (≥0.90).

**Low-confidence descriptions are filled with an annotation.** When BrokerBin's seller-authored descriptions don't reach high consensus (modal description present in <90% of listings), the modal description is still written to the output with `[unverified — brokerbin consensus 59%]` appended. The provenance entry has `tagged_low_confidence: true`. The operator can edit or accept; a blank cell wouldn't have been more useful.

**Vendor-SKU detection.** After the tier walk, `enrich_mpn.py` returns an `mpn_assessment` block with a pattern score (see `reference/mpn-patterns.md`). When the MPN doesn't match any known manufacturer prefix AND no tier found listings, `likely_vendor_sku: true` is set. When web search also returns a `candidate_real_mpn`, that token is attached to the assessment so you can offer it explicitly. Surface this to the operator:

> The MPN `PA33N3T8` doesn't match any known manufacturer prefix and BrokerBin returned no listings. Web search suggests the real manufacturer MPN may be `MZILS3T8HMLH` — should I use that as the MPN, keep the vendor SKU, or pause this row for manual review?

If no `candidate_real_mpn` is present, fall back to the original phrasing (no suggestion, just the SKU flag). Never auto-swap the MPN — always confirm with the operator. After confirmation, re-run enrichment with the swapped MPN as the input.

| Tier | Source | Confidence | Cost |
|------|--------|-----------|------|
| 1 | **MTGI catalog lookup** (optional, see Setup) | high | free |
| 2 | **BrokerBin API** | high | $$ |
| 3 | **Brave web search** — catches vendor SKUs and OEM cross-refs BrokerBin misses | medium | free tier 2000/mo |
| 4 | **Ask the user** | n/a | n/a |

Run `scripts/enrich_mpn.py <mpn>` which orchestrates this. Each tier returns `{value, source, confidence, raw_response}`.

**Critical:** if confidence < 0.9 for any field, do NOT auto-fill. Surface to user with: "I found X via Y with Z% confidence — accept?"

### 6. Generate the output

Run `scripts/write_template.py`. This produces two files:
- `<input>-normalized.xlsx` — matches the MTGI template exactly
- `<input>-provenance.json` — per-cell provenance log

Show the user:
- Summary: N rows consolidated to M rows, P fields enriched
- A small table of any rows still missing required fields
- The output file path

### 7. Hand-off

Tell the user: "Upload `<input>-normalized.xlsx` to MTGI via /rfqs/new. The provenance log is at `<input>-provenance.json` if you need to audit any value."

## Setup (one-time)

On a fresh install, run `/rfq-setup`. It installs the `keyring` Python package, then walks you through entering BrokerBin credentials and stores them in the OS-native secure store (macOS Keychain / Windows Credential Manager / Linux Secret Service). They persist across Claude restarts and machine reboots.

Power users and CI can override stored values with env vars:

```bash
# Optional: enables Tier 1 catalog lookup
MTGI_API_URL=https://your-mtgi-instance.example.com
MTGI_API_TOKEN=<token-from-MTGI-settings>

# Override keyring — wins when set
BROKERBIN_API_KEY=<key>
BROKERBIN_LOGIN=<username>
BRAVE_SEARCH_API_KEY=<key>
```

Inspect what's configured with `python scripts/check_setup.py`. Manage stored credentials directly with `python scripts/credentials.py {status|get|set|delete|backend} ...`.

## Files in this skill

- `reference/template-schema.md` — canonical output columns + accepted values
- `reference/description-patterns.md` — regex patterns for spec extraction
- `reference/outcome-mapping.md` — vendor outcome strings → MTGI enum
- `reference/condition-mapping.md` — vendor condition strings → MTGI enum
- `scripts/parse_vendor.py` — read xlsx/csv into rows
- `scripts/analyze_columns.py` — fill rates + row-per-item detection + live-vs-historical hint
- `scripts/consolidate_duplicates.py` — group by exact MPN; mode='sum' or mode='count'
- `scripts/split_description.py` — description → spec columns (regex, free)
- `scripts/normalize_grade.py` — A/B/C/D grade letters → MTGI condition enum
- `scripts/mpn_patterns.py` — score MPNs against known manufacturer prefixes (flags vendor SKUs)
- `scripts/manufacturer_aliases.py` — collapse HGST/Hitachi, Compaq/HPE, etc. for clean consensus
- `scripts/enrich_mpn.py` — tiered enrichment cascade with pre-flight skip + persistent cache
- `scripts/brokerbin_client.py` — BrokerBin API v2 client (Bearer auth, rate-limited)
- `scripts/brave_client.py` — Brave Search API v1 client (Tier 3 web search)
- `scripts/credentials.py` — per-user credential store via the `keyring` library
- `scripts/cache.py` — persistent MPN cache (60-day TTL); CLI for stats/clear/show
- `scripts/write_template.py` — emit normalized xlsx + provenance
- `scripts/check_setup.py` — report credential + tier configuration
- `prompts/extract-specs.md` — LLM fallback for descriptions regex can't parse
- `prompts/review-merge.md` — phrasing for "should I merge these?" prompts
- `examples/` — sample input/output pairs
