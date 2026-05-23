# Changelog

All notable changes to plugins in the `mtgi-skills` marketplace are recorded here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); plugins
are versioned independently and each entry notes which plugin it applies to.

## rfq-normalizer

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
