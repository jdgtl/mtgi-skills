#!/usr/bin/env python3
"""Thin eBay REST client + the lookups a listing needs. Stdlib only.

Covers the read/write surface around a listing that is NOT the publish chain
itself (see publish.py): category resolution, required aspects, business
policies, and inventory locations -- including creating and editing them.

CLI:
    python ebay_api.py suggest-category "Corsair 64GB DDR4 RAM kit"
    python ebay_api.py aspects 170083
    python ebay_api.py policies
    python ebay_api.py create-policy fulfillment '<json>'
    python ebay_api.py edit-policy fulfillment <policyId> '<json>'
    python ebay_api.py locations
    python ebay_api.py create-location <key> '<json>'
    python ebay_api.py request GET /sell/inventory/v1/offer?sku=FOO
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import auth

MARKETPLACE_ID = "EBAY_US"
CONTENT_LANGUAGE = "en-US"
REQUEST_TIMEOUT_S = 45

# Account API resource names, keyed by the short name the skill uses.
POLICY_RESOURCES = {
    "fulfillment": "fulfillment_policy",
    "payment": "payment_policy",
    "return": "return_policy",
}


class EbayApiError(RuntimeError):
    """An eBay API call failed. Carries status and eBay's own error payload."""

    def __init__(self, status: int, path: str, payload: str):
        self.status = status
        self.path = path
        self.payload = payload
        super().__init__(f"eBay {status} on {path}: {payload[:600]}")


def request(method: str, path: str, body: dict | None = None) -> dict | None:
    """Call an eBay REST endpoint with a fresh access token.

    Returns the decoded JSON body, or None for 204/empty responses.
    """
    url = path if path.startswith("http") else f"{auth.api_base()}{path}"
    headers = {
        "Authorization": f"Bearer {auth.get_access_token()}",
        "Accept": "application/json",
        # Required by the Account API on writes; harmless elsewhere.
        "Content-Language": CONTENT_LANGUAGE,
        "Accept-Language": CONTENT_LANGUAGE,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode().strip()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise EbayApiError(e.code, path, e.read().decode(errors="replace")) from e
    except urllib.error.URLError as e:
        raise EbayApiError(0, path, f"network error: {e.reason}") from e


# ── Taxonomy ──────────────────────────────────────────────────────────────────

_tree_id_cache: str | None = None


def default_category_tree_id() -> str:
    global _tree_id_cache
    if _tree_id_cache is None:
        data = request(
            "GET",
            f"/commerce/taxonomy/v1/get_default_category_tree_id?marketplace_id={MARKETPLACE_ID}",
        )
        _tree_id_cache = (data or {}).get("categoryTreeId", "0")
    return _tree_id_cache


def suggest_category(query: str) -> list[dict]:
    """eBay's own category suggestions for a free-text product description.

    Always prefer these over a hardcoded map -- eBay reorganizes categories,
    and required aspects are per-category.
    """
    tree = default_category_tree_id()
    q = urllib.parse.quote(query)
    data = request(
        "GET",
        f"/commerce/taxonomy/v1/category_tree/{tree}/get_category_suggestions?q={q}",
    )
    out = []
    for s in (data or {}).get("categorySuggestions", []):
        cat = s.get("category", {})
        ancestors = [a.get("categoryName") for a in s.get("categoryTreeNodeAncestors", [])]
        out.append(
            {
                "categoryId": cat.get("categoryId"),
                "categoryName": cat.get("categoryName"),
                "path": " > ".join(reversed([a for a in ancestors if a])),
            }
        )
    return out


def category_aspects(category_id: str) -> dict:
    """Item aspects for a category, split into required and optional.

    Publishing fails if a required aspect is missing, so the skill must fill
    every entry in `required` before it calls publish.
    """
    tree = default_category_tree_id()
    data = request(
        "GET",
        f"/commerce/taxonomy/v1/category_tree/{tree}/get_item_aspects_for_category"
        f"?category_id={urllib.parse.quote(category_id)}",
    )
    required, optional = [], []
    for aspect in (data or {}).get("aspects", []):
        constraint = aspect.get("aspectConstraint", {})
        entry = {
            "name": aspect.get("localizedAspectName"),
            "cardinality": constraint.get("itemToAspectCardinality"),
            "mode": constraint.get("aspectMode"),
            "values": [v.get("localizedValue") for v in aspect.get("aspectValues", [])][:40],
        }
        (required if constraint.get("aspectRequired") else optional).append(entry)
    return {"categoryId": category_id, "required": required, "optional": optional}


# ── Business policies ─────────────────────────────────────────────────────────


def _policy_resource(kind: str) -> str:
    resource = POLICY_RESOURCES.get(kind)
    if not resource:
        raise ValueError(f"Unknown policy kind '{kind}'. Use one of {sorted(POLICY_RESOURCES)}.")
    return resource


# Response array key and ID field differ per policy family.
POLICY_RESPONSE_KEYS = {
    "fulfillment": ("fulfillmentPolicies", "fulfillmentPolicyId"),
    "payment": ("paymentPolicies", "paymentPolicyId"),
    "return": ("returnPolicies", "returnPolicyId"),
}


def list_policies() -> dict:
    """All three policy families in one shot, trimmed to id + name.

    A failure in one family is reported inline rather than aborting the others,
    so the skill can still show what IS configured.
    """
    out: dict[str, list[dict]] = {}
    for kind, resource in POLICY_RESOURCES.items():
        array_key, id_field = POLICY_RESPONSE_KEYS[kind]
        try:
            data = request("GET", f"/sell/account/v1/{resource}?marketplace_id={MARKETPLACE_ID}")
        except EbayApiError as e:
            out[kind] = [{"error": e.payload[:300]}]
            continue
        out[kind] = [
            {
                "policyId": p.get(id_field),
                "name": p.get("name"),
                "description": p.get("description"),
            }
            for p in (data or {}).get(array_key, [])
        ]
    return out


def create_policy(kind: str, payload: dict) -> dict | None:
    """Create a business policy. payload must include marketplaceId + name."""
    resource = _policy_resource(kind)
    payload.setdefault("marketplaceId", MARKETPLACE_ID)
    return request("POST", f"/sell/account/v1/{resource}", payload)


def edit_policy(kind: str, policy_id: str, payload: dict) -> dict | None:
    """Replace a business policy. eBay's PUT is a full replace, not a patch --
    send the complete policy object, not just the changed fields."""
    resource = _policy_resource(kind)
    payload.setdefault("marketplaceId", MARKETPLACE_ID)
    return request("PUT", f"/sell/account/v1/{resource}/{urllib.parse.quote(policy_id)}", payload)


# ── Inventory locations ───────────────────────────────────────────────────────


def list_locations() -> list[dict]:
    data = request("GET", "/sell/inventory/v1/location")
    return [
        {
            "merchantLocationKey": loc.get("merchantLocationKey"),
            "name": loc.get("name"),
            "status": loc.get("merchantLocationStatus"),
            "address": (loc.get("location") or {}).get("address"),
        }
        for loc in (data or {}).get("locations", [])
    ]


def create_location(key: str, payload: dict) -> dict | None:
    """Create an inventory location. Required before any offer can publish."""
    return request(
        "POST", f"/sell/inventory/v1/location/{urllib.parse.quote(key)}", payload
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eBay lookups for ebay-lister")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("suggest-category")
    sc.add_argument("query")
    asp = sub.add_parser("aspects")
    asp.add_argument("category_id")
    sub.add_parser("policies")
    cp = sub.add_parser("create-policy")
    cp.add_argument("kind", choices=sorted(POLICY_RESOURCES))
    cp.add_argument("payload_json")
    ep = sub.add_parser("edit-policy")
    ep.add_argument("kind", choices=sorted(POLICY_RESOURCES))
    ep.add_argument("policy_id")
    ep.add_argument("payload_json")
    sub.add_parser("locations")
    cl = sub.add_parser("create-location")
    cl.add_argument("key")
    cl.add_argument("payload_json")
    rq = sub.add_parser("request")
    rq.add_argument("method")
    rq.add_argument("path")
    rq.add_argument("payload_json", nargs="?")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "suggest-category":
            result = suggest_category(args.query)
        elif args.cmd == "aspects":
            result = category_aspects(args.category_id)
        elif args.cmd == "policies":
            result = list_policies()
        elif args.cmd == "create-policy":
            result = create_policy(args.kind, json.loads(args.payload_json))
        elif args.cmd == "edit-policy":
            result = edit_policy(args.kind, args.policy_id, json.loads(args.payload_json))
        elif args.cmd == "locations":
            result = list_locations()
        elif args.cmd == "create-location":
            result = create_location(args.key, json.loads(args.payload_json))
        elif args.cmd == "request":
            body = json.loads(args.payload_json) if args.payload_json else None
            result = request(args.method.upper(), args.path, body)
        print(json.dumps(result, indent=2))
    except (EbayApiError, auth.AuthError, ValueError, json.JSONDecodeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
