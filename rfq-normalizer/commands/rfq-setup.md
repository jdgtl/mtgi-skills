---
name: rfq-setup
description: Configure credentials for the rfq-normalizer skill (BrokerBin + Brave Search). Run once after plugin install.
---

Walk the user through entering their credentials for each enrichment tier the rfq-normalizer skill uses. Store each value via the skill's credential helper so it persists in the OS-native secure store (macOS Keychain, Windows Credential Manager, or Linux Secret Service) across Claude restarts and machine reboots.

## Steps

0. **Install dependencies.** The skill uses the `keyring` PyPI package to talk to the system credential store. Run:

   ```bash
   python -m pip install --user -r "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/requirements.txt"
   ```

   If `pip` reports any package is already installed, that's fine — continue. If the install fails (e.g., no Python on PATH), surface the error and stop.

1. Show current credential status by running:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" status
   ```

   The output is JSON keyed by credential name with `source` (`env` / `keychain` / `file` / `null`) and `set` (bool). Summarize it for the user in plain language — "BrokerBin API key: not configured" etc.

2. For each unset credential, prompt the user via AskUserQuestion or an elicitation form. Use the labels and help text below verbatim — they're the spec.

   | Credential name | Label | Help text |
   |---|---|---|
   | `brokerbin_api_key` | BrokerBin API key | Contact your BrokerBin account rep to provision (David Lewis: david@brokerbin.com). |
   | `brokerbin_login` | BrokerBin login (username) | Your BrokerBin account username. Some accounts require this in addition to the API key. |
   | `brave_search_api_key` | Brave Search API key | Sign up at https://api.search.brave.com/app/signup (free tier: 2000 queries/month). |

   If the user skips a prompt, save nothing for that key — the tier will silently disable rather than fail.

3. Save each entered value:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" set <name> <value>
   ```

   This writes to the OS-native secure store via the `keyring` library. On macOS the first read from a new Python process may trigger an "Always Allow / Allow / Deny" Keychain dialog — that's expected once per machine; click "Always Allow" to make subsequent runs silent.

4. After all prompts, run the verification script:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/check_setup.py"
   ```

   Report the tier status table to the user.

5. Smoke-test any keys that were configured:

   ```bash
   # BrokerBin
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/brokerbin_client.py" --test-connection HUS726060ALA640
   # Brave Search
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/brave_client.py" --test-connection "test"
   ```

   Confirm each returns `{"ok": true, "error": null}`. If not, show the error and suggest the user double-check the relevant key.

## Notes for the agent

- **Per-user accounts.** BrokerBin appears to provision per-user; each teammate needs their own credentials. Don't suggest sharing a key.
- **Keychain prompts.** macOS may prompt the user the first time a script reads a Keychain entry. Tell them to click "Always Allow" so subsequent runs are silent.
- **Resetting credentials.** To clear a value, run `python ${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py delete <name>`.
- **Env-var overrides.** If a user has set the corresponding env var (e.g. `BROKERBIN_API_KEY`) the credentials script will return that and skip the keyring — useful for dev workflows. Mention this if the user asks why stored values seem to be ignored.
- **Headless / unsupported environments.** If no system keyring is available (e.g., a Linux box with no Secret Service daemon), `credentials.py set` raises a clear error pointing to the env-var workaround. The diagnostic command `python ${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py backend` prints which backend is active.
