#!/usr/bin/env python3
"""The eBay Sell Inventory publish chain.

    1. PUT  /sell/inventory/v1/inventory_item/{sku}     create/replace the item
    2. POST /sell/inventory/v1/offer                    create the offer (or PUT an existing one)
    3. POST /sell/inventory/v1/offer/{id}/publish       go live

Idempotent by SKU: an already-published offer is returned as-is rather than
duplicated, so a retry after a network blip cannot double-list.

CLI:
    python publish.py validate  spec.json
    python publish.py dry-run   spec.json
    python publish.py publish   spec.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import ebay_api
from ebay_api import EbayApiError

MARKETPLACE_ID = "EBAY_US"
LISTING_FORMAT = "FIXED_PRICE"
LISTING_DURATION = "GTC"

# eBay condition enums. Left column is the vocabulary MTGI uses.
CONDITION_MAP = {
    "new": "NEW",
    "new_other": "NEW_OTHER",
    "refurbished": "SELLER_REFURBISHED",
    "seller_refurbished": "SELLER_REFURBISHED",
    "certified_refurbished": "CERTIFIED_REFURBISHED",
    "used_like_new": "USED_EXCELLENT",
    "used_excellent": "USED_EXCELLENT",
    "used_very_good": "USED_VERY_GOOD",
    "used_good": "USED_GOOD",
    "used_fair": "USED_ACCEPTABLE",
    "used_acceptable": "USED_ACCEPTABLE",
    "for_parts": "FOR_PARTS_OR_NOT_WORKING",
}

REQUIRED_FIELDS = ("sku", "title", "price", "categoryId", "condition")

EBAY_TITLE_MAX = 80

LEDGER_PATH = Path(
    os.environ.get("EBAY_LISTER_LEDGER", Path.home() / ".ebay-lister-listings.jsonl")
)


class SpecError(ValueError):
    """The listing spec is incomplete or malformed."""


def normalize_condition(value: str) -> str:
    """Map MTGI's condition vocabulary to eBay's enum, passing through enums."""
    key = (value or "").strip()
    if key.upper() in set(CONDITION_MAP.values()):
        return key.upper()
    mapped = CONDITION_MAP.get(key.lower())
    if not mapped:
        raise SpecError(
            f"Unknown condition '{value}'. Use one of: {sorted(CONDITION_MAP)}"
        )
    return mapped


def validate(spec: dict) -> list[str]:
    """Return a list of problems. Empty list means the spec is publishable."""
    problems = []
    for field in REQUIRED_FIELDS:
        if not spec.get(field):
            problems.append(f"missing required field: {field}")

    title = spec.get("title", "")
    if len(title) > EBAY_TITLE_MAX:
        problems.append(f"title is {len(title)} chars; eBay's limit is {EBAY_TITLE_MAX}")

    if spec.get("condition"):
        try:
            normalize_condition(spec["condition"])
        except SpecError as e:
            problems.append(str(e))

    if not spec.get("imageUrls"):
        problems.append("no imageUrls -- eBay requires at least one picture")
    else:
        non_https = [u for u in spec["imageUrls"] if not u.startswith("https://")]
        if non_https:
            problems.append(f"image URLs must be https: {non_https}")

    if not spec.get("merchantLocationKey"):
        problems.append("missing merchantLocationKey -- publish will fail without one")

    policies = ("fulfillmentPolicyId", "paymentPolicyId", "returnPolicyId")
    missing_policies = [p for p in policies if not spec.get(p)]
    if missing_policies:
        problems.append(f"missing business policies: {', '.join(missing_policies)}")

    return problems


def build_inventory_item_payload(spec: dict) -> dict:
    product: dict = {"title": spec["title"]}
    if spec.get("description"):
        product["description"] = spec["description"]
    if spec.get("brand"):
        product["brand"] = spec["brand"]
    # MPN strings are preserved verbatim -- exact case and hyphens.
    if spec.get("mpn"):
        product["mpn"] = spec["mpn"]
    # Product identifiers. Some categories (e.g. 11175 Network Media Converters)
    # refuse to publish without a UPC. eBay wants each as a list of strings.
    for ident in ("upc", "ean", "isbn"):
        if spec.get(ident):
            v = spec[ident]
            product[ident] = [str(x) for x in v] if isinstance(v, list) else [str(v)]
    if spec.get("imageUrls"):
        product["imageUrls"] = list(spec["imageUrls"])
    if spec.get("aspects"):
        # eBay expects aspects as {name: [value, ...]}.
        product["aspects"] = {
            k: v if isinstance(v, list) else [str(v)] for k, v in spec["aspects"].items()
        }

    payload = {
        "product": product,
        "condition": normalize_condition(spec["condition"]),
        "availability": {
            "shipToLocationAvailability": {"quantity": int(spec.get("quantity", 1))}
        },
    }
    if spec.get("conditionDescription"):
        payload["conditionDescription"] = spec["conditionDescription"]
    # Optional. eBay uses it to pre-fill label purchase and to quote any
    # calculated-cost service on the fulfillment policy. Passed through as-is
    # in eBay's own shape: {"weight": {"value", "unit"}, "dimensions": {...}}.
    if spec.get("packageWeightAndSize"):
        payload["packageWeightAndSize"] = spec["packageWeightAndSize"]
    return payload


def build_offer_payload(spec: dict) -> dict:
    payload = {
        "sku": spec["sku"],
        "marketplaceId": MARKETPLACE_ID,
        "format": LISTING_FORMAT,
        "listingDuration": LISTING_DURATION,
        "categoryId": str(spec["categoryId"]),
        "merchantLocationKey": spec["merchantLocationKey"],
        "availableQuantity": int(spec.get("quantity", 1)),
        "pricingSummary": {
            "price": {
                "value": str(spec["price"]),
                "currency": spec.get("currency", "USD"),
            }
        },
        "listingPolicies": {
            "fulfillmentPolicyId": spec.get("fulfillmentPolicyId"),
            "paymentPolicyId": spec.get("paymentPolicyId"),
            "returnPolicyId": spec.get("returnPolicyId"),
        },
    }

    # Best Offer lets a price come down quietly instead of via a public markdown,
    # which matters on slow-moving parts where the asking price is the ceiling.
    if spec.get("bestOfferEnabled"):
        terms: dict = {"bestOfferEnabled": True}
        if spec.get("autoAcceptPrice"):
            terms["autoAcceptPrice"] = {
                "value": str(spec["autoAcceptPrice"]),
                "currency": spec.get("currency", "USD"),
            }
        if spec.get("autoDeclinePrice"):
            terms["autoDeclinePrice"] = {
                "value": str(spec["autoDeclinePrice"]),
                "currency": spec.get("currency", "USD"),
            }
        payload["listingPolicies"]["bestOfferTerms"] = terms
    if spec.get("listingDescription") or spec.get("description"):
        payload["listingDescription"] = spec.get("listingDescription") or spec["description"]
    return payload


def find_existing_offer(sku: str) -> dict | None:
    """Look up an offer already attached to this SKU."""
    try:
        data = ebay_api.request(
            "GET",
            f"/sell/inventory/v1/offer?sku={urllib.parse.quote(sku)}&marketplace_id={MARKETPLACE_ID}",
        )
    except EbayApiError as e:
        # eBay returns 404 when the SKU has no offers. That is not an error here.
        if e.status == 404:
            return None
        raise
    offers = (data or {}).get("offers", [])
    return offers[0] if offers else None


def _append_ledger(record: dict) -> None:
    """Append-only local record of what was listed. Cheap audit, no database."""
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # Never fail a live listing because the ledger is unwritable.


def publish(spec: dict) -> dict:
    problems = validate(spec)
    if problems:
        raise SpecError("Spec is not publishable:\n  " + "\n  ".join(problems))

    sku = spec["sku"]

    # ── Idempotency: an already-live offer is returned, not duplicated ────────
    existing = find_existing_offer(sku)
    if existing and existing.get("status") == "PUBLISHED" and existing.get("listingId"):
        return {
            "success": True,
            "already_published": True,
            "sku": sku,
            "offerId": existing.get("offerId"),
            "listingId": existing["listingId"],
            "listingUrl": f"https://www.ebay.com/itm/{existing['listingId']}",
        }

    # ── Step 1: create or replace the inventory item ──────────────────────────
    ebay_api.request(
        "PUT",
        f"/sell/inventory/v1/inventory_item/{urllib.parse.quote(sku)}",
        build_inventory_item_payload(spec),
    )

    # ── Step 2: create the offer, or update the one that already exists ───────
    offer_payload = build_offer_payload(spec)
    if existing and existing.get("offerId"):
        offer_id = existing["offerId"]
        ebay_api.request(
            "PUT", f"/sell/inventory/v1/offer/{urllib.parse.quote(offer_id)}", offer_payload
        )
    else:
        created = ebay_api.request("POST", "/sell/inventory/v1/offer", offer_payload)
        offer_id = (created or {}).get("offerId")
        if not offer_id:
            raise EbayApiError(0, "/sell/inventory/v1/offer", "no offerId in response")

    # ── Step 3: publish ──────────────────────────────────────────────────────
    published = ebay_api.request(
        "POST", f"/sell/inventory/v1/offer/{urllib.parse.quote(offer_id)}/publish"
    )
    listing_id = (published or {}).get("listingId")
    result = {
        "success": bool(listing_id),
        "already_published": False,
        "sku": sku,
        "offerId": offer_id,
        "listingId": listing_id,
        "listingUrl": f"https://www.ebay.com/itm/{listing_id}" if listing_id else None,
        "warnings": (published or {}).get("warnings", []),
    }
    _append_ledger(
        {
            "listed_at": datetime.now(timezone.utc).isoformat(),
            # The team shares one eBay seller login, so eBay itself cannot say
            # who published a listing. `listed_by` is the only attribution.
            "listed_by": spec.get("listed_by") or os.environ.get("USER") or "unknown",
            "sku": sku,
            "title": spec["title"],
            "price": str(spec["price"]),
            "currency": spec.get("currency", "USD"),
            "quantity": int(spec.get("quantity", 1)),
            "categoryId": str(spec["categoryId"]),
            "mpn": spec.get("mpn"),
            "offerId": offer_id,
            "listingId": listing_id,
            "listingUrl": result["listingUrl"],
            "imageUrls": spec.get("imageUrls", []),
        }
    )
    return result


def _load(path: str) -> dict:
    return json.loads(Path(path).expanduser().read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish an eBay listing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "dry-run", "publish"):
        p = sub.add_parser(name)
        p.add_argument("spec")
    args = parser.parse_args(argv)

    try:
        spec = _load(args.spec)
        if args.cmd == "validate":
            problems = validate(spec)
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
            return 0 if not problems else 1
        if args.cmd == "dry-run":
            problems = validate(spec)
            print(
                json.dumps(
                    {
                        "ok": not problems,
                        "problems": problems,
                        "inventory_item": build_inventory_item_payload(spec),
                        "offer": build_offer_payload(spec),
                    },
                    indent=2,
                )
            )
            return 0 if not problems else 1
        print(json.dumps(publish(spec), indent=2))
    except (SpecError, EbayApiError, json.JSONDecodeError, OSError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
