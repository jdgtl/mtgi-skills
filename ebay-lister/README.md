# ebay-lister

Build and publish eBay listings by talking them through. No app, no database,
no inventory system — a conversation, a folder of photos, and the eBay Sell
Inventory API.

## What it does

```
/ebay-lister
> Corsair 64GB DDR4 kit, used-good, $149, photos are in work/product-images

  3 image groups found: corsair-64gb-ram-01, -02, -03 (4 photos each)
  → three physical units, so three listings. Start with -01?
> yes

  Category   170083  Computer Memory (RAM)      [confirm/change]
  Required aspects: Brand, Type, Total Capacity, Number of Modules
  …
  Title      Corsair Vengeance LPX 64GB (4x16GB) DDR4 2666 Desktop RAM Kit - Tested
  Price      $149.00 · Qty 1
  Publish? [y/n/edit]
> y

  ✓ Live — https://www.ebay.com/itm/…
```

Along the way it stages the photos to Cloudflare R2, resolves the category and
its required item aspects from eBay's Taxonomy API, drafts the title and
specifics for approval, and runs the three-step publish chain.

It will also inspect, create, and edit the business policies and inventory
locations a listing depends on — those are account-level prerequisites that
`publishOffer` fails without.

## Install

```bash
claude plugin marketplace add jdgtl/mtgi-skills
claude plugin install ebay-lister@mtgi-skills
/ebay-setup
```

`/ebay-setup` runs the OAuth flow once. The refresh token is valid for ~18
months; after that, run it again.

## Requirements

- **Python 3.10+** — stdlib only, no `requirements.txt`
- **Node.js** — for `npx wrangler r2 object put`; no global install needed
- An eBay developer app (App ID, Cert ID, RuName) with the seller account authorized
- A public Cloudflare R2 bucket — defaults to `mtgi` at `https://assets.mtgi-inc.com`
- Cloudflare auth: `CLOUDFLARE_API_TOKEN` with R2 write scope, or `npx wrangler login`

## How images work

Photos live in a flat folder named `<product-slug>-<unit>-<image#>.<ext>`:

```
corsair-64gb-ram-01-1.png   ← group "corsair-64gb-ram-01", gallery image
corsair-64gb-ram-01-2.png
corsair-64gb-ram-02-1.png   ← a different physical unit, a different listing
```

One group is one unit is one listing. The skill uploads each group to R2 under
`listings/<sku>/`, verifies every public URL with a HEAD request, and passes
the ordered URLs to eBay.

**eBay copies self-hosted images to eBay Picture Services when the listing
publishes**, so R2 is a staging hop — the URLs only need to resolve at publish
time, not for the life of the listing.

## Scripts

| Script | Purpose |
|---|---|
| `check_setup.py` | Pre-flight: credentials, token, policies, location, R2 |
| `r2_upload.py` | `scan` a folder; `stage` one group to R2 |
| `ebay_api.py` | Categories, aspects, policies, locations |
| `publish.py` | `validate` / `dry-run` / `publish` |
| `auth.py` | OAuth: consent URL, code exchange, token refresh |
| `credentials.py` | chmod-600 credential store, keyring fallback |

Each runs standalone with `--help`.

## Safety

- Never publishes without explicit confirmation
- Idempotent by SKU — a retry can't double-list
- Stops if a staged image URL doesn't verify
- Validates title length, condition, images, and policies before calling eBay
- Appends every published listing to `~/.ebay-lister-listings.jsonl`

## Credentials

Resolution order, first match wins:

1. Environment variable
2. **macOS Keychain** via the built-in `security` CLI — where writes go by default
3. `keyring` package, if installed (non-macOS hosts)
4. chmod-600 file at `~/.ebay-lister.env` (fallback for hosts with no keychain)

Keychain items use the service names `ebay-client-id`, `ebay-client-secret`,
`ebay-redirect-uri`, `ebay-refresh-token` — readable with
`security find-generic-password -s ebay-client-id -w`.

The access token is cached separately at `~/.ebay-lister-token.json`.

**This repo is public. No credential is ever committed** — not in a file, not
in an example, not in git history. Values live in the Keychain.

## Team rollout

Everyone shares one MTGI eBay seller account, so teammates never need
developer.ebay.com access. They need four values from you, delivered through
whatever channel already carries the store login — **never through this repo**:

| Keychain service | What it is |
|---|---|
| `ebay-client-id` | MTGI's eBay App ID |
| `ebay-client-secret` | MTGI's eBay Cert ID |
| `ebay-redirect-uri` | The RuName string |
| `ebay-refresh-token` | From your one-time OAuth run — skips their browser flow entirely |

Each teammate installs the plugin and stores them:

```bash
security add-generic-password -U -s ebay-client-id -a "$USER" -w '<value>'
# …repeat for the other three
```

Then `/ebay-lister` works immediately — no `/ebay-setup` run, no browser
consent, no eBay developer account.

`/ebay-setup` is the owner's tool: run it once to mint the refresh token, and
again in ~18 months when it expires.

Sharing the refresh token is equivalent to sharing the store login, which the
team already does — it grants no access they don't have. It is still a live
credential: Keychain only, never a file, never a chat message that persists.

Each teammate also needs R2 write access for image staging — a
`CLOUDFLARE_API_TOKEN` scoped to R2, or `npx wrangler login`. Scoped tokens
beat sharing account access.
