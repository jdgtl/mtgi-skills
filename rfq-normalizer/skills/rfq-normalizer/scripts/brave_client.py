#!/usr/bin/env python3
"""Brave Search API v1 client.

Used by Tier 5 of the enrichment cascade — catches vendor-internal SKUs,
OEM cross-references, and parts that aren't in the BrokerBin index.

Endpoint:
  GET https://api.search.brave.com/res/v1/web/search?q={q}&count={n}
  Header: X-Subscription-Token: {api_key}

Credentials are resolved by `credentials.py` (env > keyring). Set them with
`python credentials.py set brave_search_api_key <value>` or run /rfq-setup.

Free tier limit: 2000 queries/month, 1 req/sec. The rate-limit guard below
enforces 1 req/sec on the client side; the 429 retry handles the rare burst.

Env vars (override keyring when set):
  BRAVE_SEARCH_API_KEY    required to enable Tier 5
  BRAVE_SEARCH_BASE_URL   optional: defaults to https://api.search.brave.com
  BRAVE_MOCK=1            optional: skip the network, return synthetic data

Usage as a library:
    from brave_client import BraveSearchClient
    client = BraveSearchClient.from_credentials()
    if client is None:
        ...  # tier disabled
    result = client.search("PA33N3T8 specifications")

Usage as a CLI (for quick testing):
    BRAVE_SEARCH_API_KEY=... python brave_client.py "PA33N3T8 specifications"
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Any

DEFAULT_BASE_URL = "https://api.search.brave.com"
# Brave's free tier is 1 req/sec. Cushion slightly to absorb clock skew /
# wall-clock jitter so we don't slam the limit on rapid sequential calls.
DEFAULT_RATE_LIMIT_MS = 1100
MAX_RETRIES = 3
REQUEST_TIMEOUT_S = 15


@dataclass
class BraveResult:
    title: str
    description: str
    url: str
    age: str | None = None


@dataclass
class BraveSearchResult:
    query: str
    results: list[BraveResult]
    total_results: int
    meta: dict[str, Any] = field(default_factory=dict)


class BraveError(Exception):
    pass


class BraveAuthError(BraveError):
    pass


class BraveSearchClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        rate_limit_ms: int = DEFAULT_RATE_LIMIT_MS,
        use_mock: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.rate_limit_ms = rate_limit_ms
        self.use_mock = use_mock
        self._last_request_at: float = 0.0

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_credentials(cls) -> "BraveSearchClient | None":
        """Build a client from the credentials store (env > keyring).

        Returns None if no API key is available anywhere AND mock mode is off,
        which silently disables the web-search tier in the enrichment cascade.
        """
        try:
            from credentials import get as _cred_get
        except ImportError:
            _cred_get = lambda _name: None  # noqa: E731

        api_key = _cred_get("brave_search_api_key")
        if not api_key and os.environ.get("BRAVE_MOCK") != "1":
            return None
        return cls(
            api_key=api_key or "mock",
            base_url=os.environ.get("BRAVE_SEARCH_BASE_URL", DEFAULT_BASE_URL),
            use_mock=os.environ.get("BRAVE_MOCK") == "1",
        )

    # ── Web search ───────────────────────────────────────────────────────────

    def search(self, query: str, count: int = 10) -> BraveSearchResult:
        """Run a single web-search query.

        Returns up to `count` results. Caller is responsible for handling
        empty results (no listings) and for deduping across multiple queries.
        """
        if self.use_mock:
            return self._mock_search(query, count)

        params = urllib.parse.urlencode({"q": query, "count": count})
        raw = self._request_json(f"/res/v1/web/search?{params}")

        web = raw.get("web") or {}
        items = web.get("results") or []
        results = [
            BraveResult(
                title=str(it.get("title") or ""),
                description=str(it.get("description") or ""),
                url=str(it.get("url") or ""),
                age=(str(it["age"]) if it.get("age") else None),
            )
            for it in items
        ]

        return BraveSearchResult(
            query=query,
            results=results,
            total_results=len(results),
            meta={"family_friendly": web.get("family_friendly")},
        )

    def test_connection(self) -> tuple[bool, str | None]:
        try:
            self.search("test", count=1)
            return True, None
        except BraveError as e:
            return False, str(e)

    # ── Internals ────────────────────────────────────────────────────────────

    def _request_json(self, endpoint: str) -> dict[str, Any]:
        self._respect_rate_limit()

        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
            "User-Agent": "rfq-normalizer/0.1",
        }
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
                    raise BraveAuthError(
                        f"Brave Search auth error ({e.code}): {body or 'invalid API key'}"
                    ) from e
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", "2"))
                    time.sleep(retry_after)
                    continue
                last_error = BraveError(f"Brave Search API {e.code}: {body or e.reason}")
            except urllib.error.URLError as e:
                last_error = BraveError(f"Brave Search network error: {e.reason}")
            except Exception as e:
                last_error = BraveError(f"Brave Search request failed: {e}")

            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

        raise last_error or BraveError("Brave Search request failed after retries")

    def _respect_rate_limit(self) -> None:
        elapsed_ms = (time.monotonic() - self._last_request_at) * 1000
        if elapsed_ms < self.rate_limit_ms:
            time.sleep((self.rate_limit_ms - elapsed_ms) / 1000)

    def _mock_search(self, query: str, count: int) -> BraveSearchResult:
        # Deterministic synthetic data for dev/test runs without a key.
        results = [
            BraveResult(
                title=f"Mock result {i} for '{query}'",
                description=f"Synthetic description {i} mentioning the query.",
                url=f"https://example.com/mock/{i}",
            )
            for i in range(min(count, 3))
        ]
        return BraveSearchResult(
            query=query, results=results, total_results=len(results), meta={"mock": True},
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--test-connection", action="store_true")
    args = ap.parse_args()

    client = BraveSearchClient.from_credentials()
    if client is None:
        print(
            "ERROR: Brave Search credentials not configured. "
            "Run /rfq-setup or set BRAVE_SEARCH_API_KEY (or BRAVE_MOCK=1).",
            file=sys.stderr,
        )
        return 2

    if args.test_connection:
        ok, err = client.test_connection()
        print(json.dumps({"ok": ok, "error": err}))
        return 0 if ok else 1

    result = client.search(args.query, count=args.count)
    out = {
        "query": result.query,
        "total_results": result.total_results,
        "results": [asdict(r) for r in result.results],
        "meta": result.meta,
    }
    json.dump(out, sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
