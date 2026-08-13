---
name: ebay-setup
description: One-time OAuth and configuration for the ebay-lister skill. Run via /ebay-setup. Also the recovery path if the eBay refresh token ever expires.
disable-model-invocation: true
---

Walk the operator through connecting an eBay seller account and confirming
where listing images are staged. This runs **once** — the refresh token is
valid for ~18 months, after which this skill is the recovery path.

Scripts live at `${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/` (the setup
skill deliberately shares the lister's scripts — there is one credential store).

## Steps

### 0. Confirm where values will be stored

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/credentials.py" backend
```

`keychain:macos-security` is the expected answer on a Mac — values go to the
macOS Keychain via the built-in `security` CLI, never to a plaintext file.

If it reports `file:…`, you are on a host without a keychain (a sandbox).
That's supported, but say so plainly: the credentials will sit in a chmod-600
file, which is a weaker store.

### 1. Show current state

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/credentials.py" status
```

Summarize in plain language. `source: "default"` means a built-in default is in
play, not a stored value — that's fine for the R2 settings.

### 2. Collect the eBay app keys

Prompt for any required credential that is unset, using AskUserQuestion or an
elicitation form. Labels and help text:

| Credential | Label | Help |
|---|---|---|
| `ebay_client_id` | eBay App ID (Client ID) | developer.ebay.com → Application Keys → Production |
| `ebay_client_secret` | eBay Cert ID (Client Secret) | Same page. Treat as a secret. |
| `ebay_redirect_uri` | eBay RuName | developer.ebay.com → User Tokens. This is the **RuName string, not a URL**. |

Store each:

```bash
python3 ".../credentials.py" set ebay_client_id "<value>"
```

### 3. Confirm the R2 staging config

Defaults are already correct for MTGI:

- bucket `mtgi`
- public base `https://assets.mtgi-inc.com`
- key prefix `listings`

Only override if the operator says otherwise:

```bash
python3 ".../credentials.py" set r2_public_base "https://assets.example.com"
```

Cloudflare auth for uploads comes from `CLOUDFLARE_API_TOKEN` (R2 write scope)
or a prior `npx wrangler login`. Mention this only if pre-flight warns.

### 4. Run the OAuth flow

Build the consent URL:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/auth.py" url
```

Give the operator the URL and these instructions verbatim:

1. Open it in a browser and sign in as the **seller account**, then accept.
2. eBay redirects to your RuName's callback. **The page will probably fail to
   load — that is expected and fine.**
3. Copy the `code=` parameter out of the address bar. It is URL-encoded; copy
   the whole value up to the next `&`.
4. Paste it back here **within 5 minutes** — authorization codes expire in
   ~299 seconds and are single-use.

Then exchange it immediately:

```bash
python3 ".../auth.py" exchange "<code>"
```

This stores the refresh token and its expiry. If the exchange fails with
`invalid_grant`, the code expired or was already used — regenerate the URL and
go again. Do not retry the same code.

**Do not use any eBay-provided "get OAuth URL" helper.** They have historically
emitted a broken URL — empty `state=`, a trailing `hd=`, and a
`signin.ebay.com/signin?ru=` wrapper that eBay rejects with `invalid_request`.
`auth.py url` builds it from the documented parameters instead.

### 5. Verify

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/check_setup.py"
```

Walk the operator through anything not `OK`. Missing business policies or
inventory locations are **not** a setup failure — the `ebay-lister` skill
creates those in conversation. Say so rather than blocking here.

On success, tell them: authenticate once, then `/ebay-lister` just works until
the refresh token expires — the date is in the pre-flight output.

## Teammates don't run this

Everyone shares one MTGI seller account, so the refresh token this produces is
the same for the whole team. Teammates get the four values out-of-band and
store them directly:

```bash
security add-generic-password -U -s ebay-client-id -a "$USER" -w '<value>'
```

Services: `ebay-client-id`, `ebay-client-secret`, `ebay-redirect-uri`,
`ebay-refresh-token`. Then `/ebay-lister` works with no browser flow and no
eBay developer account. See the plugin README's "Team rollout" section.

This skill is the account owner's tool — run once now, once in ~18 months.

## Notes

- Values go to the **macOS Keychain** by default (service names above), falling
  back to a chmod-600 file at `~/.ebay-lister.env` only where no keychain
  exists. Env vars take precedence over both.
- The access-token cache is separate, at `~/.ebay-lister-token.json`.
- **Never echo a secret back into the transcript.** Confirm by label, not value.
  A pasted secret persists in session history — that is how leaks happen.
- `mtgi-skills` is a **public** repo. No credential ever gets committed, and
  `.gitignore` blocks `*.env` as a backstop.
- Per JDGTL's standing rule (`05_System/credentials/REGISTRY.md`, 2026-08-03):
  secret values never live under `Documents/`. Add a registry line for each new
  Keychain item.
