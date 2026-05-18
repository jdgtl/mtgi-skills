# MTGI Skills — Claude Cowork plugin marketplace

Internal plugin marketplace for MTGI workflows. Hosts Claude Cowork plugins the team uses for trading-floor data work.

## Install the marketplace

```bash
claude plugin marketplace add jdgtl/mtgi-skills
```

This clones the marketplace privately to your local Claude install. You can then install any plugin from it.

## Available plugins

| Plugin | Description |
|---|---|
| [`rfq-normalizer`](./rfq-normalizer) | Cleans up vendor RFQ spreadsheets and produces MTGI's historical-import xlsx + provenance log. Tier 2 BrokerBin enrichment, Tier 3 Brave web search, vendor-SKU detection. |

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

This repo is the **distribution** mirror. The authoritative source for each plugin lives in its home repo (e.g. `rfq-normalizer` is developed in [`MTGI/web-app`](https://github.com/jdgtl/MTGI) under `skills/rfq-normalizer/`). To cut a release:

1. Bump the plugin's `version` in `<plugin>/.claude-plugin/plugin.json` in its source repo
2. Build a fresh tree via the source repo's `scripts/build-plugin.sh`
3. Copy the build output into this marketplace's `<plugin>/` directory
4. Commit + push here; teammates pick up the new version on their next `claude plugin marketplace update`

Visibility: **private**. Don't make this repo public without auditing every file for MTGI-internal references.
