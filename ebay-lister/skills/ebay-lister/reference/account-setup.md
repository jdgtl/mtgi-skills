# Account prerequisites

`publishOffer` fails without an enabled inventory location and all three
business policies. These are **account-level** — they affect every listing, not
just the one being built. Always show the payload to the operator before
writing.

## Inspect first

```bash
python3 ".../ebay_api.py" policies
python3 ".../ebay_api.py" locations
```

## Inventory location

One is enough. The key is yours to choose and is referenced by every offer.

```bash
python3 ".../ebay_api.py" create-location mtgi-warehouse '{
  "location": {
    "address": {
      "addressLine1": "123 Example St",
      "city": "Springfield",
      "stateOrProvince": "MA",
      "postalCode": "01103",
      "country": "US"
    }
  },
  "locationInstructions": "Ships from MTGI warehouse",
  "name": "MTGI Warehouse",
  "merchantLocationStatus": "ENABLED",
  "locationTypes": ["WAREHOUSE"]
}'
```

`country` is a two-letter ISO code. `stateOrProvince` is the two-letter state
for US addresses.

## Fulfillment (shipping) policy

```bash
python3 ".../ebay_api.py" create-policy fulfillment '{
  "name": "MTGI Standard Shipping",
  "marketplaceId": "EBAY_US",
  "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
  "handlingTime": {"value": 2, "unit": "DAY"},
  "shippingOptions": [{
    "optionType": "DOMESTIC",
    "costType": "FLAT_RATE",
    "shippingServices": [{
      "shippingCarrierCode": "USPS",
      "shippingServiceCode": "USPSGround",
      "shippingCost": {"value": "12.00", "currency": "USD"},
      "freeShipping": false,
      "buyerResponsibleForShipping": false
    }]
  }]
}'
```

For free shipping set `"freeShipping": true` and omit `shippingCost`.

## Payment policy

Managed payments accounts need very little here.

```bash
python3 ".../ebay_api.py" create-policy payment '{
  "name": "MTGI Standard Payment",
  "marketplaceId": "EBAY_US",
  "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
  "immediatePay": true
}'
```

## Return policy

```bash
python3 ".../ebay_api.py" create-policy return '{
  "name": "MTGI 30-Day Returns",
  "marketplaceId": "EBAY_US",
  "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
  "returnsAccepted": true,
  "returnPeriod": {"value": 30, "unit": "DAY"},
  "returnMethod": "REPLACEMENT_OR_MONEY_BACK",
  "returnShippingCostPayer": "BUYER"
}'
```

For no returns, `{"returnsAccepted": false}` plus name, marketplaceId, and
categoryTypes.

## Editing

`edit-policy` maps to eBay's `PUT`, which is a **full replace, not a patch**.

1. Read the existing policy.
2. Merge the change into the complete object.
3. Send the whole thing.

Sending only the changed field wipes everything else on that policy — across
every listing using it.

```bash
python3 ".../ebay_api.py" edit-policy fulfillment 6100000000 '<complete policy object>'
```

## Common failures

| eBay error | Meaning |
|---|---|
| `20403` invalid category type | `categoryTypes` missing or wrong for the account |
| Duplicate policy name | Names must be unique per marketplace |
| Invalid shipping service code | Carrier/service pair isn't valid — check eBay's shipping service list |
| Location key already exists | Pick a different key, or edit the existing location |
