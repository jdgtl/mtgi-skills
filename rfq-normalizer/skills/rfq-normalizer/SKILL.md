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
3. **Cite every enriched value.** The provenance log must record where each filled-in value came from (decoder, regex/text, Brave web search, or user-confirmed).
4. **Ask, don't assume, when in doubt.** Ambiguous descriptions, conflicting data, multiple potential merges — surface them to the user.

## Workflow

Follow these steps in order. Update the user after each step with a one-line status.

### 0. Pre-flight: credentials check

**First, export the workspace path explicitly.** Autodetection covers most Cowork layouts, but exporting `RFQ_WORKSPACE_DIR` removes any ambiguity. If you can see the path of the current workspace folder (e.g. via the shell environment or the user's prompt), export it before any script call:

```bash
export RFQ_WORKSPACE_DIR=<absolute path to the persistent workspace folder>
```

This is the authoritative location for the chmod-600 credentials file and the enrichment cache. Skip this step if `RFQ_WORKSPACE_DIR` is already set.

Before parsing anything, run `python scripts/check_setup.py`. Enrichment is **decoder-first and works fully offline**, so credentials are optional — `check_setup` exits non-zero only as a soft nudge when Brave (the web fallback) isn't configured:

> Brave isn't configured. The decoder engine still resolves most drives offline, but rows it can't decode won't use the web fallback and will land on the needs-review list. Run `/rfq-setup` to add a Brave key.

You can proceed regardless. eBay and BrokerBin are no longer used (the decoder engine replaced them).

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
| Enrichment scope | `full` | `offline` (decoders + cache only, no network), or `full` (decoders + Brave fallback for rows decoders can't resolve). |

Present all four with sensible defaults pre-filled. After this single interaction, only ambiguous-merge prompts (step 3) and confirmations (vendor-SKU swaps in step 5) should require operator input.

### 2. Map vendor columns to MTGI fields

Read `reference/template-schema.md` for the canonical output columns. For each MTGI field, find the best matching vendor column using:
1. Exact header match (case-insensitive)
2. Common alias patterns (e.g., `Part Number`, `P/N`, `SKU` → MPN; a `Protocol` column feeds `Interface`)
3. If unmatched, ask the user

Show the user a mapping table and confirm before proceeding.

### 2b. Clean MPN (via the engine's extractor)

The vendor "Model"/part column mixes brand words, marketing/family names, OEM spare numbers, and the real part number — e.g. `Savvio 10K.3 (ST9300603SS)`, `MM1000FBFVR 605832-002 (ST91000640SS)`. The MPN column must be the **manufacturer part number only**. The enrichment engine's extractor (`extract_mpns`) finds it — parenthetical MPNs win, manufacturer-prefix matches preferred — and `enrich_row` (step 5) returns the chosen MPN as `_mpn`. Set the MPN column from that, always preserving the original:

```python
from enrich_engine import extract_mpns
mpns = extract_mpns(brand, row["Model"])
row["Description"] = f"{row.get('Description','')} (vendor MPN: {row['Model']})".strip()
if mpns:
    row["MPN"] = mpns[0][1]            # e.g. ST91000640SS from "MM1000FBFVR … (ST91000640SS)"
else:
    row["MPN"] = row["Model"].strip()  # required column — keep the cleaned string, never blank
    row["_mpn_unresolved"] = True       # → needs-review; enrichment may surface a candidate
```

Never auto-swap to an enrichment-suggested MPN — surface it for confirmation (see the vendor-SKU rule in step 5).

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

### 4. Build the `known` dict from existing cells

Enrichment fills **blanks only** — values the vendor already supplied always win. Before enriching, gather whatever spec cells the row already has into a `known` dict keyed by contract names:

```python
known = {}
if row.get("Interface"): known["interface"] = row["Interface"]
if row.get("Capacity"):  known["capacity"]  = row["Capacity"]
# ...drive_type, form_factor, speed likewise, from the mapped columns
```

`scripts/split_description.py` is still available to mine free-text columns (`Notes`, a combined `Size` column) for hints when there's no dedicated spec column — feed anything it confidently extracts into `known` too.

### 4b. Normalize the condition column

If the vendor file expresses condition as a `Grade`, `Condition`, or `Health / Grade` column, run `scripts/normalize_condition.py` (`normalize_condition(raw)`). It is the single entry point covering all three forms vendors use:

- bare grade letters/numbers — `A+`, `B`, `3`
- grade words with a "grade" token — `B grade`, `Grade B`
- plain condition words — `Good`, `Refurb`, `Server Pull`

It strips the "grade" token, tries `normalize_grade`, then falls back to the condition-word map in `reference/condition-mapping.md`, returning the canonical enum or `None` (never guesses — leave blank when unknown). `scripts/normalize_grade.py` remains the letter-only helper it delegates to.

Many lot/refurb vendors use these conventions. The Evolution drive list mixed `B grade` and `Good`, both → `used_good`; the Brass Valley HDD list used `Grade=B` → `used_good`.

### 5. Enrich missing fields (tiered)

**Goal: every row has all applicable core columns filled or on the needs-review list.** Core columns are `MPN`, `Manufacturer`, `Condition`, and the storage specs `Capacity`, `Interface`, `Drive Type`, `Form Factor` (storage specs stay blank for non-storage parts).

Enrichment is **decoder-first** via `scripts/enrich_engine.py`. Call `enrich_row(brand, model, known)` per row:

```python
from enrich_engine import enrich_row
r = enrich_row(row.get("Brand",""), row.get("Model",""), known=known)
# r → capacity, drive_type, interface, form_factor, speed, _mpn, _source, _confidence, _flags
```

Pipeline inside `enrich_row` (load-bearing order, validated on ~660 rows):

| Step | Source | Notes |
|------|--------|-------|
| 1 | `capacity_from_text` | capacity from the model string — decoder/text only |
| 2 | `looks_ssd` | tentative drive type |
| 3 | vendor **decoders** (Seagate/WD/Toshiba/HGST/Hitachi/HP-OEM) | free, offline, deterministic — resolves most enterprise drives |
| 4 | ICEcat (optional) | only if gaps remain and `ICECAT_TOKEN` set |
| 5 | **Brave web search** | type/interface/form ONLY for still-gapped rows — **never capacity** |
| 6 | `known` folded LAST | uploaded values win; decoder-vs-known disagreement → `_flags`, not a correction |

`_confidence` = HIGH (4 core fields) / MED (2–3) / LOW (1) / NONE (0).

**Hard rules (do not "improve" away):**
- **Capacity comes only from a decoder or the text — never from a web family/series match.** (The one narrow exception: Brave may set capacity tagged-low-confidence *only* when the exact MPN string appears with a single consistent capacity across ≥2 results.)
- **Fill blanks only.** On a decoder-vs-`known` conflict, keep `known` and record a `_flags` note.
- **Nonstandard/OEM-relabeled MPN → LOW + `NONSTANDARD_MPN` flag, never a guess.**

**Self-building cross-ref cache.** Brave results are written back to the workspace cache keyed by the cleaned **SKU** (not the raw `brand model` blob), so a repeat SKU in any format is a free cache hit on later rows/files/runs. Only confident (unanimous ≥2) results persist durably (60-day TTL); misses get a short 7-day TTL so they re-verify. Inspect/clear: `python scripts/cache.py {stats|show SKU|clear --sku SKU}`.

**Vendor-SKU / unresolved-MPN.** When `extract_mpns` finds no manufacturer MPN (e.g. `DC S3500 Series`, `PA33N3T8`), `enrich_row` flags `NONSTANDARD_MPN` and the row goes to needs-review. If a confident candidate MPN turns up, surface it — never auto-swap:

> `PA33N3T8` isn't a standard manufacturer MPN. A web cross-ref suggests `MZILS3T8HMLH` — use that, keep the vendor SKU, or pause this row for review?

### 5b. Canonicalize spec columns

Feed the engine's output into `scripts/canonicalize_specs.py` (map `enrich_row`'s `capacity/drive_type/interface/form_factor/manufacturer` → the canonicalizer's `size/interface/drive_type/form_factor/manufacturer` input keys). It collapses values to the constrained MTGI enums and **bridges the engine's formats**:

- `capacity` `"300 GB"`/`"1 TB"` → `Capacity` `"300GB"`/`"1TB"` (space stripped)
- `drive_type` `HDD`/`SSD` pass through; `SSHD` → `HDD` (provenance `normalized_from`)
- `interface` `SATA`/`SAS`/`NVMe` pass through
- `form_factor` `2.5"`/`3.5"`/`M.2` → `2.5in`/`3.5in`/`M.2`; `1.8"` isn't in the MTGI enum → **blank + needs-review**
- `speed` has no canonical column → emit as an extra passthrough column `Speed` (the writer preserves extras; the wizard captures it as a custom field)

Carry the engine's `_flags` (`KNOWN_CONFLICT`, `CAP_CONFLICT`, `NONSTANDARD_MPN`, `CAP_FROM_SEARCH_LOWCONF`) into provenance and the needs-review list.

The canonical mapping itself:

- `size` → **Capacity** (verbatim clean string, e.g. `1.92TB`)
- `interface` → **Interface** — one of `SATA` / `SAS` / `NVMe` (priority NVMe > SAS > SATA; other buses blank)
- `drive_type` → **Drive Type** — one of `SSD` / `HDD` (qualifiers stripped)
- `form_factor` → **Form Factor** — one of `2.5in` / `3.5in` / `M.2` / `U.2` / `PCIe` (U.2/M.2 derived from the drive-type signal)
- `manufacturer` → **Manufacturer** — canonical brand (via `manufacturer_aliases`), blank if unknown, **populated for every part type**

**Storage-domain gate:** when the row is a non-storage part (NIC, switch, HBA, RAID controller, RAM, CPU, GPU), the four storage spec columns are blanked automatically; `Manufacturer` is kept. The script carries provenance forward for all five columns — including a `normalized_from` note when a value was collapsed/derived, and a blank-reason note when the gate fired. Merge its `_provenance` into the row under the output headers so the provenance log covers the five typed columns.

Call it per row (internal keys + `_provenance` in, output headers out) or in bulk via stdin `{"rows":[...]}`. Pass-through columns (MPN, Quantity, …) are preserved. Any other vendor columns you emit are fine — the wizard captures them as `custom_fields`; do **not** rename them to the canonical headers.

### 5c. Compose a fallback Description (optional)

If a row has no human-written vendor description, run `scripts/compose_description.py` (`fill_description(row)`) to build one from the confirmed canonical fields — e.g. `Western Digital 6TB HDD SATA 3.5in`. Rules it enforces (so this stays inside never-invent):

- **Fill-blank-only.** A real vendor description is never overwritten; only composed when the human text is empty.
- **Audit tag preserved.** The `(vendor MPN: …)` suffix from step 2b is split off and re-appended, so a composed row reads `… specs … (vendor MPN: …)`.
- **Needs ≥2 confirmed fields**, drawn only from already-resolved/cited columns (Manufacturer, Capacity, Drive Type, Interface, Form Factor; Speed appended as `N RPM` when present). Fewer than 2 → left blank.
- Composed values are tagged `source: composed` in provenance, distinct from sourced spec values.

This is a fallback for human readability — the MTGI wizard maps the five typed columns directly, so Description isn't the primary spec carrier.

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
# Web fallback (optional — decoders run offline without it)
BRAVE_SEARCH_API_KEY=<key>    # the engine also accepts BRAVE_API_KEY
ICECAT_TOKEN=<token>          # optional; rarely useful on enterprise drives

# Optional path overrides
RFQ_WORKSPACE_DIR=/path/to/persistent/dir
RFQ_CREDS_FILE=/path/to/.rfq-normalizer.env
RFQ_CACHE_DIR=/path/to/.rfq-cache    # also where the engine's mpn_cache.json lives
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
- `scripts/enrich_engine.py` — **decoder-first enrichment engine**: `enrich_row(brand, model, known)` + part-number decoders, Brave fallback, self-building SKU cache
- `scripts/split_description.py` — description → spec hints (regex, free); supplements `known`
- `scripts/canonicalize_specs.py` — collapse engine specs → the 5 typed output columns; format bridging + storage-domain gating + provenance
- `scripts/compose_description.py` — fallback Description from confirmed specs (fill-blank-only; preserves vendor text + audit tag)
- `scripts/normalize_grade.py` — A/B/C/D grade letters → MTGI condition enum
- `scripts/normalize_condition.py` — single entry point for condition: grade letters, "B grade" suffixes, and condition words
- `scripts/mpn_patterns.py` — score MPNs against known manufacturer prefixes; `strip_brand_prefix`
- `scripts/manufacturer_aliases.py` — collapse HGST/Hitachi→WD, Compaq/HPE, etc. before consensus voting
- `scripts/brave_client.py` — Brave Search API client; used by `/rfq-setup` to smoke-test the key
- `scripts/brokerbin_client.py` — **deprecated/dormant** (BrokerBin sunset; not wired into enrichment)
- `scripts/credentials.py` — per-user credential store; chmod-600 workspace file with env-var and keyring fallbacks
- `scripts/workspace.py` — workspace-folder detection for persistent storage
- `scripts/cache.py` — inspect/clear the shared engine cache (`mpn_cache.json`): `{stats|show SKU|clear --sku SKU}`
- `scripts/write_template.py` — emit normalized xlsx + provenance + needs-review report
- `scripts/check_setup.py` — report credential + tier configuration
- `prompts/extract-specs.md` — LLM fallback for descriptions regex can't parse
- `prompts/review-merge.md` — phrasing for "should I merge these?" prompts
- `examples/` — sample input/output pairs
