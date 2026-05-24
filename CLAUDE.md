# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is the `mtgi-skills` Claude Cowork plugin marketplace **and** the source of truth for the plugins it hosts. Edit files under `<plugin>/` directly — there is no upstream mirror.

The marketplace itself is declared in `.claude-plugin/marketplace.json`. Each plugin lives at `<plugin-name>/` and is referenced by relative `source` in that file. Visibility is **public** (made public 2026-05-23) — anything committed, including git history and the `dist/` artifacts, is world-readable, so keep secrets out of the tree.

## Release flow

When the user asks to "cut a release" or "publish a new version":

1. Bump `version` in `<plugin>/.claude-plugin/plugin.json`.
2. Commit + push. Marketplace consumers pick up on their next `claude plugin marketplace update mtgi-skills`.
3. For Cowork's "install from file" path, run `scripts/build-plugin.sh [plugin]` to produce `dist/<plugin>-<version>.plugin`. `dist/` is committed to the repo so the built artifacts have shareable GitHub links (e.g. send someone the raw URL of `dist/<plugin>-<version>.plugin` to install). Commit the new artifact alongside the version bump.

`scripts/build-plugin.sh` zips the plugin tree, reads the version from `plugin.json` via inline `python3`, and excludes `.DS_Store`, `__pycache__`, `*.pyc`, `*.pyo`, `.cache/`, and `examples/` from the artifact.

## Plugin layout

A plugin directory mirrors the Claude Cowork plugin spec:

```
<plugin>/
  .claude-plugin/plugin.json     # name, version, description
  skills/<skill>/SKILL.md        # skill definition (frontmatter + body)
  skills/<skill>/scripts/        # Python helpers the skill shells out to
  skills/<skill>/reference/      # static reference docs read by the skill
  skills/<skill>/prompts/        # LLM-fallback prompts the skill loads
  skills/<skill>/requirements.txt
```

Everything is a **skill** under `skills/`. Cowork flags a top-level `commands/` directory as the legacy format, so user-invoked actions (like setup) are skills too — e.g. `skills/rfq-setup/SKILL.md` with `disable-model-invocation: true` so it only runs when the user calls `/rfq-setup`, never auto-triggered. Do not add a `commands/` directory.

Scripts are invoked from the skill body with `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/<name>.py`. Dependencies install via `pip install --user -r requirements.txt` — the `/rfq-setup` skill runs this on first use.

## rfq-normalizer specifics

The pipeline is a fixed sequence of Python scripts orchestrated by `skills/rfq-normalizer/SKILL.md`. Each step is one script; the skill body is the controller and is where workflow logic lives, not in any Python file. Key invariants enforced by the skill:

- **Never invent values** — every enriched field is cited in `provenance.json` with `{source, confidence}`.
- **Exact-match consolidation only** — even whitespace/case differences in MPN require operator confirmation before merging.
- **Tiered enrichment with quota awareness** — Tier 1 MTGI catalog (optional), Tier 2 BrokerBin (50/day quota, persistent cache at `.cache/brokerbin-enrichment.json` with 60-day TTL on hits, 7-day on misses), Tier 3 Brave Search, Tier 4 ask user. Pass `--current` to `enrich_mpn.py` to skip already-filled fields and conserve quota.
- **Vendor-SKU detection** lives in `mpn_patterns.py`; when an MPN matches no known manufacturer prefix and BrokerBin returns nothing, the skill must surface the swap suggestion explicitly rather than auto-replacing.
- **Manufacturer aliases** (HGST↔Hitachi, Compaq↔HPE, etc.) are normalized in `manufacturer_aliases.py` before consensus checks.

Credentials live in the OS keyring via `scripts/credentials.py` (env vars override). The skill's pre-flight calls `check_setup.py`; if BrokerBin is unconfigured, it stops and routes the user to `/rfq-setup`.

When debugging the rfq-normalizer pipeline:

```bash
# Inspect / clear the enrichment cache
python rfq-normalizer/skills/rfq-normalizer/scripts/cache.py {stats|clear|show MPN}

# Smoke-test API connectivity
python rfq-normalizer/skills/rfq-normalizer/scripts/brokerbin_client.py --test-connection HUS726060ALA640
python rfq-normalizer/skills/rfq-normalizer/scripts/brave_client.py --test-connection "test"

# Show which credentials/tiers are configured
python rfq-normalizer/skills/rfq-normalizer/scripts/check_setup.py
```
