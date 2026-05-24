---
name: rfq-setup
description: Configure credentials for the rfq-normalizer skill (eBay Browse + Brave Search). Run once per workspace.
---

Walk the user through entering credentials for each enrichment tier the
rfq-normalizer skill uses. Store each value via the skill's credential
helper, which writes a chmod-600 file in the persistent workspace folder
so values survive Cowork sandbox resets.

## Steps

0. **Install dependencies.** The skill uses the `keyring` PyPI package as a
   fallback credential store on hosts with a working OS keychain. Run:

   ```bash
   python -m pip install --user -r "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/requirements.txt"
   ```

   If `pip` reports any package is already installed, that's fine — continue.

1. Show current credential status:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" status
   ```

   Output is JSON keyed by credential name with `source` (`env` / `file` /
   `keyring` / `null`) and `set` (bool). Summarize for the user in plain
   language — "BrokerBin API key: not configured", etc.

2. For each unset credential, prompt the user via AskUserQuestion or an
   elicitation form, using these labels and help text verbatim:

   | Credential name | Label | Help text |
   |---|---|---|
   | `ebay_app_id` | eBay App ID (Client ID) | eBay developer program → your production application keyset: https://developer.ebay.com/my/keys |
   | `ebay_cert_id` | eBay Cert ID (Client Secret) | The Cert ID from the same keyset as the App ID. |
   | `brave_search_api_key` | Brave Search API key | Sign up at https://api.search.brave.com/app/signup (free tier: 2000 queries/month). |

   Skipped prompts save nothing — the tier silently disables rather than failing. The eBay keyset must be a **Browse API** application keyset (client-credentials / guest access); the Sell API store account cannot search the marketplace. BrokerBin is no longer used (sunset in v0.8.0); if old `brokerbin_*` values are present they're ignored.

3. Save each entered value:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" set <name> <value>
   ```

   This writes to `<workspace>/.rfq-normalizer.env` (chmod 600). Set
   `RFQ_WORKSPACE_DIR` or `RFQ_CREDS_FILE` first to override the location.

4. Verify:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/check_setup.py"
   ```

   Report the tier status table to the user.

5. Smoke-test any keys that were configured:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/ebay_browse_client.py" --test-connection ST9300603SS
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/brave_client.py" --test-connection "test"
   ```

   Confirm each returns `{"ok": true, "error": null}`.

## Notes for the agent

- **eBay Browse keyset.** Needs an application keyset (App ID + Cert ID) with Browse API access; the client uses OAuth2 client-credentials (no user-consent redirect). The Sell API store account will not work for marketplace search.
- **File location.** `python credentials.py backend` shows the active backend (file path or keyring backend name). Useful for diagnosing why a value isn't being read.
- **Plaintext credentials.** The workspace env file is plaintext; that's acceptable for an internal tool but document it and keep the file out of any synced/shared folder.
- **Env-var overrides.** If a user has set the corresponding env var (e.g. `BROKERBIN_API_KEY`) the credentials script will return that and skip the file — useful for dev workflows.
- **Resetting credentials.** `python credentials.py delete <name>` removes the value from both the file and the keyring.
- **Headless / unsupported environments.** If no writable file path is found AND no keyring backend exists, `credentials.py set` raises a clear error pointing to the env-var workaround.
