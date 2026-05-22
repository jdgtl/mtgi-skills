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

This repo is the **source of truth** for every plugin it hosts. Edit files in place under `<plugin>/` — there is no upstream mirror to sync from.

To cut a release:

1. Bump `version` in `<plugin>/.claude-plugin/plugin.json`.
2. Commit + push. Teammates installing via the marketplace (`claude plugin marketplace update mtgi-skills`) pick up the new version on their next update.
3. (Optional) For Claude Cowork's "install from file" flow, build a `.plugin` zip:

   ```bash
   scripts/build-plugin.sh             # defaults to rfq-normalizer
   scripts/build-plugin.sh <plugin>    # any plugin in this repo
   ```

   Output lands at `dist/<plugin>-<version>.plugin`. `dist/` is gitignored; distribute the artifact out-of-band.

Visibility: **private**. Don't make this repo public without auditing every file for MTGI-internal references.
