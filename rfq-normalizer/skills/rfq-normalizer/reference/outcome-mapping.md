# Outcome Mapping

Mirror of `src/lib/intake/normalize-outcome.ts` in the MTGI app. Vendor strings map to canonical enum values.

## Canonical enum values

```
pending
won
lost_to_competitor
lost_no_response
lost_no_buy
withdrawn
```

## Accepted variants (lowercased, trimmed)

| Canonical | Accepted inputs |
|---|---|
| `won` | `won`, `win`, `awarded`, `y`, `yes` |
| `lost_to_competitor` | `lost`, `loss`, `no`, `n`, `lost_to_competitor`, `lost-to-competitor`, `lost to competitor`, `competitor` |
| `lost_no_response` | `lost_no_response`, `lost-no-response`, `lost no response`, `no response`, `no reply`, `ghosted` |
| `lost_no_buy` | `lost_no_buy`, `lost-no-buy`, `lost no buy`, `no buy`, `no purchase` |
| `withdrawn` | `withdrawn`, `cancelled`, `canceled`, `rescinded` |
| `pending` | `pending`, `open`, `in progress`, `submitted` |

If a value doesn't match any of the above → output blank cell (NOT `unknown`). The MTGI wizard treats blank as `pending`.
