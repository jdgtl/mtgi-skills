# RFQ Normalizer — Claude Cowork plugin

Cleans up vendor RFQ spreadsheets and outputs the canonical MTGI historical-import template.

## Who this is for

MTGI team members who receive vendor RFQs in arbitrary formats (different column names, free-text descriptions, duplicate rows, missing fields) and need to upload them to MTGI's `/rfqs/new` historical-import flow.

## What it does

1. Accepts any xlsx or csv vendor file — **auto-detects the real header row** below title/banner rows and **drops TOTAL/summary footers** so they never become bogus line items (`--header-row N` to override)
2. Maps vendor columns to MTGI fields (auto-detects, asks when unclear)
3. **Splits free-text descriptions** into five **typed spec columns** the MTGI wizard maps to first-class fields: `Capacity`, `Interface`, `Drive Type`, `Form Factor`, `Manufacturer`
4. **Preserves extra vendor columns** (Serial, Tested, Source, …) so the wizard captures them as `custom_fields` instead of dropping them
5. **Normalizes conditions** — grade letters, "B grade" suffixes, and condition words ("Good") → MTGI's condition enum
6. **Consolidation is opt-in** — live/count inventory defaults to one row per physical unit; when consolidation runs, any same-spec price/capacity conflict safely reverts the whole file to single units
7. **Enriches missing fields** decoder-first: an offline part-number decoder engine (Seagate/WD/Toshiba/HGST/Hitachi/HP-OEM) → Brave web search fallback for type/interface/form → leave blank for review (never invents capacity from a web match)
8. **Surfaces vendor-internal SKUs** — when web search finds the real manufacturer MPN for a vendor's internal part number (e.g. `PA33N3T8` → `MZILS3T8HMLH`), it offers the swap explicitly
9. Outputs a template-ready `.xlsx`, a `provenance.json` audit log, and a `needs-review.csv` listing rows with blank/low-confidence core columns or unresolved MPNs

## Hard rules

- **No hallucinations.** Never invents values.
- **Exact-match consolidation only.** Even single-character differences in MPN → user confirms before merging.
- **Cite every enriched value.** Every filled field has a `{source, confidence}` entry in the provenance log.

## Install (Claude Cowork)

1. Drop the `.plugin` file into Claude Cowork — Settings → Plugins → Install from file.
2. Run `/rfq-setup` once to install Python dependencies and configure credentials.
3. The setup command walks you through entering:
   - Brave Search API key (optional — the decoder works offline; Brave is the fallback for rows it can't decode; free tier 2000/mo at https://api.search.brave.com/app/signup)

Credentials are written to a chmod-600 workspace file (`<workspace>/.rfq-normalizer.env`), which is the only storage that survives a Cowork sandbox reset and so is the primary persistence layer. On local-Mac installs with a working keychain, the OS-native secure store (macOS Keychain, Windows Credential Manager, Linux Secret Service) acts as an additional fallback. Env vars override both.

## Build a .plugin file from source

```bash
scripts/build-plugin.sh rfq-normalizer
```

Produces `dist/rfq-normalizer-<version>.plugin` ready to install. Released versions are also attached to [GitHub releases](https://github.com/jdgtl/mtgi-skills/releases) — download the `.plugin` from there.

## Usage

Attach a vendor spreadsheet and say:

> Normalize this vendor RFQ for MTGI import.

The skill walks through each step, asks for confirmation on ambiguous cases, and outputs the normalized xlsx + provenance log.

## What's NOT in scope

- Does NOT push data to MTGI directly — produces a clean xlsx that the user uploads via MTGI's existing wizard.
- Does NOT replace MTGI's catalog-matching logic — exact/alias/fuzzy MPN resolution happens in the app on import.
- Handles both **live/count inventory lists** (one row per physical unit) and **historical backfills** with bid + outcome data.
