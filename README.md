# MTGI Skills — Claude Cowork plugin marketplace

Internal plugin marketplace for MTGI workflows. Hosts Claude Cowork plugins the team uses for trading-floor data work.

## Install the marketplace

```bash
claude plugin marketplace add jdgtl/mtgi-skills
```

This clones the marketplace privately to your local Claude install. You can then install any plugin from it.

## Available plugins

| Plugin | Version | Description |
|---|---|---|
| [`rfq-normalizer`](./rfq-normalizer) | 0.8.0 | Cleans up any vendor RFQ spreadsheet (xlsx/csv) and produces MTGI's historical-import xlsx + provenance log + needs-review report. Auto-detects header rows / drops summary footers, extracts a clean MPN, splits free-text into five typed spec columns, preserves extra vendor columns, normalizes conditions, eBay Browse + Brave enrichment, vendor-SKU detection. |

## Install a specific plugin

```bash
claude plugin install rfq-normalizer@mtgi-skills
```

Then run the plugin's first-run setup. For `rfq-normalizer`, that's `/rfq-setup` — it'll install Python dependencies and walk you through entering credentials (stored in your OS-native secure keychain).

## Updates

```bash
claude plugin marketplace update mtgi-skills
claude plugin update rfq-normalizer
```

## For maintainers

This repo is the **source of truth** for every plugin it hosts. Edit files in place under `<plugin>/` — there is no upstream mirror to sync from.

To cut a release:

1. Bump `version` in `<plugin>/.claude-plugin/plugin.json` and add a `CHANGELOG.md` entry.
2. Commit + push. Teammates installing via the marketplace (`claude plugin marketplace update mtgi-skills`) pick up the new version on their next update.
3. For Claude Cowork's "install from file" flow, build a `.plugin` zip:

   ```bash
   scripts/build-plugin.sh             # defaults to rfq-normalizer
   scripts/build-plugin.sh <plugin>    # any plugin in this repo
   ```

   Output lands at `dist/<plugin>-<version>.plugin`. `dist/` is **committed** so the artifacts have shareable GitHub links. Tag a matching GitHub release (e.g. `v0.7.0`) and attach the `.plugin` as a release asset — the release page is the cleanest link to hand to teammates.

Visibility: **public**. Git history and the committed `dist/` artifacts are world-readable — keep secrets and MTGI-internal references out of the tree.
