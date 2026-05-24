# Changelog

All notable changes to plugins in the `mtgi-skills` marketplace are recorded here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); plugins
are versioned independently and each entry notes which plugin it applies to.

## rfq-normalizer

### 0.9.0 — 2026-05-23

Decoder-first enrichment. **Supersedes 0.8.0's eBay approach** — both eBay Browse
and BrokerBin are dropped; enrichment is now a free, offline, deterministic
part-number decoder engine with Brave web search as the only network fallback.
Backward compatible with v0.7 (header/footer detection, opt-in consolidation +
conflict fallback, condition normalizer, extra-column passthrough, HGST→WD).

#### Added
- **Decoder engine** (`enrich_engine.py`) with `enrich_row(brand, model, known)`:
  part-number decoders for Seagate/WD/Toshiba/HGST/Hitachi/HP-OEM, `capacity_from_text`,
  `looks_ssd`, optional ICEcat, Brave fallback (type/interface/form only — never
  capacity), and `known` folded last (uploaded values win, conflicts flagged).
- **Self-building cross-ref cache** (Change 7): Brave results persist keyed by the
  cleaned SKU, so a repeat SKU in any format is a free cache hit. Confident hits get
  a 60-day TTL; misses a 7-day TTL (never persist an unverified guess). Inspect via
  `cache.py {stats|show SKU|clear --sku SKU}` over the shared `mpn_cache.json`.
- **Capacity-distribution audit** (`capacity_audit`) as a regression guard against
  greedy-match phantom capacities.

#### Changed
- Enrichment is **decoder-first** (offline) with Brave as the lone network fallback;
  `/rfq-setup` + `check_setup` need Brave only (ICEcat optional). Credentials work
  offline with nothing configured.
- Format bridging in `canonicalize_specs`: `"300 GB"`→`"300GB"`, `SSHD`→`HDD`,
  `1.8"`→blank+review, `Speed` emitted as an extra passthrough column.
- MPN extraction now uses the engine's `extract_mpns` (parenthetical MPNs win,
  manufacturer prefixes preferred); the standalone `extract_mpn.py` is removed.
- The needs-review report carries the engine's `_confidence` and `_flags`.

#### Removed
- `ebay_browse_client.py`, `extract_mpn.py`, and the old tiered `enrich_mpn.py`
  cascade (and their tests). `brokerbin_client.py` / `brave_client.py` remain;
  BrokerBin is dormant, Brave is reused for the engine fallback + setup smoke-test.

### 0.8.0 — 2026-05-23

Enrichment overhaul: drop BrokerBin, add eBay, clean the MPN column, and make
"fill every core column or list it for review" the goal. Backward compatible
with v0.7 (header/footer detection, opt-in consolidation + conflict fallback,
condition normalizer, extra-column passthrough, HGST→WD).

#### Added
- **eBay Browse API client** (`ebay_browse_client.py`) — OAuth2 client-credentials
  (token cached ~2h), `item_summary/search` + `item/{id}` `localizedAspects`,
  consensus per field (capacity/interface/drive_type/form_factor/manufacturer/
  condition) with manufacturer-alias collapsing. Active listings only (Change 2).
- **`extract_mpn.py`** — pulls the manufacturer part number out of a messy vendor
  Model string, preferring a known-manufacturer prefix over OEM/spare numbers;
  preserves the original, flags unresolved MPNs for review (Change 4).
- **Needs-review report** — `write_template.py` emits `<input>-needs-review.csv`
  (rows with blank/low-confidence core columns or unresolved MPNs) plus a
  one-line run summary (Change 5).

#### Changed
- **Enrichment cascade reworked** (Change 3): tiers are now local/regex+cache →
  MTGI catalog → eBay Browse → Brave web search → leave blank/needs-review. Fill
  a core spec at consensus ≥ 0.60 with ≥2 corroborating listings (0.60–0.89
  tagged low-confidence); required fields (MPN, Condition) are never best-guessed.
- Vendor-SKU / `is_likely_vendor_sku` logic is now source-agnostic (eBay/web).

#### Removed / deprecated
- **BrokerBin sunset** (Change 1): removed from the enrichment cascade and from
  required setup. `check_setup` reports eBay + Brave and exits 0 with those alone;
  `credentials`/`rfq-setup` no longer demand BrokerBin keys (old values still
  resolve). `brokerbin_client.py` stays in the repo but dormant.

### 0.7.0 — 2026-05-23

Eight fixes from a real validation run on a messy 1,403-drive vendor file
("Evolution E-Cycle – Combined Drive Inventory"). Backward compatible: the
historical/`sum` consolidation path (AGIS lot-bid use case) is unchanged.

#### Added
- `normalize_condition.py` — single entry point for condition strings: grade
  letters, grade-suffix words ("B grade", "Grade B"), and condition words
  ("Good"). Never guesses (Fix 7).
- Parser auto-detects the real header row, skips title/banner rows, and reports
  `header_row_index` / `skipped_banner_rows`; `--header-row N` override (Fix 1).
- Parser drops trailing TOTAL/summary footer rows conservatively and reports
  them as `dropped_summary_rows` (Fix 2).
- Writer preserves extra/custom vendor columns (Serial, Tested, Source, …) after
  the 13 canonical columns instead of dropping them (Fix 4).
- Consolidation conflict detection: must-agree columns (price/capacity/specs)
  trigger a whole-file fallback to single units with `fell_back_to_single_units`
  + `conflicts` when any group disagrees (Fix 3).
- Evolution-shaped test fixture and tests across all eight fixes.

#### Changed
- **Consolidation is now opt-in.** Live/count inventory files default to one row
  per physical unit (Quantity = 1); consolidation runs only for historical bid
  records (Fix 3, SKILL.md workflow + settings card).
- Canonicalizer maps vendor drive-type spellings ("Hard Drive", "Hard Disk",
  "Solid State Drive") to HDD/SSD (Fix 5).
- Manufacturer aliases: HGST and Hitachi(-GST) variants → Western Digital
  (operator decision; WD acquired Hitachi GST 2012); added `HP Enterprise`→HPE,
  `Sandisk`→SanDisk, `WDC`→Western Digital (Fix 6).
- Row-per-item detection weights the serial-column signal by fill rate so a
  sparse serial column alone no longer forces `count` mode (Fix 8).

### 0.6.0 — 2026-05-23

Promote five spec fields to first-class typed output columns so the MTGI intake
wizard routes them into typed `rfq_lines` columns instead of the generic
`custom_fields` bucket.

#### Added
- New `canonicalize_specs.py` step: collapses the pipeline's rich internal spec
  values into the wizard's constrained canonical sets, with storage-domain gating
  and per-column provenance (`normalized_from` notes on collapsed/derived values,
  blank-reason notes when the gate fires).
- `Manufacturer` output column — canonical brand via `manufacturer_aliases`,
  populated for every part type, blank when unknown.

#### Changed
- Output template column `Size` renamed to `Capacity`.
- `Interface` constrained to `SATA` / `SAS` / `NVMe` (priority NVMe > SAS > SATA);
  `Drive Type` to `SSD` / `HDD` (qualifiers stripped); `Form Factor` to
  `2.5in` / `3.5in` / `M.2` / `U.2` / `PCIe` (`U.2`/`M.2` derived from the
  drive-type signal).
- Storage spec columns blank automatically for non-storage parts (NIC, switch,
  HBA, RAID controller, RAM, CPU, GPU).
- `template-schema.md` and `SKILL.md` updated for the typed-column contract and a
  `Protocol` → `Interface` mapping hint.

### 0.5.1 — 2026-05-22

Bug fixes from first-round Cowork validation.

#### Fixed
- Autodetect the Cowork `/sessions/<id>/mnt/<workspace>` path as the workspace
  directory, so cache and credentials persist in the right place.
- Wire `strip_brand_prefix` into `enrich()`, which now returns `(cleaned, brand)`
  so brand-prefixed MPNs enrich against the cleaned part number.

#### Changed
- Add HUSMR/HUSMM MPN patterns; refresh the consolidation docstring.

### 0.5.0 — 2026-05-22

Cowork-native persistence and parallel enrichment.

#### Added
- Workspace-dir helper for persistent storage; cache and credentials route to the
  workspace, never the read-only skill folder.
- Workspace-file credential source (`file`) for Cowork persistence, with atomic
  credential writes; `/rfq-setup` rewritten for this credential model.
- Streaming/resumable batch enrichment via `--results-jsonl`.
- `--parallel N` for concurrent batch enrichment, with file-locked cache writes so
  workers don't clobber each other's entries.
- `--budget-seconds` for clean partial exits under execution-window caps.
- Expanded MPN prefix database and brand-prefix stripping; broadened the SDLF
  SanDisk pattern to match multi-letter prefixes.
- pytest harness for the pipeline.

#### Fixed
- Parse decimal GB/MB sizes and round to marketing capacity.
- `split_row` now mines spec hints across all row text columns; `FORM_FACTOR_PATTERNS`
  matches a trailing double-quote (e.g. `2.5"`) at end-of-string.
- Historical consolidation keys on bid + win + outcome so pricing isn't lost when
  duplicate MPNs are merged.
- Validate `candidate_real_mpn` against interface tokens and family names.

#### Changed
- Single settings form after column analysis, replacing four sequential prompts.
- Reconciled the documented confidence policy with how enrichment tiers actually score.

### 0.4.0 — 2026-05-18

Initial release into the marketplace.

#### Added
- First marketplace publication of `rfq-normalizer`: normalize vendor RFQ
  spreadsheets into MTGI's canonical historical-import template — split free-text
  descriptions, consolidate duplicate MPN rows, enrich missing fields via BrokerBin
  and Brave web search, and emit a per-cell provenance log.
