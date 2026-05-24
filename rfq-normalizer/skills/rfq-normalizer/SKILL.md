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
3. **Cite every enriched value.** The provenance log must record where each filled-in value came from (regex, MTGI catalog, eBay, Brave, or user-confirmed).
4. **Ask, don't assume, when in doubt.** Ambiguous descriptions, conflicting data, multiple potential merges — surface them to the user.

## Workflow

Follow these steps in order. Update the user after each step with a one-line status.

### 0. Pre-flight: credentials check

**First, export the workspace path explicitly.** Autodetection covers most Cowork layouts, but exporting `RFQ_WORKSPACE_DIR` removes any ambiguity. If you can see the path of the current workspace folder (e.g. via the shell environment or the user's prompt), export it before any script call:

```bash
export RFQ_WORKSPACE_DIR=<absolute path to the persistent workspace folder>
```

This is the authoritative location for the chmod-600 credentials file and the enrichment cache. Skip this step if `RFQ_WORKSPACE_DIR` is already set.

Before parsing anything, run `python scripts/check_setup.py`. It exits non-zero only when **no** enrichment tier (eBay or Brave) is configured. If so, tell the user:

> The rfq-normalizer skill has no enrichment tier configured. Run `/rfq-setup` to add eBay Browse and/or Brave Search credentials, then re-run — otherwise only local regex/cache will run and most missing specs will land on the needs-review list.

The local tier (vendor columns + regex + cache) always works, so you *can* proceed unconfigured, but enrichment is what fills the core columns. The MTGI catalog tier is optional; eBay Browse is the primary structured spec source (BrokerBin was sunset in v0.8.0).

### 1. Parse the vendor file

Run `scripts/parse_vendor.py <input>`. The parser auto-detects the real header row (vendor sheets often have title/banner rows above it) and drops trailing TOTAL/summary footers so they never become bogus line items. It returns raw rows + column headers plus:
- `header_row_index` — the 1-based row the header was found on
- `skipped_banner_rows` — banner text discarded above the header
- `dropped_summary_rows` — aggregate/footer rows excluded (with their text)

Show the user:
- Row count
- Detected column headers (and `header_row_index` if banners were skipped)
- Any `dropped_summary_rows` (so a dropped TOTAL is visible, not silent)
- A 3-row preview

If header detection guessed wrong, re-run with `--header-row N` (1-based). Confirm with the user that this matches what they expected before proceeding.

### 1b. Analyze the sheet structure

Pipe the parse output into `scripts/analyze_columns.py`. This returns:
- Per-column fill rate + uniqueness signal
- **Warnings** — always-blank columns ("the 'Type' column is empty in 158/158 rows — drop or request fresh data?")
- **`suggested_consolidation_mode`** — `count` (one row per physical item) or `sum` (each row has its own Quantity)
- **`suggested_rfq_mode`** — `live` (no Bid Price / Outcome columns → for-bid sourcing list) or `historical` (already-bid record with outcomes)
- Detected role columns (serial, qty, bid_price, outcome)

**Surface the warnings to the operator** before proceeding. Especially for blank-column warnings — vendors often forget to fill required data.

### 1c. Settings form

After analyze surfaces its warnings, ask the operator a **single** settings card (one elicitation, not four separate prompts) covering:

| Setting | Default | Where the default comes from |
|---|---|---|
| Default Condition for the file | `used_good` | Detected from a `Grade`/`Condition`/`Health` column; ask explicitly if none is present. |
| Outcome Date source | `filename` if a date is parseable from the input filename, else `ask`. | Parse `YYYY-MM-DD` or `M-D-YYYY` patterns from the input filename. |
| Consolidation | **off** for `count`/`live` files (one row per physical unit, Quantity = 1); **on** only when `suggested_rfq_mode='historical'`. | step 1b output. |
| Enrichment scope | `full` | `free-only` (regex + cache only), `top-N` (cap API calls), or `full` (run all configured tiers). |

Present all four with sensible defaults pre-filled. After this single interaction, only ambiguous-merge prompts (step 3) and confirmations (vendor-SKU swaps in step 5) should require operator input.

### 2. Map vendor columns to MTGI fields

Read `reference/template-schema.md` for the canonical output columns. For each MTGI field, find the best matching vendor column using:
1. Exact header match (case-insensitive)
2. Common alias patterns (e.g., `Part Number`, `P/N`, `SKU` → MPN; a `Protocol` column feeds `Interface`)
3. If unmatched, ask the user

Show the user a mapping table and confirm before proceeding.

### 2b. Extract a clean MPN

The vendor "Model"/part column mixes brand words, marketing/family names, OEM spare numbers, and the real part number — e.g. `Savvio 10K.3 (ST9300603SS)`, `MM1000FBFVR 605832-002 (ST91000640SS)`. The MPN column must be the **manufacturer part number only**. Run `scripts/extract_mpn.py` (`extract_mpn(model)`) on the mapped MPN/Model column:

```python
from extract_mpn import extract_mpn
r = extract_mpn(row["MPN"])
# Always preserve the full original string for audit:
row["Description"] = f"{row.get('Description', '')} (vendor MPN: {r['original']})".strip()
row["MPN"] = r["mpn"]
if not r["is_real_mpn"]:
    # keep the cleaned best-effort string (MPN is required — never blank it),
    # send the row to enrichment to resolve the real MPN, and flag for review.
    row["_mpn_unresolved"] = True
```

It tokenizes the string, drops brand/family words, scores each token with `mpn_patterns.score_mpn`, and prefers a token matching a known **manufacturer** prefix (Seagate `ST…`) over generic OEM/spare numbers. When no token is a real MPN (e.g. `DC S3500 Series`), it returns a cleaned best-effort string with `is_real_mpn=False` — enrichment then tries to resolve it, and any `candidate_real_mpn` is surfaced (never auto-swapped — see step 5's vendor-SKU rule).

### 3. Consolidate duplicate rows (opt-in)

**Default: do NOT consolidate.** For `count`/`live` inventory files — where the "MPN" column is often a model-family name that repeats across capacities and prices — emit one normalized row per physical unit (Quantity = 1). Skip this step entirely unless consolidation was turned **on** in the settings card (historical bid records).

When consolidation *is* requested, run `scripts/consolidate_duplicates.py` with the `mode` and `rfq_mode` detected by `analyze_columns`:

- `mode='sum'` — each row already has a Quantity column; sum the values
- `mode='count'` — each row is one physical item; count rows per MPN
- `rfq_mode='live'` — group by (MPN, condition) only. For sourcing lists.
- `rfq_mode='historical'` — group by (MPN, condition, bid_price, winning_bid, outcome). **Never merges distinct bid events** — preserves pricing history.

**Conflict fallback (whole-file).** Before merging, the script checks a set of must-agree columns (`Bid Price`, `Capacity`, `Interface`, `Drive Type`, `Form Factor` by default — pass `must_agree_cols` to override). If *any* group disagrees on one of them, consolidation is unsafe: the script returns **all rows as single units** (Quantity = 1) with `fell_back_to_single_units: true` and a `conflicts` list. Report that to the operator rather than merging conflicting data.

`analyze_columns.py` emits `suggested_rfq_mode` and the relevant column names (`bid_price_column`, `outcome_column`); pass them through.

Returns:
- `consolidated[]` — one row per unique key (or single units when it fell back)
- `fell_back_to_single_units`, `conflicts[]` — see above
- `ambiguous_pairs[]` — MPNs differing only by case/whitespace
- `qty_in`, `qty_out` — total quantity in vs out (must match — script raises if not)

For every ambiguous pair, ask the user: "These look like the same part — should I merge them?" Show both raw strings. Never auto-merge.

### 4. Split descriptions into spec columns

Run `scripts/split_description.py` over each row, mining **all text columns** (the vendor's `Description`, `Size`, `Notes`, etc.), not just the primary description. Vendors frequently hide spec hints in the Size column (e.g., "1.2 TB 10K SAS", "7.68TB SSD NVMe"). Use `split_row(row, text_columns=[...])` from the script's API; pass the list of text columns the column-mapping step identified.

Each extracted value gets a `source: 'regex'` provenance entry. If the regex can't extract a field with high confidence, leave it blank and flag for enrichment.

### 4b. Normalize the condition column

If the vendor file expresses condition as a `Grade`, `Condition`, or `Health / Grade` column, run `scripts/normalize_condition.py` (`normalize_condition(raw)`). It is the single entry point covering all three forms vendors use:

- bare grade letters/numbers — `A+`, `B`, `3`
- grade words with a "grade" token — `B grade`, `Grade B`
- plain condition words — `Good`, `Refurb`, `Server Pull`

It strips the "grade" token, tries `normalize_grade`, then falls back to the condition-word map in `reference/condition-mapping.md`, returning the canonical enum or `None` (never guesses — leave blank when unknown). `scripts/normalize_grade.py` remains the letter-only helper it delegates to.

Many lot/refurb vendors use these conventions. The Evolution drive list mixed `B grade` and `Good`, both → `used_good`; the Brass Valley HDD list used `Grade=B` → `used_good`.

### 5. Enrich missing fields (tiered)

**Goal: every row has all applicable core columns filled or on the needs-review list.** Core columns are `MPN`, `Manufacturer`, `Condition`, and the storage specs `Capacity`, `Interface`, `Drive Type`, `Form Factor` (storage specs stay blank for non-storage parts). For each row with any missing core field, walk the cascade below, driving enrichment **per missing column**. **Pass `--current` with the fields the row already has** so the walk skips them and conserves calls.

| Tier | Source | Notes |
|------|--------|-------|
| 1 | **local** — vendor columns + regex (`split_description`) + cache | free; already fills most rows |
| 2 | **MTGI catalog lookup** (optional, see Setup) | only if configured |
| 3 | **eBay Browse API** | structured item aspects (capacity/interface/drive_type/form_factor/manufacturer/condition); consensus across active listings |
| 4 | **Brave web search** | MPN resolution + cross-ref / spec confirmation (`site:ebay.com "{MPN}"` and general) |
| 5 | **leave blank → needs-review** | never invent |

Run `scripts/enrich_mpn.py <mpn>` (or `--batch`) which orchestrates tiers 1–4. BrokerBin was **sunset in v0.8.0** — it is not in the cascade. Stop as soon as a field is confirmed.

The skill keeps a **persistent MPN cache** (workspace `.rfq-cache/`). Cache hits return instantly with no API call. TTL: 60 days for hits, 7 days for "no results" misses. Inspect/clear: `python scripts/cache.py {stats|clear|show MPN}`.

**Fill policy (reconciles with never-invent):**

- **Core spec fields** (capacity, interface, drive_type, form_factor, manufacturer): fill when consensus ≥ 0.60 with ≥2 corroborating listings. Between 0.60 and 0.89 the cell is tagged `tagged_low_confidence` in provenance with an `[unverified — {source} consensus N%]` note. Below 0.60 or no data → leave blank and it lands on the needs-review list.
- **Required fields** (MPN, Condition) and **MPN swaps**: never best-guessed — confirm with the operator or leave for review.

Provenance must cite the source tier (`ebay`, `web_search`, `mtgi_catalog`, …) for every enriched value.

**Vendor-SKU / unresolved-MPN detection.** `enrich_mpn.py` returns an `mpn_assessment` block (see `reference/mpn-patterns.md`). When the MPN doesn't match any known manufacturer prefix AND no tier found listings, `likely_vendor_sku: true` is set; when web search surfaces a `candidate_real_mpn`, it's attached. Surface it — never auto-swap:

> The MPN `PA33N3T8` doesn't match any known manufacturer prefix and no listings were found. Web search suggests the real manufacturer MPN may be `MZILS3T8HMLH` — use that, keep the vendor SKU, or pause this row for review?

After confirmation, re-run enrichment with the swapped MPN. Rows with an unresolved MPN go on the needs-review list (step 6) carrying any `candidate_real_mpn`.

### 5b. Canonicalize spec columns

Before writing the output, run each row's enriched specs through `scripts/canonicalize_specs.py`. The extraction and enrichment tiers produce *rich* internal spec values (e.g. `drive_type='U.2 SSD'`, `interface='PCIe x4 NVMe'`, `form_factor='M.2 2280'`) that power consensus voting — but the MTGI intake wizard only maps the **constrained canonical values** to typed columns. This step collapses them:

- `size` → **Capacity** (verbatim clean string, e.g. `1.92TB`)
- `interface` → **Interface** — one of `SATA` / `SAS` / `NVMe` (priority NVMe > SAS > SATA; other buses blank)
- `drive_type` → **Drive Type** — one of `SSD` / `HDD` (qualifiers stripped)
- `form_factor` → **Form Factor** — one of `2.5in` / `3.5in` / `M.2` / `U.2` / `PCIe` (U.2/M.2 derived from the drive-type signal)
- `manufacturer` → **Manufacturer** — canonical brand (via `manufacturer_aliases`), blank if unknown, **populated for every part type**

**Storage-domain gate:** when the row is a non-storage part (NIC, switch, HBA, RAID controller, RAM, CPU, GPU), the four storage spec columns are blanked automatically; `Manufacturer` is kept. The script carries provenance forward for all five columns — including a `normalized_from` note when a value was collapsed/derived, and a blank-reason note when the gate fired. Merge its `_provenance` into the row under the output headers so the provenance log covers the five typed columns.

Call it per row (internal keys + `_provenance` in, output headers out) or in bulk via stdin `{"rows":[...]}`. Pass-through columns (MPN, Quantity, …) are preserved. Any other vendor columns you emit are fine — the wizard captures them as `custom_fields`; do **not** rename them to the canonical headers.

### 6. Generate the output

Run `scripts/write_template.py`. This produces three files:
- `<input>-normalized.xlsx` — matches the MTGI template exactly (13 canonical columns + any preserved vendor extras)
- `<input>-provenance.json` — per-cell provenance log
- `<input>-needs-review.csv` — every row with a blank/low-confidence core column or an unresolved MPN: row #, MPN, Manufacturer, the missing/low-confidence fields, and any `candidate_real_mpn`

The script prints a one-line `summary`, e.g. *"12 of 1403 rows need review (9 with blank/low-confidence specs, 3 unresolved MPNs)."* Show the user:
- That summary plus N→M row counts and fields enriched
- The needs-review path (and a few example rows if the list is short)
- The output file path

A fully-enriched file yields an empty needs-review report and a "0 rows need review" summary.

### 7. Hand-off

Tell the user: "Upload `<input>-normalized.xlsx` to MTGI via /rfqs/new. The provenance log is at `<input>-provenance.json`, and `<input>-needs-review.csv` lists the rows still needing attention."

## Setup (one-time)

On a fresh install, run `/rfq-setup`. It writes credentials to a chmod-600 file at `<workspace>/.rfq-normalizer.env` (set `RFQ_WORKSPACE_DIR` or `RFQ_CREDS_FILE` to override). The workspace file is the only storage that survives a Cowork sandbox reset, so it is the primary persistence layer. On genuine local-Mac installs with a working OS keychain the keyring acts as an additional fallback when the file path isn't writable.

Power users and CI can override stored values with env vars:

```bash
# Optional: enables Tier 1 catalog lookup
MTGI_API_URL=https://your-mtgi-instance.example.com
MTGI_API_TOKEN=<token-from-MTGI-settings>

# Override the workspace file — wins when set
EBAY_APP_ID=<app-id>          # eBay Browse API application keyset
EBAY_CERT_ID=<cert-id>
BRAVE_SEARCH_API_KEY=<key>

# Optional path overrides
RFQ_WORKSPACE_DIR=/path/to/persistent/dir
RFQ_CREDS_FILE=/path/to/.rfq-normalizer.env
RFQ_CACHE_DIR=/path/to/.rfq-cache
```

Inspect what's configured with `python scripts/check_setup.py`. Manage stored credentials directly with `python scripts/credentials.py {status|get|set|delete|backend} ...`. The `backend` subcommand prints the active storage location (file path or keyring backend name).

## Files in this skill

- `reference/template-schema.md` — canonical output columns + accepted values
- `reference/description-patterns.md` — regex patterns for spec extraction
- `reference/outcome-mapping.md` — vendor outcome strings → MTGI enum
- `reference/condition-mapping.md` — vendor condition strings → MTGI enum
- `scripts/parse_vendor.py` — read xlsx/csv into rows; auto-detect header row, skip banners, drop TOTAL/summary footers (`--header-row N` override)
- `scripts/analyze_columns.py` — fill rates + row-per-item detection (serial signal weighted by fill rate) + live-vs-historical hint
- `scripts/consolidate_duplicates.py` — group by exact MPN; mode='sum' or mode='count'; must-agree conflict detection with whole-file fallback to single units
- `scripts/split_description.py` — description → spec columns (regex, free)
- `scripts/canonicalize_specs.py` — collapse rich internal specs → the 5 typed output columns; storage-domain gating + provenance
- `scripts/normalize_grade.py` — A/B/C/D grade letters → MTGI condition enum
- `scripts/normalize_condition.py` — single entry point for condition: grade letters, "B grade" suffixes, and condition words
- `scripts/extract_mpn.py` — pull the manufacturer part number out of a messy vendor Model string (prefers known-mfg prefixes; flags unresolved)
- `scripts/mpn_patterns.py` — score MPNs against known manufacturer prefixes (flags vendor SKUs)
- `scripts/manufacturer_aliases.py` — collapse HGST/Hitachi→WD, Compaq/HPE, etc. for clean consensus
- `scripts/enrich_mpn.py` — tiered enrichment cascade (MTGI → eBay → Brave) with pre-flight skip + persistent cache
- `scripts/ebay_browse_client.py` — eBay Browse API client (Tier 3 structured item aspects)
- `scripts/brave_client.py` — Brave Search API v1 client (Tier 4 web search)
- `scripts/brokerbin_client.py` — **deprecated (v0.8.0)** BrokerBin client, kept dormant (not wired into enrichment)
- `scripts/credentials.py` — per-user credential store; chmod-600 workspace file with env-var and keyring fallbacks
- `scripts/workspace.py` — workspace-folder detection for persistent storage
- `scripts/cache.py` — persistent MPN cache (60-day TTL); CLI for stats/clear/show
- `scripts/write_template.py` — emit normalized xlsx + provenance + needs-review report
- `scripts/check_setup.py` — report credential + tier configuration
- `prompts/extract-specs.md` — LLM fallback for descriptions regex can't parse
- `prompts/review-merge.md` — phrasing for "should I merge these?" prompts
- `examples/` — sample input/output pairs
