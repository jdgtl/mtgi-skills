#!/usr/bin/env python3
"""BrokerBin Search API v2 client (Python port of src/lib/integrations/brokerbin/client.ts).

Endpoints:
  GET /api/v2/part/search?query={mpn}&size={n}&priced={0|1}
  GET /api/v2/part/history/stats?query={mpn}

Auth: Bearer token via Authorization header. Optional `login` header for the
acting user (some accounts require it).

Credentials are resolved by `credentials.py` (env → Keychain → file).
Set them with `python credentials.py set brokerbin_api_key <value>` or run
the /rfq-setup slash command on first install.

Env vars (override Keychain when set):
  BROKERBIN_API_KEY     required to enable Tier 2 enrichment
  BROKERBIN_LOGIN       optional: acting-user login (some accounts require this)
  BROKERBIN_BASE_URL    optional: defaults to https://search.brokerbin.com
  BROKERBIN_MOCK=1      optional: skip the network call, return synthetic data for dev

Usage as a library:
    from brokerbin_client import BrokerBinClient
    client = BrokerBinClient.from_credentials()
    if client is None:
        ...  # tier disabled (no credentials anywhere)
    result = client.search("UCS-SD16TBKS4-EV", size=10, priced=True)

Usage as a CLI (for quick testing):
    BROKERBIN_API_KEY=... python brokerbin_client.py UCS-SD16TBKS4-EV
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Any

DEFAULT_BASE_URL = "https://search.brokerbin.com"
DEFAULT_RATE_LIMIT_MS = 500
MAX_RETRIES = 3
REQUEST_TIMEOUT_S = 15


@dataclass
class BrokerBinListing:
    id: str
    part_number: str
    description: str
    condition: str
    manufacturer: str
    price: float
    quantity: int
    company: str
    country: str | None = None
    state: str | None = None
    age: str | None = None
    age_in_days: int | None = None
    clei: str | None = None


@dataclass
class BrokerBinSearchResult:
    total_results: int
    listings: list[BrokerBinListing]
    offset: int
    has_more: bool
    meta: dict[str, Any] = field(default_factory=dict)


class BrokerBinError(Exception):
    pass


class BrokerBinAuthError(BrokerBinError):
    pass


class BrokerBinClient:
    def __init__(
        self,
        api_key: str,
        login: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        rate_limit_ms: int = DEFAULT_RATE_LIMIT_MS,
        use_mock: bool = False,
    ):
        self.api_key = api_key
        self.login = login
        self.base_url = base_url.rstrip("/")
        self.rate_limit_ms = rate_limit_ms
        self.use_mock = use_mock
        self._last_request_at: float = 0.0

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_credentials(cls) -> "BrokerBinClient | None":
        """Build a client from the credentials store (env > Keychain > file).

        Returns None if no API key is available anywhere AND mock mode is off,
        which silently disables the BrokerBin tier in the enrichment cascade.
        """
        # Local import avoids a hard dependency at module load — `credentials`
        # is sibling-imported via sys.path manipulation in enrich_mpn.py.
        try:
            from credentials import get as _cred_get
        except ImportError:
            _cred_get = lambda _name: None  # noqa: E731 — narrow scope

        api_key = _cred_get("brokerbin_api_key")
        if not api_key and os.environ.get("BROKERBIN_MOCK") != "1":
            return None
        return cls(
            api_key=api_key or "mock",
            login=_cred_get("brokerbin_login"),
            base_url=os.environ.get("BROKERBIN_BASE_URL", DEFAULT_BASE_URL),
            use_mock=os.environ.get("BROKERBIN_MOCK") == "1",
        )

    @classmethod
    def from_env(cls) -> "BrokerBinClient | None":
        """Backward-compat alias for from_credentials()."""
        return cls.from_credentials()

    # ── Part search ──────────────────────────────────────────────────────────

    def search(
        self,
        part_number: str,
        size: int = 10,
        offset: int = 0,
        priced: bool = True,
        fuzziness: float | None = None,
        mfg: list[str] | None = None,
        cond: list[str] | None = None,
    ) -> BrokerBinSearchResult:
        # BrokerBin enforces size >= 10 on /part/search (422 otherwise).
        size = max(10, size)

        if self.use_mock:
            return self._mock_search(part_number, size, offset)

        params = urllib.parse.urlencode(
            [("query", part_number), ("size", size), ("offset", offset)]
            + ([("priced", "1")] if priced else [])
            + ([("fuzziness", fuzziness)] if fuzziness is not None else [])
            + [("mfg[]", m) for m in (mfg or [])]
            + [("cond[]", c) for c in (cond or [])]
        )
        raw = self._request_json(f"/api/v2/part/search?{params}")

        listings = []
        for idx, item in enumerate(raw.get("data") or []):
            listings.append(self._parse_listing(item, part_number, idx))

        total = raw.get("meta", {}).get("total")
        if not isinstance(total, int):
            total = len(listings)

        return BrokerBinSearchResult(
            total_results=total,
            listings=listings,
            offset=offset,
            has_more=offset + size < total,
            meta=raw.get("meta", {}) or {},
        )

    # ── Connection test ──────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str | None]:
        try:
            self.search("test", size=1)
            return True, None
        except BrokerBinError as e:
            return False, str(e)

    # ── Internals ────────────────────────────────────────────────────────────

    def _parse_listing(self, item: dict, fallback_part: str, idx: int) -> BrokerBinListing:
        def s(k: str, default: str = "") -> str:
            v = item.get(k)
            return str(v) if v is not None else default

        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            qty = int(item.get("qty") or item.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0

        age_in_days_raw = item.get("age_in_days")
        try:
            age_in_days = int(age_in_days_raw) if age_in_days_raw is not None else None
        except (TypeError, ValueError):
            age_in_days = None
        age = f"{age_in_days}d" if age_in_days is not None else (s("age") or None)

        return BrokerBinListing(
            id=s("id", f"bb-{fallback_part}-{idx}"),
            part_number=s("part") or s("partsno") or s("part_number") or fallback_part,
            description=s("description"),
            condition=s("cond") or s("condition") or "Unknown",
            manufacturer=s("mfg") or s("manufacturer"),
            price=price,
            quantity=qty,
            company=s("company") or s("seller"),
            country=item.get("country") and str(item["country"]) or None,
            state=item.get("state") and str(item["state"]) or None,
            age=age,
            age_in_days=age_in_days,
            clei=item.get("clei") and str(item["clei"]) or None,
        )

    def _request_json(self, endpoint: str) -> dict[str, Any]:
        self._respect_rate_limit()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "rfq-normalizer/0.1",
        }
        if self.login:
            headers["login"] = self.login

        url = f"{self.base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            self._last_request_at = time.monotonic()
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                if e.code in (401, 403):
                    raise BrokerBinAuthError(
                        f"BrokerBin API auth error ({e.code}): {body or 'invalid API key'}"
                    ) from e
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", "5"))
                    time.sleep(retry_after)
                    continue
                last_error = BrokerBinError(f"BrokerBin API {e.code}: {body or e.reason}")
            except urllib.error.URLError as e:
                last_error = BrokerBinError(f"BrokerBin network error: {e.reason}")
            except Exception as e:  # timeout, json error, etc.
                last_error = BrokerBinError(f"BrokerBin request failed: {e}")

            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

        raise last_error or BrokerBinError("BrokerBin request failed after retries")

    def _respect_rate_limit(self) -> None:
        elapsed_ms = (time.monotonic() - self._last_request_at) * 1000
        if elapsed_ms < self.rate_limit_ms:
            time.sleep((self.rate_limit_ms - elapsed_ms) / 1000)

    def _mock_search(self, part: str, size: int, offset: int) -> BrokerBinSearchResult:
        conditions = ["New", "Refurbished", "Used"]
        mfgs = ["Dell", "HP", "Cisco", "Intel", "Samsung"]
        companies = ["TechVault Inc", "ServerParts Co", "IT Surplus Global", "NetHardware LLC"]
        listings = [
            BrokerBinListing(
                id=f"mock-{part}-{i}",
                part_number=part,
                description=f"{part} - Enterprise Grade Component",
                condition=conditions[i % len(conditions)],
                manufacturer=mfgs[i % len(mfgs)],
                price=round(50 + random.random() * 500, 2),
                quantity=random.randint(1, 100),
                company=companies[i % len(companies)],
                country="US",
                age=f"{random.randint(0, 30)}d",
            )
            for i in range(size)
        ]
        return BrokerBinSearchResult(
            total_results=len(listings),
            listings=listings,
            offset=offset,
            has_more=False,
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mpn")
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--test-connection", action="store_true")
    args = ap.parse_args()

    client = BrokerBinClient.from_credentials()
    if client is None:
        print(
            "ERROR: BrokerBin credentials not configured. "
            "Run /rfq-setup or set BROKERBIN_API_KEY (or BROKERBIN_MOCK=1).",
            file=sys.stderr,
        )
        return 2

    if args.test_connection:
        ok, err = client.test_connection()
        print(json.dumps({"ok": ok, "error": err}))
        return 0 if ok else 1

    result = client.search(args.mpn, size=args.size)
    out = {
        "total_results": result.total_results,
        "has_more": result.has_more,
        "listings": [asdict(l) for l in result.listings],
        "meta": result.meta,
    }
    json.dump(out, sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
