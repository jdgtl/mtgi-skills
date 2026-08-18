# Listing spec

The JSON object `publish.py` consumes. Write it to a temp file, `dry-run` it,
then `publish` it.

```json
{
  "sku": "MTGI-CMK64GX4M4A2666C16-01",
  "title": "Corsair Vengeance LPX 64GB (4x16GB) DDR4 2666 Desktop RAM Kit - Tested",
  "description": "Corsair Vengeance LPX 64GB kit, four matched 16GB DDR4-2666 modules. Pulled from a working system and tested. Light shelf wear on the heat spreaders; no bent pins.",
  "condition": "used_good",
  "conditionDescription": "Tested working. Minor cosmetic scuffing on two heat spreaders.",
  "quantity": 1,
  "price": "149.00",
  "currency": "USD",
  "categoryId": "170083",
  "brand": "Corsair",
  "mpn": "CMK64GX4M4A2666C16",
  "aspects": {
    "Brand": "Corsair",
    "Type": "DDR4 SDRAM",
    "Total Capacity": "64 GB",
    "Number of Modules": "4"
  },
  "imageUrls": [
    "https://assets.mtgi-inc.com/listings/MTGI-CMK64GX4M4A2666C16-01/01.png",
    "https://assets.mtgi-inc.com/listings/MTGI-CMK64GX4M4A2666C16-01/02.png"
  ],
  "merchantLocationKey": "mtgi-warehouse",
  "fulfillmentPolicyId": "0000000000",
  "paymentPolicyId": "0000000000",
  "returnPolicyId": "0000000000"
}
```

## Fields

| Field | Required | Notes |
|---|---|---|
| `sku` | yes | Convention `MTGI-<MPN-or-slug>-<unit>`. MPN verbatim. Idempotency key. |
| `title` | yes | **80 chars max.** Hard eBay limit; `validate` enforces it. |
| `description` | no | Becomes both the product description and the listing description. |
| `condition` | yes | MTGI vocabulary or an eBay enum — see `conditions.md`. |
| `conditionDescription` | no | Free text. Only meaningful for used conditions. |
| `quantity` | no | Defaults to 1. Sets both item availability and offer quantity. |
| `price` | yes | String, e.g. `"149.00"`. Not a float. |
| `currency` | no | Defaults to `USD`. |
| `categoryId` | yes | From `ebay_api.py suggest-category`. Never hardcode. |
| `brand` | no | Fills `product.brand`. |
| `mpn` | no | Fills `product.mpn`. **Verbatim.** |
| `upc` / `ean` / `isbn` | no | Product identifier, string or list. Some categories refuse to publish without one (eBay error 25002 "The UPC field is missing") — read it off the retail box barcode. |
| `aspects` | no | `{name: value}` or `{name: [values]}`. Every *required* aspect for the category must be present or publish fails. |
| `imageUrls` | yes | HTTPS only, ordered. From `r2_upload.py stage`. First is the gallery image. |
| `packageWeightAndSize` | no | eBay shape, passed through: `{"weight": {"value": 2, "unit": "POUND"}, "dimensions": {"length": 8, "width": 6, "height": 4, "unit": "INCH"}}`. Pre-fills label purchase; required for calculated-cost services. |
| `merchantLocationKey` | yes | From `ebay_api.py locations`. |
| `fulfillmentPolicyId` | yes | From `ebay_api.py policies`. |
| `paymentPolicyId` | yes | Same. |
| `returnPolicyId` | yes | Same. |
| `listed_by` | no | Who published it. Defaults to `$USER`. The team shares one eBay seller login, so eBay cannot attribute a listing to a person — this is the only record of who did it. |

## What `validate` catches before eBay does

- Missing required fields
- Title over 80 characters
- Unknown condition value
- No images, or a non-HTTPS image URL
- Missing merchant location
- Missing any of the three business policies

`dry-run` additionally prints the resolved `inventory_item` and `offer`
payloads so the operator can see exactly what eBay will receive.

## What it cannot catch

Required *aspects* are per-category and only known after calling
`ebay_api.py aspects <categoryId>`. Fill them in step 4 of the workflow — a
missing one fails at publish, not at validate.
