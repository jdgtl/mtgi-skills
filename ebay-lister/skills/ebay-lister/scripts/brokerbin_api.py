#!/usr/bin/env python3
"""BrokerBin Search API v2 client for ebay-lister's channel check.

Endpoints (spec v2.1.2, server https://search.brokerbin.com/api/v2):
  GET /part/search?query=<mpn>&priced=1&size=50   listings currently on BrokerBin
  GET /part/history/rfq?query=<mpn>&from=<date>    quote-request counts (demand)
  GET /part/history/supply-demand?query=<mpn>&interval=month&from=<date>
  GET /part/history/stats?query=<mpn>              price/qty stats of listings

Auth: Bearer token (Keychain `brokerbin-mtgi-api-token`), optional `login`
header (Keychain `brokerbin-mtgi-login`). Quota is ~50 calls/day, so every
response is cached to a JSON file (60-day TTL). BROKERBIN_MOCK=1 or mock=True
serves tests/fixtures/brokerbin_hd223.json for any MPN.

CLI:  python3 brokerbin_api.py search|rfq|supply|stats|summary <MPN> [--refresh]
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import credentials

BASE_URL = "https://search.brokerbin.com/api/v2"
RATE_LIMIT_S = 0.5
MAX_RETRIES = 3
TIMEOUT_S = 15
DEFAULT_TTL_DAYS = 60
DEFAULT_CACHE = Path.home() / "Documents/01_Clients/mtgi/work/ebay/market/.brokerbin-cache.json"
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "brokerbin_hd223.json"
OUR_COMPANY = "Micro Technologies"


class BrokerBinError(RuntimeError):
    """The operator has to fix something (credentials, quota, network)."""


class BrokerBinAPI:
    def __init__(self, token: str | None = None, login: str | None = None,
                 cache_path: Path | None = None, ttl_days: int = DEFAULT_TTL_DAYS,
                 mock: bool | None = None, refresh: bool = False):
        self.mock = bool(int(os.environ.get("BROKERBIN_MOCK", "0"))) if mock is None else mock
        if not self.mock and not token:
            raise BrokerBinError(
                "No BrokerBin token. Store it in Keychain as `brokerbin-mtgi-api-token` "
                "(security add-generic-password -U -s brokerbin-mtgi-api-token -a jonathan -w) "
                "or set BROKERBIN_API_KEY.")
        self.token, self.login = token, login
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE
        self.ttl = timedelta(days=ttl_days)
        self.refresh = refresh
        self.last_quota: dict | None = None
        self._last_call = 0.0
        self._cache = self._load_cache()

    @classmethod
    def from_credentials(cls, cache_path: Path | None = None, refresh: bool = False) -> "BrokerBinAPI":
        return cls(token=credentials.get("brokerbin_api_token"),
                   login=credentials.get("brokerbin_login"),
                   cache_path=cache_path, refresh=refresh)

    # ── public endpoints ────────────────────────────────────────────────
    def search(self, mpn: str, priced: bool = False, size: int = 50) -> dict:
        """All listings by default -- priced and CALL-priced -- so one call counts both."""
        params = {"query": mpn, "size": str(size)}
        if priced:
            params["priced"] = "1"
        return self._get("/part/search", params, kind="search")

    def rfq(self, mpn: str, days: int = 90) -> dict:
        since = (date.today() - timedelta(days=days)).isoformat()
        return self._get("/part/history/rfq", {"query": mpn, "from": since, "interval": "month"}, kind="rfq")

    def supply_demand(self, mpn: str, months: int = 12) -> dict:
        since = (date.today() - timedelta(days=30 * months)).isoformat()
        return self._get("/part/history/supply-demand",
                         {"query": mpn, "from": since, "interval": "month"}, kind="supply_demand")

    def stats(self, mpn: str) -> dict:
        return self._get("/part/history/stats", {"query": mpn}, kind="stats")

    # ── internals ───────────────────────────────────────────────────────
    def _get(self, path: str, params: dict, kind: str) -> dict:
        key = f"{path}|{json.dumps(params, sort_keys=True)}"
        if not self.refresh:
            hit = self._cache.get(key)
            if hit and datetime.fromisoformat(hit["at"]) + self.ttl > datetime.now(timezone.utc):
                return hit["body"]
        body = self._fetch(path, params, kind)
        meta = body.get("meta") if isinstance(body, dict) else None
        if isinstance(meta, dict) and isinstance(meta.get("request"), dict):
            self.last_quota = {"count": meta["request"].get("count"), "limit": meta["request"].get("limit")}
        self._cache[key] = {"at": datetime.now(timezone.utc).isoformat(), "body": body}
        self._save_cache()
        return body

    def _fetch(self, path: str, params: dict, kind: str) -> dict:
        if self.mock:
            return json.loads(FIXTURE.read_text())[kind]
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if self.login:
            headers["login"] = self.login
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            wait = RATE_LIMIT_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise BrokerBinError(
                        f"BrokerBin auth failed ({e.code}). Check Keychain item `brokerbin-mtgi-api-token`.") from None
                if e.code == 429:
                    time.sleep(int(e.headers.get("Retry-After", "5")))
                    continue
                last = e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = e
            time.sleep(2 ** attempt)
        raise BrokerBinError(f"BrokerBin request failed after {MAX_RETRIES} tries: {last}")

    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache))
        except OSError:
            pass  # cache is an optimization, never a failure


# ── summary used by channel_check ───────────────────────────────────────────
def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


def summarize(search: dict, rfq: dict, supply: dict, our_company: str = OUR_COMPANY,
              brand: str | None = None) -> dict:
    """Collapse the three raw responses into the numbers the channel check needs.

    The median ask excludes our own listing (we are pricing against the
    market, not ourselves) and unpriced (CALL) rows; qty_total includes both.
    When `brand` is given, rows whose manufacturer does not fuzzy-match it are
    dropped (BrokerBin keyword search on a short MPN like "828" matches
    unrelated parts); the count dropped is reported as `other_brand_rows`.
    """
    rows = search.get("data") or []
    other_brand = 0
    if brand:
        b = _norm(brand)
        kept = []
        for r in rows:
            m = _norm(r.get("mfg") or r.get("manufacturer") or "")
            if m and (m == b or b in m or m in b):
                kept.append(r)
            else:
                other_brand += 1
        rows = kept
    ours = None
    asks: list[float] = []
    qty_total = 0
    unpriced = 0
    conditions: dict[str, int] = {}
    for r in rows:
        price = _num(r.get("price"), 0.0)
        qty = int(_num(r.get("qty") or r.get("quantity"), 0))
        qty_total += qty
        cond = str(r.get("cond") or r.get("condition") or "").upper()
        conditions[cond] = conditions.get(cond, 0) + 1
        if str(r.get("company", "")).strip().lower() == our_company.lower():
            ours = {"price": price, "qty": qty}
            continue
        if price > 0:
            asks.append(price)
        else:
            unpriced += 1
    # Real v2 shapes (observed 2026-08-18): rfq rows {"date","rfqs"};
    # supply-demand rows {"date","searches","avg_total_qty"}.
    rfq_rows = rfq.get("data") or []
    rfq90 = int(sum(_num(x.get("rfqs", x.get("count", 0))) for x in rfq_rows))
    sd = supply.get("data") or []
    latest = sd[-1] if sd else {}
    return {
        "sellers": len(rows),
        "priced_listings": len(asks) + (1 if ours and ours["price"] > 0 else 0),
        "unpriced_listings": unpriced,
        "other_brand_rows": other_brand,
        "ask_med": statistics.median(asks) if asks else None,
        "ask_min": min(asks) if asks else None,
        "qty_total": qty_total,
        "conditions": conditions,
        "rfq90": rfq90,
        "ours": ours,
        "supply_qty_latest": int(_num(latest.get("avg_total_qty", latest.get("qty")))) if latest else None,
        "matches_latest": int(_num(latest.get("searches", latest.get("matches")))) if latest else None,
        "searches_90d": int(sum(_num(x.get("searches", 0)) for x in sd[-3:])) if sd else 0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BrokerBin Search API v2")
    p.add_argument("cmd", choices=["search", "rfq", "supply", "stats", "summary"])
    p.add_argument("mpn")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--brand", default=None, help="fuzzy manufacturer filter for summary")
    a = p.parse_args(argv)
    try:
        api = BrokerBinAPI.from_credentials(refresh=a.refresh)
        if a.cmd == "summary":
            out = summarize(api.search(a.mpn), api.rfq(a.mpn), api.supply_demand(a.mpn), brand=a.brand)
        else:
            out = {"search": api.search, "rfq": api.rfq, "supply": api.supply_demand, "stats": api.stats}[a.cmd](a.mpn)
        print(json.dumps({"quota": api.last_quota, "result": out}, indent=2))
    except BrokerBinError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
