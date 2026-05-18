# Manufacturer Aliases

`scripts/manufacturer_aliases.py` collapses naming variants and acquisitions
into a single canonical name. This is critical for BrokerBin consensus:
without it, a part that everyone agrees is HGST/WD enterprise storage
might split votes 50/50 between "HITACHI" and "WESTERN DIGITAL" and we'd
flag low confidence on what's actually unanimous agreement.

## Canonical mappings

| Canonical | Variants collapsed |
|---|---|
| `Hitachi` | HGST, Hitachi GST, Hitachi Global Storage, Hitachi Global Storage Technologies, IBM/Hitachi |
| `Western Digital` | WD |
| `Oracle` | Sun, Sun Microsystems, Sun/Oracle |
| `HPE` | HP, Hewlett Packard, Hewlett-Packard, Hewlett Packard Enterprise, Compaq |
| `Dell` | Dell EMC, Dell Technologies, EMC, EMC Corporation |
| `IBM` | (kept as IBM) |
| `Lenovo` | (kept as Lenovo) |
| `Samsung` | Samsung Electronics, Samsung Semi, Samsung Semiconductor |
| `Toshiba` | Toshiba Electronics, Toshiba America |
| `Intel` | Intel Corporation, Solidigm (Intel's NAND business → SK Hynix as Solidigm, but historical MPNs still trace to Intel) |
| `Nvidia` | Mellanox, Mellanox Technologies, Nvidia Networking |
| `Broadcom` | Brocade, Brocade Communications |
| `SK Hynix` | Hynix, SK Hynix |
| `Cisco` | Cisco Systems |

## Functions

```python
normalize_manufacturer(name: str) -> str | None
manufacturers_match(a: str, b: str) -> bool
```

`normalize_manufacturer` returns the canonical form, falling back to title-case
for unrecognized long names and uppercase for short ones (so "HPE", "IBM",
"AMD" stay as acronyms but "SEAGATE TECHNOLOGY" becomes "Seagate Technology").

`manufacturers_match` is a convenience wrapper that returns True iff both
inputs normalize to the same canonical form. Used in `enrich_mpn.py` for the
vendor-corroboration boost.

## Editorial decisions

Some choices favor operator usefulness over strict legal accuracy:

- **`HGST → Hitachi` (not Western Digital).** WD acquired HGST in 2012, but
  vendor inventory lists overwhelmingly still call HUS-prefixed drives "Hitachi"
  because that's what the customer remembers. We follow the customer convention.
- **`Compaq → HPE` (not HP).** HP acquired Compaq in 2002, then split itself
  into HP and HPE in 2015. For server/storage equipment, HPE is the right
  modern reference.
- **`EMC → Dell`.** Dell acquired EMC in 2016 forming Dell Technologies. For
  server/storage parts this is the right consolidation.
- **`Solidigm → Intel`.** SK Hynix acquired Intel's NAND business in 2021 as
  Solidigm. Drives with Intel SSDPED-style MPNs still trace cleanly to "Intel"
  in BrokerBin listings; we follow that. Revisit if this stops being true.

## Adding new aliases

Edit the `_ALIASES` dict at the top of `manufacturer_aliases.py`. Keys are
**already lowercased and whitespace-collapsed**, so:

- ✅ `"hewlett packard enterprise": "HPE"`
- ❌ `"Hewlett Packard Enterprise": "HPE"`

Then re-run the module's `__main__` block to verify your additions:

```bash
python3 scripts/manufacturer_aliases.py
```
