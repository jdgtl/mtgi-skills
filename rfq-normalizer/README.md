# RFQ Normalizer — Claude Cowork plugin

Cleans up vendor RFQ spreadsheets and outputs the canonical MTGI historical-import template.

## Who this is for

MTGI team members who receive vendor RFQs in arbitrary formats (different column names, free-text descriptions, duplicate rows, missing fields) and need to upload them to MTGI's `/rfqs/new` historical-import flow.

## What it does

1. Accepts any xlsx or csv vendor file
2. Maps vendor columns to MTGI fields (auto-detects, asks when unclear)
3. **Consolidates duplicate rows** — exact MPN matches summed; near-matches flagged for user review
4. **Splits free-text descriptions** into structured spec columns (`size`, `interface`, `drive_type`, `form_factor`)
5. **Enriches missing fields** via a tiered cascade: regex → MTGI catalog → BrokerBin → Brave web search → ask user
6. **Surfaces vendor-internal SKUs** — when web search finds the real manufacturer MPN for a vendor's internal part number (e.g. `PA33N3T8` → `MZILS3T8HMLH`), it offers the swap explicitly
7. Outputs a template-ready `.xlsx` plus a `provenance.json` audit log

## Hard rules

- **No hallucinations.** Never invents values.
- **Exact-match consolidation only.** Even single-character differences in MPN → user confirms before merging.
- **Cite every enriched value.** Every filled field has a `{source, confidence}` entry in the provenance log.

## Install (Claude Cowork)

1. Drop the `.plugin` file into Claude Cowork — Settings → Plugins → Install from file.
2. Run `/rfq-setup` once to install Python dependencies and configure credentials.
3. The setup command walks you through entering:
   - BrokerBin API key + login (contact David Lewis at david@brokerbin.com to provision)
   - Brave Search API key (free tier 2000/mo at https://api.search.brave.com/app/signup)

Credentials are stored in the OS-native secure store (macOS Keychain, Windows Credential Manager, or Linux Secret Service) and persist across restarts and reboots.

## Build a .plugin file from source

```bash
skills/rfq-normalizer/scripts/build-plugin.sh
```

Produces `dist/rfq-normalizer-<version>.plugin` ready to install.

## Usage

Attach a vendor spreadsheet and say:

> Normalize this vendor RFQ for MTGI import.

The skill walks through each step, asks for confirmation on ambiguous cases, and outputs the normalized xlsx + provenance log.

## What's NOT in scope

- Does NOT push data to MTGI directly — produces a clean xlsx that the user uploads via MTGI's existing wizard.
- Does NOT replace MTGI's catalog-matching logic — exact/alias/fuzzy MPN resolution happens in the app on import.
- Does NOT handle live RFQs — only historical backfills with bid + outcome data.
