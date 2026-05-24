#!/usr/bin/env python3
"""eBay Browse API client — structured item-aspect enrichment (v0.8 Tier 3).

Replaces BrokerBin as the structured spec source. Uses the **Browse API**
(guest/application access), NOT the Sell API — the Sell account that may already
be connected manages a store and cannot search the marketplace, so this needs
its own application keyset (`EBAY_APP_ID` / `EBAY_CERT_ID`).

Auth: OAuth2 client-credentials (application token), cached ~2h in the workspace
cache dir. No user-consent/redirect flow is needed for Browse guest access.

    POST https://api.ebay.com/identity/v1/oauth2/token
      grant_type=client_credentials & scope=.../oauth/api_scope
      Authorization: Basic base64(APP_ID:CERT_ID)

Spec source: for the top relevant `item_summary/search?q={MPN}` results, fetch
`item/{id}` and read `localizedAspects` (Brand, Capacity, Interface, Form Factor,
Type, …) plus `condition`. Consensus = modal value per field across listings;
confidence = agreement ratio. Manufacturer values are collapsed through
`manufacturer_aliases` (WD / Western Digital / HGST → Western Digital) before
voting. A field is only reported when ≥2 listings corroborate it.

Out of scope: sold/completed comps (require the Marketplace Insights API, which
has restricted access). v0.8 uses active-listing aspects only — sufficient for
filling specs.

Env vars (override the credential store when set):
  EBAY_APP_ID, EBAY_CERT_ID   application keyset (required to enable the tier)
  EBAY_BROWSE_BASE_URL        optional override of the API base
  EBAY_MOCK=1                 optional: skip the network, return synthetic data
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
DEFAULT_BASE_URL = "https://api.ebay.com/buy/browse/v1"
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE_ID = "EBAY_US"
REQUEST_TIMEOUT_S = 15
DEFAULT_SEARCH_LIMIT = 10
ITEM_DETAIL_TOP = 6          # how many of the top results to fetch aspects for
MIN_CORROBORATION = 2        # a field needs ≥2 agreeing listings to be reported
TOKEN_CACHE_FILENAME = "ebay-oauth-token.json"
TOKEN_SAFETY_MARGIN_S = 120  # refresh a bit early to avoid edge-of-expiry 401s

# Internal field names (matching the enrichment cascade) the aspects map to.
_SPEC_FIELDS = ("size", "interface", "drive_type", "form_factor", "manufacturer", "condition")


class EbayError(Exception):
    pass


class EbayAuthError(EbayError):
    pass


def _classify_aspect(name: str) -> str | None:
    """Map an eBay aspect name to an internal field, or None if irrelevant."""
    n = (name or "").strip().lower()
    if "form factor" in n:
        return "form_factor"
    if "capacity" in n:
        return "size"
    if "interface" in n:
        return "interface"
    if "brand" in n or "manufacturer" in n:
        return "manufacturer"
    if "type" in n:  # "Type", "Drive Type", "Media Type"
        return "drive_type"
    return None


def _token_cache_path() -> Path:
    explicit = os.environ.get("RFQ_CACHE_DIR")
    if explicit:
        base = Path(explicit)
    else:
        try:
            from workspace import workspace_dir
            base = workspace_dir() / ".rfq-cache"
        except Exception:
            base = Path.home() / ".cache" / "rfq-normalizer"
    base.mkdir(parents=True, exist_ok=True)
    return base / TOKEN_CACHE_FILENAME


class EbayBrowseClient:
    def __init__(self, app_id: str, cert_id: str,
                 base_url: str = DEFAULT_BASE_URL, use_mock: bool = False):
        self.app_id = app_id
        self.cert_id = cert_id
        self.base_url = base_url.rstrip("/")
        self.use_mock = use_mock

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_credentials(cls) -> "EbayBrowseClient | None":
        """Build a client from the credential store. Returns None when the app
        keyset isn't configured (and mock mode is off), disabling the tier."""
        try:
            from credentials import get as _cred_get
        except ImportError:
            _cred_get = lambda _name: None  # noqa: E731

        app_id = _cred_get("ebay_app_id")
        cert_id = _cred_get("ebay_cert_id")
        if (not app_id or not cert_id) and os.environ.get("EBAY_MOCK") != "1":
            return None
        return cls(
            app_id=app_id or "mock",
            cert_id=cert_id or "mock",
            base_url=os.environ.get("EBAY_BROWSE_BASE_URL", DEFAULT_BASE_URL),
            use_mock=os.environ.get("EBAY_MOCK") == "1",
        )

    # ── Public: consensus spec lookup ─────────────────────────────────────────

    def search_specs(self, mpn: str, limit: int = DEFAULT_SEARCH_LIMIT,
                     inspect: int = ITEM_DETAIL_TOP) -> dict[str, Any]:
        """Search active listings for an MPN and return consensus item aspects.

        Returns {source, fields, field_confidence, raw}. `fields` maps internal
        names (size/interface/drive_type/form_factor/manufacturer/condition) to
        the modal value across inspected listings; only fields with ≥2 agreeing
        listings are included. Never raises for a single bad item — degrades to
        whatever it could read.
        """
        if self.use_mock:
            return self._mock_specs(mpn)

        summaries = self._search_raw(mpn, limit) or []
        mpn_u = mpn.upper()
        relevant = [s for s in summaries if mpn_u in str(s.get("title") or "").upper()] or summaries
        item_ids = [s.get("itemId") for s in relevant[:inspect] if s.get("itemId")]

        votes: dict[str, Counter] = {f: Counter() for f in _SPEC_FIELDS}
        examples: dict[str, dict[str, str]] = {f: {} for f in _SPEC_FIELDS}
        inspected = 0

        for iid in item_ids:
            try:
                detail = self._item_raw(iid) or {}
            except EbayError:
                continue
            inspected += 1
            for asp in detail.get("localizedAspects") or []:
                field = _classify_aspect(str(asp.get("name") or ""))
                value = str(asp.get("value") or "").strip()
                if not field or not value:
                    continue
                self._cast_vote(votes, examples, field, value)
            cond = detail.get("condition")
            if cond:
                self._cast_vote(votes, examples, "condition", str(cond))

        fields: dict[str, Any] = {}
        confidence: dict[str, float] = {}
        for field, counter in votes.items():
            if not counter:
                continue
            key, count = counter.most_common(1)[0]
            if count < MIN_CORROBORATION:
                continue
            fields[field] = examples[field][key]
            confidence[field] = round(min(0.95, count / max(inspected, 1)), 3)

        return {
            "source": "ebay",
            "fields": fields,
            "field_confidence": confidence,
            "raw": {"matched": len(summaries), "inspected": inspected, "item_ids": item_ids},
        }

    @staticmethod
    def _cast_vote(votes, examples, field, value):
        """Record one listing's value for a field, collapsing manufacturer
        aliases and condition words to canonical forms before voting."""
        if field == "manufacturer":
            try:
                from manufacturer_aliases import normalize_manufacturer
                canon = normalize_manufacturer(value)
            except ImportError:
                canon = value.strip()
            if not canon:
                return
            votes[field][canon] += 1
            examples[field][canon] = canon
        elif field == "condition":
            try:
                from normalize_condition import normalize_condition
                canon = normalize_condition(value)
            except ImportError:
                canon = None
            if not canon:
                return
            votes[field][canon] += 1
            examples[field][canon] = canon
        else:
            collapsed = " ".join(value.split())
            key = collapsed.casefold()
            votes[field][key] += 1
            examples[field].setdefault(key, collapsed)

    def test_connection(self) -> tuple[bool, str | None]:
        try:
            self._search_raw("test", 1)
            return True, None
        except EbayError as e:
            return False, str(e)

    # ── Internals: OAuth + HTTP ────────────────────────────────────────────────

    def _get_token(self) -> str:
        cached = self._read_token_cache()
        if cached:
            return cached
        creds = base64.b64encode(f"{self.app_id}:{self.cert_id}".encode()).decode()
        data = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": OAUTH_SCOPE}
        ).encode()
        req = urllib.request.Request(
            OAUTH_URL, data=data, method="POST",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise EbayAuthError(f"eBay OAuth error ({e.code}): {_read_err(e)}") from e
        except urllib.error.URLError as e:
            raise EbayError(f"eBay OAuth network error: {e.reason}") from e
        token = body.get("access_token")
        if not token:
            raise EbayAuthError("eBay OAuth response had no access_token")
        self._write_token_cache(token, int(body.get("expires_in", 7200)))
        return token

    def _read_token_cache(self) -> str | None:
        try:
            data = json.loads(_token_cache_path().read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("expires_at", 0) - TOKEN_SAFETY_MARGIN_S > time.time():
            return data.get("token")
        return None

    def _write_token_cache(self, token: str, expires_in: int) -> None:
        try:
            _token_cache_path().write_text(json.dumps(
                {"token": token, "expires_at": time.time() + expires_in}
            ))
        except OSError:
            pass  # caching is best-effort; a write failure just means re-auth

    def _browse_get(self, endpoint: str) -> dict[str, Any]:
        token = self._get_token()
        req = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise EbayAuthError(f"eBay Browse auth error ({e.code}): {_read_err(e)}") from e
            raise EbayError(f"eBay Browse API {e.code}: {_read_err(e)}") from e
        except urllib.error.URLError as e:
            raise EbayError(f"eBay Browse network error: {e.reason}") from e

    def _search_raw(self, query: str, limit: int) -> list[dict]:
        params = urllib.parse.urlencode({"q": query, "limit": limit})
        data = self._browse_get(f"/item_summary/search?{params}")
        return data.get("itemSummaries") or []

    def _item_raw(self, item_id: str) -> dict:
        return self._browse_get(f"/item/{urllib.parse.quote(item_id, safe='')}")

    # ── Mock ───────────────────────────────────────────────────────────────────

    def _mock_specs(self, mpn: str) -> dict[str, Any]:
        return {
            "source": "ebay",
            "fields": {"manufacturer": "Seagate", "drive_type": "Hard Drive"},
            "field_confidence": {"manufacturer": 0.9, "drive_type": 0.9},
            "raw": {"mock": True, "query": mpn},
        }


def _read_err(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:300]
    except Exception:
        return e.reason if hasattr(e, "reason") else "unknown error"


def search_specs(mpn: str, limit: int = DEFAULT_SEARCH_LIMIT) -> dict[str, Any]:
    """Module-level convenience: build a client from credentials and look up an
    MPN. Degrades cleanly (empty fields, no crash) when eBay isn't configured."""
    client = EbayBrowseClient.from_credentials()
    if client is None:
        return {"source": "ebay", "fields": {}, "field_confidence": {},
                "raw": {"note": "not_configured"}}
    return client.search_specs(mpn, limit=limit)


def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mpn")
    ap.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT)
    ap.add_argument("--test-connection", action="store_true")
    args = ap.parse_args()

    client = EbayBrowseClient.from_credentials()
    if client is None:
        print("ERROR: eBay credentials not configured. Run /rfq-setup or set "
              "EBAY_APP_ID + EBAY_CERT_ID (or EBAY_MOCK=1).", file=sys.stderr)
        return 2
    if args.test_connection:
        ok, err = client.test_connection()
        print(json.dumps({"ok": ok, "error": err}))
        return 0 if ok else 1
    json.dump(client.search_specs(args.mpn, limit=args.limit), sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
