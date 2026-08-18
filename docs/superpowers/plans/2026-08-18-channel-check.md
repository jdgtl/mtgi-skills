# Channel Check (eBay vs BrokerBin vs combo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scripted marketplace comparison to the ebay-lister skill that reads exact-SKU eBay market figures + live BrokerBin API data and prints eBay-only / BrokerBin-only / combo net revenue at 3 and 6 months with a recommendation the operator can write into the draft.

**Architecture:** Two new stdlib Python scripts under `ebay-lister/skills/ebay-lister/scripts/`: `brokerbin_api.py` (thin cached client for BrokerBin Search API v2) and `channel_check.py` (pure scenario math + CLI + `--apply`). Credentials resolve through the existing `credentials.py` (Keychain first). Constants live in `reference/channel-rules.md` and are mirrored as a `RULES` dict in code. A new SKILL.md step 1c wires it into the listing flow. Tests are pytest with `BROKERBIN_MOCK=1` fixtures; the math is pure functions so it is tested without network.

**Tech Stack:** Python 3.10+ stdlib only (`urllib`, `json`, `argparse`, `datetime`, `statistics`); pytest for tests (already on the machine, 9.x); macOS Keychain via `security` CLI (existing pattern).

**Spec:** `docs/superpowers/specs/2026-08-18-channel-check-design.md`

## Global Constraints

- Stdlib only — no `requests`, no `pandas`; the plugin ships with no `requirements.txt` for runtime.
- Never print or log a credential value; auth errors name the Keychain item (`brokerbin-mtgi-api-token`).
- BrokerBin quota is 50 calls/day: cache every response (60-day TTL, file at `<market_dir>/.brokerbin-cache.json`); surface `meta.request` count/limit on every live call.
- Verdict is advice: `channel_check.py` always exits 0; nothing in `publish.py` changes.
- Market JSON path convention: `<market_dir>/<MPN>.json`, default `market_dir` = `~/Documents/01_Clients/mtgi/work/ebay/market`; drafts at `~/Documents/01_Clients/mtgi/work/ebay/drafts/<SKU>.json`.
- MPN strings verbatim (exact case and hyphens) in filenames and API queries.
- All money rounded to whole dollars in the table; keep floats in `--json`.
- Commit after every task with a `feat(ebay-lister): …` / `test(ebay-lister): …` / `docs(ebay-lister): …` message on branch `ebay-lister-v0.1.0`.

---

## File map

| File | Responsibility |
|---|---|
| `ebay-lister/skills/ebay-lister/scripts/credentials.py` (modify) | add `brokerbin_api_token`, `brokerbin_login` to `CREDENTIAL_SCHEMA` (Keychain names `brokerbin-mtgi-api-token`, `brokerbin-mtgi-login`) |
| `ebay-lister/skills/ebay-lister/scripts/brokerbin_api.py` (create) | `BrokerBinAPI` class: `search`, `rfq`, `supply_demand`, `stats`; throttle, retries, cache, mock |
| `ebay-lister/skills/ebay-lister/scripts/channel_check.py` (create) | load market JSON + draft, fetch BrokerBin summary, `compute()` pure math, render table, `--apply` |
| `ebay-lister/skills/ebay-lister/reference/channel-rules.md` (create) | constants + how to tune + how to read the table |
| `ebay-lister/skills/ebay-lister/reference/spec.md` (modify) | document `channel`, `unit_cost`, `eol_date` |
| `ebay-lister/skills/ebay-lister/reference/market-json.md` (create) | schema of `market/<MPN>.json` and the screenshot-filtering rules |
| `ebay-lister/skills/ebay-lister/SKILL.md` (modify) | step 1c — Marketplace check |
| `ebay-lister/skills/ebay-lister/tests/conftest.py` (create) | sys.path shim (copy of rfq-normalizer's) |
| `ebay-lister/skills/ebay-lister/tests/test_brokerbin_api.py` (create) | cache hit, mock shape, auth error message, quota surfacing |
| `ebay-lister/skills/ebay-lister/tests/test_channel_check.py` (create) | share rule, three scenarios, EOL cap, no-asks fallback, verdict tie-break, `--apply` idempotent |
| `ebay-lister/skills/ebay-lister/tests/fixtures/hd223_market.json`, `hd223_draft.json`, `brokerbin_hd223.json` (create) | fixtures from the 2026-08-18 research |

---

### Task 1: Register BrokerBin credentials in `credentials.py`

**Files:**
- Modify: `ebay-lister/skills/ebay-lister/scripts/credentials.py` (the `CREDENTIAL_SCHEMA` dict, around lines 62–118)
- Create: `ebay-lister/skills/ebay-lister/tests/conftest.py`
- Test: `ebay-lister/skills/ebay-lister/tests/test_brokerbin_api.py`

**Interfaces:**
- Produces: `credentials.get("brokerbin_api_token") -> str | None`, `credentials.get("brokerbin_login") -> str | None` (Keychain items `brokerbin-mtgi-api-token`, `brokerbin-mtgi-login`; env `BROKERBIN_API_KEY`, `BROKERBIN_LOGIN`).

- [ ] **Step 1: Create the tests package and conftest**

`ebay-lister/skills/ebay-lister/tests/__init__.py` — empty file.

`ebay-lister/skills/ebay-lister/tests/conftest.py`:
```python
"""Adds the skill's scripts/ folder to sys.path so tests import modules directly."""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
```

- [ ] **Step 2: Write the failing test**

`ebay-lister/skills/ebay-lister/tests/test_brokerbin_api.py`:
```python
import credentials


def test_brokerbin_credentials_are_in_schema():
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["keychain"] == "brokerbin-mtgi-api-token"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["env"] == "BROKERBIN_API_KEY"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["keychain"] == "brokerbin-mtgi-login"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["env"] == "BROKERBIN_LOGIN"


def test_brokerbin_env_override(monkeypatch):
    monkeypatch.setenv("BROKERBIN_API_KEY", "env-token")
    assert credentials.get("brokerbin_api_token") == "env-token"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ebay-lister/skills/ebay-lister && python3 -m pytest tests/test_brokerbin_api.py -v`
Expected: FAIL with `KeyError: 'brokerbin_api_token'`

- [ ] **Step 4: Add the schema entries**

In `credentials.py`, inside `CREDENTIAL_SCHEMA`, after the `cloudflare_account_id` entry, add:
```python
    "brokerbin_api_token": {
        "env": "BROKERBIN_API_KEY",
        "keychain": "brokerbin-mtgi-api-token",
        "label": "BrokerBin API token (Search API v2)",
        "help": "Bearer token for https://search.brokerbin.com/api/v2. Registered in 05_System/credentials/REGISTRY.md.",
    },
    "brokerbin_login": {
        "env": "BROKERBIN_LOGIN",
        "keychain": "brokerbin-mtgi-login",
        "label": "BrokerBin acting-user login (optional)",
        "help": "Sent as the `login` header so BrokerBin attributes calls to this user; falls back to the company primary user.",
    },
```
Do NOT add them to the required-credentials list used by `check_setup.py` (BrokerBin is optional).

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_brokerbin_api.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add ebay-lister/skills/ebay-lister/scripts/credentials.py ebay-lister/skills/ebay-lister/tests/
git commit -m "feat(ebay-lister): brokerbin credentials in schema + tests scaffold"
```

---

### Task 2: `brokerbin_api.py` — client with cache and mock

**Files:**
- Create: `ebay-lister/skills/ebay-lister/scripts/brokerbin_api.py`
- Create: `ebay-lister/skills/ebay-lister/tests/fixtures/brokerbin_hd223.json`
- Test: `ebay-lister/skills/ebay-lister/tests/test_brokerbin_api.py` (append)

**Interfaces:**
- Consumes: `credentials.get("brokerbin_api_token")`, `credentials.get("brokerbin_login")`.
- Produces:
  ```python
  class BrokerBinAPI:
      def __init__(self, token: str | None = None, login: str | None = None,
                   cache_path: Path | None = None, ttl_days: int = 60,
                   mock: bool | None = None, refresh: bool = False): ...
      @classmethod
      def from_credentials(cls, cache_path: Path | None = None, refresh: bool = False) -> "BrokerBinAPI": ...
      def search(self, mpn: str, priced: bool = True, size: int = 50) -> dict   # raw v2 JSON {meta, data}
      def rfq(self, mpn: str, days: int = 90) -> dict
      def supply_demand(self, mpn: str, months: int = 12) -> dict
      def stats(self, mpn: str) -> dict
      last_quota: dict | None   # {"count": int, "limit": int} from the last live call
  class BrokerBinError(RuntimeError): ...
  def summarize(search: dict, rfq: dict, supply: dict, our_company: str = "Micro Technologies") -> dict
  ```
  `summarize` returns:
  ```python
  {"sellers": int, "priced_listings": int, "ask_med": float | None, "ask_min": float | None,
   "qty_total": int, "conditions": {"NEW": n, ...}, "rfq90": int,
   "ours": {"price": float, "qty": int} | None, "supply_qty_latest": int | None,
   "matches_latest": int | None}
  ```
  Median excludes our own listing. `rfq90` = sum of `data[*].count` (or `doc_count`) in the RFQ response; 0 when empty.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/brokerbin_hd223.json` — the mock returns this for any MPN when `mock=True`:
```json
{
  "search": {"meta": {"total": 4, "request": {"count": 1, "limit": 50},
                       "manufacturers": [{"key": "BRIGHTSIGN", "doc_count": 4}],
                       "conditions": [{"key": "USED", "doc_count": 3}, {"key": "REF", "doc_count": 1}]},
             "data": [
               {"mfg": "BRIGHTSIGN", "part": "HD223", "cond": "USED", "price": "38", "qty": "12", "company": "Signage Surplus", "country": "USA", "age_in_days": 3},
               {"mfg": "BRIGHTSIGN", "part": "HD223", "cond": "USED", "price": "45", "qty": "6", "company": "AV Brokers", "country": "USA", "age_in_days": 10},
               {"mfg": "BRIGHTSIGN", "part": "HD223", "cond": "REF", "price": "60", "qty": "2", "company": "RefurbCo", "country": "GBR", "age_in_days": 1},
               {"mfg": "BRIGHTSIGN", "part": "HD223", "cond": "USED", "price": "42", "qty": "17", "company": "Micro Technologies", "country": "USA", "age_in_days": 0}
             ]},
  "rfq": {"meta": {"request": {"count": 2, "limit": 50}}, "data": [{"key": "2026-06", "count": 1}, {"key": "2026-07", "count": 1}]},
  "supply_demand": {"meta": {"request": {"count": 3, "limit": 50}}, "data": [{"key": "2026-07", "qty": 210, "matches": 34}, {"key": "2026-08", "qty": 198, "matches": 29}]},
  "stats": {"meta": {"request": {"count": 4, "limit": 50}}, "data": []}
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_brokerbin_api.py`:
```python
import json
from pathlib import Path
import pytest
import brokerbin_api as bb

FIX = Path(__file__).parent / "fixtures" / "brokerbin_hd223.json"


def test_mock_search_shape(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    r = api.search("HD223")
    assert r["meta"]["total"] == 4 and len(r["data"]) == 4


def test_summarize_excludes_our_listing():
    fx = json.loads(FIX.read_text())
    s = bb.summarize(fx["search"], fx["rfq"], fx["supply_demand"])
    assert s["sellers"] == 4
    assert s["ours"] == {"price": 42.0, "qty": 17}
    assert s["ask_med"] == 45.0          # median of 38, 45, 60 (ours excluded)
    assert s["ask_min"] == 38.0
    assert s["qty_total"] == 37          # 12 + 6 + 2 + 17
    assert s["rfq90"] == 2
    assert s["supply_qty_latest"] == 198 and s["matches_latest"] == 29


def test_summarize_no_priced_asks():
    s = bb.summarize({"meta": {}, "data": []}, {"data": []}, {"data": []})
    assert s["ask_med"] is None and s["sellers"] == 0 and s["rfq90"] == 0 and s["ours"] is None


def test_cache_hit_avoids_network(tmp_path, monkeypatch):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("network should not be called")
    monkeypatch.setattr(api, "_fetch", boom)
    api.search("HD223")                  # served from cache
    assert calls["n"] == 0
    assert (tmp_path / "c.json").exists()


def test_refresh_bypasses_cache(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    api2 = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json", refresh=True)
    r = api2.search("HD223")
    assert r["meta"]["total"] == 4


def test_missing_token_names_keychain_item():
    with pytest.raises(bb.BrokerBinError) as e:
        bb.BrokerBinAPI(token=None, mock=False)
    assert "brokerbin-mtgi-api-token" in str(e.value)


def test_last_quota_surfaced(tmp_path):
    api = bb.BrokerBinAPI(token="x", mock=True, cache_path=tmp_path / "c.json")
    api.search("HD223")
    assert api.last_quota == {"count": 1, "limit": 50}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_brokerbin_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brokerbin_api'`

- [ ] **Step 4: Implement `brokerbin_api.py`**

```python
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

CLI:  python3 brokerbin_api.py search HD223 | rfq HD223 | supply HD223 [--refresh]
"""
from __future__ import annotations
import argparse, json, os, statistics, sys, time, urllib.error, urllib.parse, urllib.request
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
    def search(self, mpn: str, priced: bool = True, size: int = 50) -> dict:
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
def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def summarize(search: dict, rfq: dict, supply: dict, our_company: str = OUR_COMPANY) -> dict:
    rows = search.get("data") or []
    ours = None
    asks: list[float] = []
    qty_total = 0
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
    rfq_rows = rfq.get("data") or []
    rfq90 = int(sum(_num(x.get("count", x.get("doc_count", 0))) for x in rfq_rows))
    sd = supply.get("data") or []
    latest = sd[-1] if sd else {}
    return {
        "sellers": len(rows),
        "priced_listings": len(asks) + (1 if ours and ours["price"] > 0 else 0),
        "ask_med": statistics.median(asks) if asks else None,
        "ask_min": min(asks) if asks else None,
        "qty_total": qty_total,
        "conditions": conditions,
        "rfq90": rfq90,
        "ours": ours,
        "supply_qty_latest": int(_num(latest.get("qty"))) if latest else None,
        "matches_latest": int(_num(latest.get("matches"))) if latest else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BrokerBin Search API v2")
    p.add_argument("cmd", choices=["search", "rfq", "supply", "stats", "summary"])
    p.add_argument("mpn")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args(argv)
    try:
        api = BrokerBinAPI.from_credentials(refresh=a.refresh)
        if a.cmd == "summary":
            out = summarize(api.search(a.mpn), api.rfq(a.mpn), api.supply_demand(a.mpn))
        else:
            out = {"search": api.search, "rfq": api.rfq, "supply": api.supply_demand, "stats": api.stats}[a.cmd](a.mpn)
        print(json.dumps({"quota": api.last_quota, "result": out}, indent=2))
    except BrokerBinError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_brokerbin_api.py -v`
Expected: 9 PASS

- [ ] **Step 6: Live smoke (one quota call, optional)**

Run: `python3 scripts/brokerbin_api.py summary ET91000SM20`
Expected: JSON with `"quota": {"count": N, "limit": 50}` and `"ours": {"price": 223.0, "qty": 15}` (MTGI's own line seen 2026-08-18). If auth fails, the error names the Keychain item.

- [ ] **Step 7: Commit**

```bash
git add ebay-lister/skills/ebay-lister/scripts/brokerbin_api.py ebay-lister/skills/ebay-lister/tests/
git commit -m "feat(ebay-lister): brokerbin_api.py — cached Search API v2 client + summarize()"
```

---

### Task 3: `channel_check.py` — pure scenario math

**Files:**
- Create: `ebay-lister/skills/ebay-lister/scripts/channel_check.py` (math + data classes only in this task; CLI in Task 4)
- Create: `ebay-lister/skills/ebay-lister/tests/fixtures/hd223_market.json`, `tests/fixtures/hd223_draft.json`
- Test: `ebay-lister/skills/ebay-lister/tests/test_channel_check.py`

**Interfaces:**
- Consumes: `brokerbin_api.summarize()` output dict (see Task 2).
- Produces:
  ```python
  RULES: dict  # defaults below
  def pick_share(market: dict, ask: float, rules: dict = RULES) -> tuple[float, str]
  def label_estimate(pkg: dict | None, rules: dict = RULES) -> float
  def compute(market: dict, draft: dict, bb: dict, rules: dict = RULES,
              today: date | None = None, label: float | None = None) -> dict
  ```
  `compute()` returns:
  ```python
  {"mpn": str, "qty": int, "ask": float, "share": float, "share_rule": str,
   "n_e": float, "p_e": float, "n_b_single": float | None, "n_b_lot": float | None, "p_b": float,
   "eol_months": float | None,
   "scenarios": {"ebay": {"3": float, "6": float, "unbounded": {"months": float | None, "net": float}},
                 "brokerbin": {...same..., "lot": {"net": float, "weight": float} | None},
                 "combo": {"3": float, "6": float}},
   "verdict": "ebay" | "brokerbin" | "combo",
   "rationale": str, "flags": list[str], "assumptions": dict}
  ```

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/hd223_market.json`:
```json
{"mpn": "HD223", "condition_scope": "used, unit only", "captured": "2026-08-18",
 "ebay": {"window_months": 6, "sold_units": 51, "sold_avg_allin": 59.83, "sold_median_allin": 50.70,
          "volume_seller": {"price_allin": 50.70, "units": 24}, "lots_per_unit": [35, 43, 45],
          "active_count": 40, "active_bare_range": [40, 65], "watchers_max": 4,
          "exclusions": "9 adapter rows, 3 HD1023, cross-stitch, Allison filter, Massey starter, 1 removed"},
 "notes": "Series 3 leaves BrightSign Author Dec 2026"}
```
`tests/fixtures/hd223_draft.json`:
```json
{"sku": "MTGI-HD223", "mpn": "HD223", "quantity": 17, "price": "49.95", "autoAcceptPrice": "42.00",
 "condition": "used_good", "eol_date": "2026-12-01",
 "packageWeightAndSize": {"weight": {"value": 1, "unit": "POUND"}}}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_channel_check.py`:
```python
import json
from datetime import date
from pathlib import Path
import pytest
import brokerbin_api as bb
import channel_check as cc

FIX = Path(__file__).parent / "fixtures"
MARKET = json.loads((FIX / "hd223_market.json").read_text())
DRAFT = json.loads((FIX / "hd223_draft.json").read_text())
BBFIX = json.loads((FIX / "brokerbin_hd223.json").read_text())
BB = bb.summarize(BBFIX["search"], BBFIX["rfq"], BBFIX["supply_demand"])
TODAY = date(2026, 8, 18)


def test_share_rules_precedence():
    m = dict(MARKET); e = dict(MARKET["ebay"])
    e["active_count"] = 0; m["ebay"] = e
    assert cc.pick_share(m, 49.95) == (0.70, "no exact-SKU active competitor")
    e = dict(MARKET["ebay"]); m["ebay"] = e
    assert cc.pick_share(m, 49.95) == (0.40, "default")  # vol seller 50.70 > ask; ask <= median but watchers 4 > 2
    assert cc.pick_share(m, 60.00)[0] == 0.30            # volume seller at/below our ask
    e["volume_seller"] = None; e["watchers_max"] = 2
    assert cc.pick_share(m, 45.00) == (0.50, "at/below clearing price, watchers <= 2")
    e["watchers_max"] = 5
    assert cc.pick_share(m, 45.00) == (0.40, "default")


def test_label_estimate_by_weight():
    assert cc.label_estimate({"weight": {"value": 1, "unit": "POUND"}}) == 8.0
    assert cc.label_estimate({"weight": {"value": 3, "unit": "POUND"}}) == 11.0
    assert cc.label_estimate({"weight": {"value": 13.4, "unit": "POUND"}}) == 28.0
    assert cc.label_estimate(None) == cc.RULES["label_default"]


def test_compute_hd223_numbers():
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    # ask 49.95, fvf .13 -> 6.49, label 8 -> n_e = 35.46 (rounded 35.45..)
    assert round(r["n_e"], 2) == 35.46
    # volume seller 50.70 > ask 49.95 -> not "at/below" -> falls to 0.50? median 50.70 >= 49.95 and watchers 4 > 2 -> default 0.40
    assert r["share"] == 0.40
    assert round(r["p_e"], 2) == 3.40                    # 51/6 * 0.40
    assert r["n_b_single"] == round(45.0 * 0.65, 2) and r["n_b_lot"] == round(45.0 * 0.55, 2)
    assert round(r["p_b"], 3) == round(2 / 3 * 0.25, 3)   # rfq90=2
    assert r["eol_months"] == pytest.approx(3.4, abs=0.2)  # 2026-08-18 -> 2026-12-01
    s = r["scenarios"]
    # EOL cap: horizon 6 clipped to ~3.4 months, salvage 0.25 * n_b_lot
    assert s["ebay"]["6"] == s["ebay"]["3"] or s["ebay"]["6"] > s["ebay"]["3"]
    assert s["brokerbin"]["lot"]["weight"] == 1.0
    assert r["verdict"] in ("ebay", "combo")
    assert "EOL cap" in " ".join(r["flags"])
    assert r["assumptions"]["share"] == 0.40


def test_no_brokerbin_asks_falls_back_to_ebay():
    empty = bb.summarize({"data": []}, {"data": []}, {"data": []})
    d = dict(DRAFT); d.pop("eol_date")
    r = cc.compute(MARKET, d, empty, today=TODAY)
    assert r["n_b_single"] is None
    assert r["scenarios"]["brokerbin"]["6"] is None
    assert r["verdict"] == "ebay"
    assert any("no BrokerBin asks" in f for f in r["flags"])


def test_verdict_prefers_combo_when_within_tie_pct():
    # With combo_tie_pct = 1.0 every spread counts as a tie, so combo must win
    # whenever it is computable; with 0.0 the raw top scenario wins.
    d = dict(DRAFT); d.pop("eol_date")
    tie_rules = dict(cc.RULES); tie_rules["combo_tie_pct"] = 1.0
    r = cc.compute(MARKET, d, BB, rules=tie_rules, today=TODAY)
    assert r["verdict"] == "combo" and "combo preferred" in r["rationale"]
    strict = dict(cc.RULES); strict["combo_tie_pct"] = 0.0
    r2 = cc.compute(MARKET, d, BB, rules=strict, today=TODAY)
    s = r2["scenarios"]
    best = max(("ebay", "brokerbin", "combo"), key=lambda n: (s[n]["6"] if s[n]["6"] is not None else float("-inf")))
    assert r2["verdict"] == best


def test_thin_data_flag():
    m = json.loads(json.dumps(MARKET)); m["ebay"]["sold_units"] = 3
    d = dict(DRAFT); d.pop("eol_date")
    r = cc.compute(m, d, BB, today=TODAY)
    assert any("thin eBay data" in f for f in r["flags"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_channel_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'channel_check'`

- [ ] **Step 4: Implement the math in `channel_check.py`**

```python
#!/usr/bin/env python3
"""Channel check: eBay-only vs BrokerBin-only vs combo, at 3 and 6 months.

Reads the exact-SKU eBay figures from market/<MPN>.json (written by the AI from
the operator's Seller Hub Product Research screenshots), the draft JSON (qty,
ask, package, optional unit_cost / eol_date), and a BrokerBin summary
(brokerbin_api.summarize). Pure math lives in compute(); the CLI renders it and
--apply writes the verdict into the draft. Advice only: always exits 0.

Constants are documented in reference/channel-rules.md and mirrored in RULES.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, datetime
from pathlib import Path

import brokerbin_api

RULES: dict = {
    "fvf": 0.13,                 # eBay final value fee share of the sale price
    "label_default": 11.0,       # when no package weight and no sales_history mode
    "label_by_lb": [(1, 8.0), (3, 11.0), (5, 14.0)],   # <= lb -> $; heavier -> label_heavy
    "label_heavy": 28.0,
    "share_no_competitor": 0.70,
    "share_volume_seller": 0.30,
    "share_at_clearing": 0.50,
    "share_default": 0.40,
    "bb_single_haircut": 0.65,
    "bb_lot_haircut": 0.55,
    "rfq_conversion": 0.25,      # share of 90-day RFQs that become one unit sold
    "salvage": 0.50,             # leftover at horizon, as share of n_b_lot
    "salvage_eol": 0.25,
    "no_asks_salvage_of_ne": 0.25,
    "lot_min_qty": 5,
    "combo_tie_pct": 0.10,
    "thin_solds": 5,
    "horizons": (3, 6),
}


def pick_share(market: dict, ask: float, rules: dict = RULES) -> tuple[float, str]:
    e = market["ebay"]
    if int(e.get("active_count") or 0) == 0:
        return rules["share_no_competitor"], "no exact-SKU active competitor"
    vs = e.get("volume_seller")
    if vs and float(vs.get("price_allin", 0)) <= ask:
        return rules["share_volume_seller"], "volume seller at/below our ask"
    med = e.get("sold_median_allin")
    if med is not None and ask <= float(med) and int(e.get("watchers_max") or 0) <= 2:
        return rules["share_at_clearing"], "at/below clearing price, watchers <= 2"
    return rules["share_default"], "default"


def label_estimate(pkg: dict | None, rules: dict = RULES) -> float:
    if not pkg or not pkg.get("weight"):
        return rules["label_default"]
    w = float(pkg["weight"].get("value", 0))
    if str(pkg["weight"].get("unit", "POUND")).upper().startswith("OUNCE"):
        w = w / 16.0
    for cap, cost in rules["label_by_lb"]:
        if w <= cap:
            return cost
    return rules["label_heavy"]


def _months_until(eol: str | None, today: date) -> float | None:
    if not eol:
        return None
    d = datetime.strptime(eol, "%Y-%m-%d").date()
    return max(0.0, (d - today).days / 30.4375)


def compute(market: dict, draft: dict, bb: dict, rules: dict = RULES,
            today: date | None = None, label: float | None = None) -> dict:
    today = today or date.today()
    e = market["ebay"]
    qty = int(draft.get("quantity", 1))
    ask = float(draft["price"])
    share, share_rule = pick_share(market, ask, rules)
    label = label if label is not None else label_estimate(draft.get("packageWeightAndSize"), rules)
    n_e = ask - rules["fvf"] * ask - label
    p_e = (float(e["sold_units"]) / float(e["window_months"])) * share

    ask_med = bb.get("ask_med")
    n_b_single = round(ask_med * rules["bb_single_haircut"], 2) if ask_med else None
    n_b_lot = round(ask_med * rules["bb_lot_haircut"], 2) if ask_med else None
    rfq90 = int(bb.get("rfq90") or 0)
    p_b = (rfq90 / 3.0) * rules["rfq_conversion"] if rfq90 > 0 else 0.0
    lot_weight = 1.0 if rfq90 > 0 else 0.5

    eol_months = _months_until(draft.get("eol_date"), today)
    salvage_share = rules["salvage_eol"] if eol_months is not None else rules["salvage"]
    if n_b_lot is not None:
        salvage = salvage_share * n_b_lot
    else:
        salvage = rules["no_asks_salvage_of_ne"] * n_e

    flags: list[str] = []
    if int(e["sold_units"]) < rules["thin_solds"]:
        flags.append("thin eBay data (fewer than %d exact-SKU solds)" % rules["thin_solds"])
    if rfq90 == 0:
        flags.append("no BrokerBin demand signal (0 RFQs in 90 d)")
    if ask_med is None:
        flags.append("no BrokerBin asks for this MPN — BrokerBin scenarios n/a")
    if eol_months is not None:
        flags.append("EOL cap active (%s → %.1f months; salvage %.0f%%)" % (draft["eol_date"], eol_months, salvage_share * 100))
    if bb.get("ours"):
        flags.append("MTGI already on BrokerBin at $%.0f × %d — sync qty after eBay sales" % (bb["ours"]["price"], bb["ours"]["qty"]))

    def horizon(h: float) -> float:
        return min(h, eol_months) if eol_months is not None else h

    def ebay_net(h: float) -> float:
        sold = min(qty, p_e * h)
        return sold * n_e + (qty - sold) * salvage

    def bb_net(h: float) -> float | None:
        if n_b_single is None:
            return None
        sold = min(qty, p_b * h)
        return sold * n_b_single + (qty - sold) * salvage

    def combo_net(h: float) -> float | None:
        if n_b_lot is None:
            return None
        sold = min(qty, p_e * h)
        return sold * n_e + (qty - sold) * n_b_lot * lot_weight

    scen: dict = {"ebay": {}, "brokerbin": {}, "combo": {}}
    for h in rules["horizons"]:
        hh = horizon(h)
        scen["ebay"][str(h)] = round(ebay_net(hh), 2)
        v = bb_net(hh); scen["brokerbin"][str(h)] = None if v is None else round(v, 2)
        v = combo_net(hh); scen["combo"][str(h)] = None if v is None else round(v, 2)
    scen["ebay"]["unbounded"] = {"months": round(qty / p_e, 1) if p_e > 0 else None, "net": round(qty * n_e, 2)}
    scen["brokerbin"]["unbounded"] = {"months": round(qty / p_b, 1) if p_b > 0 else None,
                                      "net": None if n_b_single is None else round(qty * n_b_single, 2)}
    scen["brokerbin"]["lot"] = None if (n_b_lot is None or qty < rules["lot_min_qty"]) else \
        {"net": round(qty * n_b_lot * lot_weight, 2), "weight": lot_weight}

    # verdict: highest at 6, tie-break 3, combo if within tie pct
    def score(name: str, h: str) -> float:
        v = scen[name].get(h)
        return float("-inf") if v is None else v
    ranked = sorted(("ebay", "brokerbin", "combo"), key=lambda n: (score(n, "6"), score(n, "3")), reverse=True)
    verdict = ranked[0]
    top, second = score(ranked[0], "6"), score(ranked[1], "6")
    tie = top > 0 and second > float("-inf") and (top - second) / top <= rules["combo_tie_pct"]
    if tie and score("combo", "6") > float("-inf") and verdict != "combo":
        verdict = "combo"

    parts = ["eBay pace %.1f/mo × %.0f%% share" % (p_e / share if share else 0, share * 100)]
    if p_e > 0 and qty / p_e > horizon(6):
        parts.append("cannot clear %d units in %.1f months" % (qty, horizon(6)))
    else:
        parts.append("clears %d units in %.1f months" % (qty, qty / p_e if p_e else 0))
    parts.append("BrokerBin %s" % ("%d RFQs/90 d, median ask $%.0f" % (rfq90, ask_med) if ask_med else "no asks"))
    nets = ", ".join("%s $%.0f" % (n, score(n, "6")) for n in ranked if score(n, "6") > float("-inf"))
    rationale = "%s; %s → 6-mo net %s%s." % ("; ".join(parts[:2]), parts[2], nets,
                                             "; within %.0f%% so combo preferred" % (rules["combo_tie_pct"] * 100) if tie else "")

    return {
        "mpn": market["mpn"], "qty": qty, "ask": ask, "share": share, "share_rule": share_rule,
        "n_e": round(n_e, 2), "p_e": round(p_e, 3), "label": label,
        "n_b_single": n_b_single, "n_b_lot": n_b_lot, "p_b": round(p_b, 3),
        "eol_months": None if eol_months is None else round(eol_months, 1),
        "scenarios": scen, "verdict": verdict, "rationale": rationale, "flags": flags,
        "assumptions": {"share": share, "rfq_conversion": rules["rfq_conversion"],
                        "bb_single_haircut": rules["bb_single_haircut"], "bb_lot_haircut": rules["bb_lot_haircut"],
                        "fvf": rules["fvf"], "label": label},
        "brokerbin": bb,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_channel_check.py -v`
Expected: 6 PASS. If `test_compute_hd223_numbers` fails on `n_e`, check that `label_estimate` returned 8.0 for 1 lb and `fvf` is 0.13 (49.95 − 6.4935 − 8 = 35.4565 → 35.46).

- [ ] **Step 6: Commit**

```bash
git add ebay-lister/skills/ebay-lister/scripts/channel_check.py ebay-lister/skills/ebay-lister/tests/
git commit -m "feat(ebay-lister): channel_check.py scenario math (eBay/BrokerBin/combo, 3 & 6 mo)"
```

---

### Task 4: `channel_check.py` — CLI, table, `--apply`

**Files:**
- Modify: `ebay-lister/skills/ebay-lister/scripts/channel_check.py` (append render + main)
- Test: `ebay-lister/skills/ebay-lister/tests/test_channel_check.py` (append)

**Interfaces:**
- Produces:
  ```python
  def render(result: dict) -> str
  def load_inputs(target: str, market_dir: Path, drafts_dir: Path) -> tuple[dict, dict, Path]  # market, draft, draft_path
  def apply(draft_path: Path, result: dict, today: date | None = None) -> None
  def main(argv: list[str] | None = None) -> int
  ```
  CLI: `channel_check.py <SKU-or-MPN> [--apply] [--refresh] [--json] [--market-dir P] [--drafts-dir P] [--label N]`. Resolution: if `<drafts_dir>/<target>.json` exists use it (SKU); else scan drafts for `mpn == target`; market file is `<market_dir>/<mpn>.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_channel_check.py`:
```python
def test_render_contains_verdict_and_table():
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    out = cc.render(r)
    assert "CHANNEL CHECK — HD223" in out
    assert "3 mo net" in out and "6 mo net" in out and "unbounded" in out
    assert "VERDICT " + r["verdict"] in out
    assert "assumptions" in out


def test_apply_writes_channel_block_idempotently(tmp_path):
    p = tmp_path / "MTGI-HD223.json"
    p.write_text(json.dumps(DRAFT))
    r = cc.compute(MARKET, DRAFT, BB, today=TODAY)
    cc.apply(p, r, today=TODAY)
    d1 = json.loads(p.read_text())
    assert d1["channel"]["verdict"] == r["verdict"]
    assert d1["channel"]["checked_at"] == "2026-08-18"
    assert set(d1["channel"]["net"]) == {"ebay", "brokerbin", "combo"}
    cc.apply(p, r, today=TODAY)
    d2 = json.loads(p.read_text())
    assert d1 == d2


def test_main_resolves_by_mpn_and_exits_zero(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BROKERBIN_MOCK", "1")
    (tmp_path / "market").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "market" / "HD223.json").write_text(json.dumps(MARKET))
    (tmp_path / "drafts" / "MTGI-HD223.json").write_text(json.dumps(DRAFT))
    rc = cc.main(["HD223", "--market-dir", str(tmp_path / "market"), "--drafts-dir", str(tmp_path / "drafts"),
                  "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mpn"] == "HD223" and out["verdict"] in ("ebay", "brokerbin", "combo")


def test_main_missing_market_file_is_a_clear_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BROKERBIN_MOCK", "1")
    (tmp_path / "market").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "MTGI-HD223.json").write_text(json.dumps(DRAFT))
    rc = cc.main(["MTGI-HD223", "--market-dir", str(tmp_path / "market"), "--drafts-dir", str(tmp_path / "drafts")])
    assert rc == 0
    assert "market/HD223.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_channel_check.py -v -k "render or apply or main"`
Expected: FAIL with `AttributeError: module 'channel_check' has no attribute 'render'`

- [ ] **Step 3: Implement render/load/apply/main**

Append to `channel_check.py`:
```python
DEFAULT_MARKET_DIR = Path.home() / "Documents/01_Clients/mtgi/work/ebay/market"
DEFAULT_DRAFTS_DIR = Path.home() / "Documents/01_Clients/mtgi/work/ebay/drafts"


def _money(v) -> str:
    return "   n/a" if v is None else "$%6.0f" % v


def render(r: dict) -> str:
    e = r["brokerbin"]; s = r["scenarios"]
    lines = []
    lines.append("CHANNEL CHECK — %s (%d units, ask $%.2f)   share %.0f%% (rule: %s)" %
                 (r["mpn"], r["qty"], r["ask"], r["share"] * 100, r["share_rule"]))
    lines.append("eBay      net/unit $%.2f · pace %.2f/mo · label $%.0f · fvf %.0f%%" %
                 (r["n_e"], r["p_e"], r["label"], r["assumptions"]["fvf"] * 100))
    ours = e.get("ours")
    lines.append("BrokerBin %d sellers · med ask %s · qty %d · RFQ/90d %d · Micro Technologies: %s" %
                 (e.get("sellers", 0), "n/a" if e.get("ask_med") is None else "$%.0f" % e["ask_med"],
                  e.get("qty_total", 0), e.get("rfq90", 0),
                  "not listed" if not ours else "$%.0f × %d" % (ours["price"], ours["qty"])))
    lines.append("                       3 mo net     6 mo net     unbounded")
    ub = s["ebay"]["unbounded"]
    lines.append("  eBay only          %s      %s      %s in %s mo → %s" %
                 (_money(s["ebay"]["3"]), _money(s["ebay"]["6"]), r["qty"],
                  "∞" if ub["months"] is None else ub["months"], _money(ub["net"])))
    ub = s["brokerbin"]["unbounded"]
    lines.append("  BrokerBin only     %s      %s      %s" %
                 (_money(s["brokerbin"]["3"]), _money(s["brokerbin"]["6"]),
                  "n/a" if ub["net"] is None else "%d in %s mo → %s" % (r["qty"], "∞" if ub["months"] is None else ub["months"], _money(ub["net"]))))
    if s["brokerbin"].get("lot"):
        lines.append("    lot of %-3d        %s (weight %.1f, ≤60 d)" % (r["qty"], _money(s["brokerbin"]["lot"]["net"]), s["brokerbin"]["lot"]["weight"]))
    lines.append("  Combo              %s      %s      —" % (_money(s["combo"]["3"]), _money(s["combo"]["6"])))
    lines.append("VERDICT %s — %s" % (r["verdict"], r["rationale"]))
    if r["flags"]:
        lines.append("flags: " + "; ".join(r["flags"]))
    a = r["assumptions"]
    lines.append("assumptions: share %.2f · rfq conv %.2f · bb haircut %.2f/%.2f · fvf %.2f · label $%.0f" %
                 (a["share"], a["rfq_conversion"], a["bb_single_haircut"], a["bb_lot_haircut"], a["fvf"], a["label"]))
    return "\n".join(lines)


def load_inputs(target: str, market_dir: Path, drafts_dir: Path) -> tuple[dict, dict, Path]:
    draft_path = drafts_dir / f"{target}.json"
    if not draft_path.exists():
        for p in sorted(drafts_dir.glob("*.json")):
            try:
                d = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            if d.get("mpn") == target:
                draft_path = p
                break
    if not draft_path.exists():
        raise FileNotFoundError(f"No draft for {target} in {drafts_dir}")
    draft = json.loads(draft_path.read_text())
    mpn = draft.get("mpn") or target
    market_path = market_dir / f"{mpn}.json"
    if not market_path.exists():
        raise FileNotFoundError(
            f"No eBay market file at {market_dir.name}/{mpn}.json — ask the operator for the Product Research "
            f"Sold + Active screenshots, filter to the exact SKU, and write it (see reference/market-json.md).")
    return json.loads(market_path.read_text()), draft, draft_path


def apply(draft_path: Path, result: dict, today: date | None = None) -> None:
    today = today or date.today()
    d = json.loads(draft_path.read_text())
    s = result["scenarios"]
    d["channel"] = {
        "verdict": result["verdict"],
        "checked_at": today.isoformat(),
        "horizon_months": 6,
        "net": {"ebay": s["ebay"]["6"], "brokerbin": s["brokerbin"]["6"], "combo": s["combo"]["6"]},
        "rationale": result["rationale"],
        "assumptions": result["assumptions"],
    }
    draft_path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="eBay vs BrokerBin vs combo channel check (advice only)")
    p.add_argument("target", help="draft SKU (MTGI-HD223) or MPN (HD223)")
    p.add_argument("--apply", action="store_true", help="write the verdict into the draft JSON")
    p.add_argument("--refresh", action="store_true", help="bypass the BrokerBin cache")
    p.add_argument("--json", action="store_true", help="emit the full computation as JSON")
    p.add_argument("--market-dir", default=str(DEFAULT_MARKET_DIR))
    p.add_argument("--drafts-dir", default=str(DEFAULT_DRAFTS_DIR))
    p.add_argument("--label", type=float, default=None, help="override the per-unit label cost")
    a = p.parse_args(argv)
    market_dir, drafts_dir = Path(a.market_dir).expanduser(), Path(a.drafts_dir).expanduser()
    try:
        market, draft, draft_path = load_inputs(a.target, market_dir, drafts_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 0
    try:
        api = brokerbin_api.BrokerBinAPI.from_credentials(cache_path=market_dir / ".brokerbin-cache.json", refresh=a.refresh)
        mpn = draft.get("mpn") or market["mpn"]
        bb = brokerbin_api.summarize(api.search(mpn), api.rfq(mpn), api.supply_demand(mpn))
        quota = api.last_quota
    except brokerbin_api.BrokerBinError as e:
        print(f"BrokerBin unavailable: {e}", file=sys.stderr)
        bb = brokerbin_api.summarize({"data": []}, {"data": []}, {"data": []})
        quota = None
    result = compute(market, draft, bb, label=a.label)
    if a.json:
        print(json.dumps({**result, "quota": quota}, indent=2, default=str))
    else:
        print(render(result))
        if quota:
            print("brokerbin quota: %s/%s today" % (quota.get("count"), quota.get("limit")))
    if a.apply:
        apply(draft_path, result)
        print(f"applied → {draft_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m pytest tests -v`
Expected: all PASS (Task 1: 2, Task 2: 7, Task 3: 6, Task 4: 4)

- [ ] **Step 5: Manual run against real drafts (mock BrokerBin first, then live)**

Write the HD223 market file for real: `cp tests/fixtures/hd223_market.json ~/Documents/01_Clients/mtgi/work/ebay/market/HD223.json` (create the dir). Then:
`BROKERBIN_MOCK=1 python3 scripts/channel_check.py MTGI-HD223` → table renders.
`python3 scripts/channel_check.py MTGI-HD223` → live BrokerBin (3 calls), quota line prints.

- [ ] **Step 6: Commit**

```bash
git add ebay-lister/skills/ebay-lister/scripts/channel_check.py ebay-lister/skills/ebay-lister/tests/
git commit -m "feat(ebay-lister): channel_check CLI — table, --json, --apply"
```

---

### Task 5: Reference docs — `channel-rules.md`, `market-json.md`, `spec.md`

**Files:**
- Create: `ebay-lister/skills/ebay-lister/reference/channel-rules.md`
- Create: `ebay-lister/skills/ebay-lister/reference/market-json.md`
- Modify: `ebay-lister/skills/ebay-lister/reference/spec.md` (fields table)

- [ ] **Step 1: Write `channel-rules.md`**

```markdown
# Channel rules — how the channel check decides

`scripts/channel_check.py` compares three ways to sell a SKU and recommends
one. It is advice; the operator decides. Constants below are mirrored in the
script's `RULES` dict — change both together.

## Inputs
- eBay: `market/<MPN>.json` (exact-SKU figures the AI filters from the operator's
  Seller Hub → Research → Product Research screenshots; see `market-json.md`).
- BrokerBin: live Search API v2 (`brokerbin_api.py`), cached 60 days:
  priced asks by seller (median excludes Micro Technologies), quote requests
  in the last 90 days, supply/demand histogram.
- Draft: `quantity`, `price`, `packageWeightAndSize`, optional `unit_cost`,
  optional `eol_date`.

## Constants (defaults)
| Name | Default | Meaning |
|---|---|---|
| fvf | 0.13 | eBay final value fee share |
| label_by_lb | ≤1 lb $8 · ≤3 lb $11 · ≤5 lb $14 · else $28 | per-unit label estimate when no `--label` |
| share_no_competitor | 0.70 | our share of eBay pace when no exact-SKU active |
| share_volume_seller | 0.30 | a volume seller sits at/below our ask |
| share_at_clearing | 0.50 | our ask ≤ sold median and watchers ≤ 2 |
| share_default | 0.40 | none of the above |
| bb_single_haircut | 0.65 | realized single-unit price as share of BrokerBin median ask |
| bb_lot_haircut | 0.55 | realized lot price as share of median ask |
| rfq_conversion | 0.25 | share of 90-day RFQs that become one unit sold |
| salvage / salvage_eol | 0.50 / 0.25 | value of leftovers at horizon, as share of n_b_lot |
| lot_min_qty | 5 | print the "lot of Q" line only from this qty |
| combo_tie_pct | 0.10 | prefer combo when top two are within this |
| thin_solds | 5 | flag when eBay exact-SKU solds are fewer |
| horizons | 3, 6 | months |

## Scenarios
- eBay only: sold = min(Q, pace × H); net = sold × n_e + leftover × salvage.
- BrokerBin only: sold = min(Q, rfq pace × H); net = sold × n_b_single +
  leftover × salvage; plus a separate "lot of Q" line at n_b_lot (weight 1.0
  if any RFQs, else 0.5).
- Combo: eBay singles for H months, remainder as a BrokerBin lot.
- Unbounded footnote: months to clear at pace, total net.
- EOL cap: `eol_date` clips H and drops salvage to 25%.
- No BrokerBin asks: BrokerBin cells n/a, verdict eBay, salvage 25% of n_e.

## Verdict
Highest 6-month net; tie-break 3-month; if the top two are within
`combo_tie_pct`, combo wins (diversifies). Rationale is one generated sentence.

## Tuning
After the first real BrokerBin trades, replace `bb_*_haircut` and
`rfq_conversion` with observed values (realized / median ask; units sold /
RFQs). After 60 days of eBay sales on a SKU, replace `share_*` with observed
(our sold / market sold in the window). Record changes here with a date.

## What it cannot see
BrokerBin does not report completed sales; its numbers are asks and demand
signals. eBay figures are only as good as the screenshot filtering. Neither
side knows MTGI's cost basis unless `unit_cost` is on the draft.
```

- [ ] **Step 2: Write `market-json.md`**

```markdown
# market/<MPN>.json — exact-SKU eBay figures

Written by the AI from the operator's two Seller Hub screenshots (Research →
Product Research → **Sold** and **Active**, All Categories, 3 years for slow
enterprise gear / 6 months for fast-moving parts). File name is the MPN
verbatim. Lives in the client workspace: `01_Clients/mtgi/work/ebay/market/`.

## Filtering rules (the AI does this, never the operator)
1. Keep only rows for the exact SKU and its condition family; drop variants
   (-XL, other port counts), accessories (adapters, transceivers), unrelated
   keyword hits, and "as-is / issue / for parts" rows unless that is our
   condition. List every exclusion in `exclusions`.
2. Unit-weight everything: a row with "total sold 17" counts 17 units.
3. All-in = item price + buyer-paid shipping.
4. Lots: record per-unit all-in in `lots_per_unit`, not in the singles pool.
5. Note the biggest single seller as `volume_seller` (all-in price, units).

## Schema
```json
{
  "mpn": "HD223",
  "condition_scope": "used, unit only",
  "captured": "2026-08-18",
  "ebay": {
    "window_months": 6,
    "sold_units": 51,
    "sold_avg_allin": 59.83,
    "sold_median_allin": 50.70,
    "volume_seller": {"price_allin": 50.70, "units": 24},
    "lots_per_unit": [35, 43, 45],
    "active_count": 40,
    "active_bare_range": [40, 65],
    "watchers_max": 4,
    "exclusions": "9 adapter rows, 3 HD1023, cross-stitch, Allison filter, Massey starter, 1 removed"
  },
  "notes": "Series 3 leaves BrightSign Author Dec 2026"
}
```
`volume_seller` may be `null`. `active_count` counts exact-SKU actives only.
Refresh the file whenever the operator pastes new screenshots; `captured` is
the screenshot date.
```

- [ ] **Step 3: Extend `spec.md`**

In the fields table of `reference/spec.md`, after the `packageWeightAndSize` row, add:
```markdown
| `unit_cost` | no | MTGI landed cost per unit (number). When present the channel check also reports margin. |
| `eol_date` | no | `YYYY-MM-DD` — vendor end-of-support or marketplace cutoff. Clips the channel-check horizon and lowers salvage. |
| `channel` | no | Written by `channel_check.py --apply`: `{verdict, checked_at, horizon_months, net{ebay,brokerbin,combo}, rationale, assumptions}`. Advice; publish does not read it. |
```

- [ ] **Step 4: Commit**

```bash
git add ebay-lister/skills/ebay-lister/reference/
git commit -m "docs(ebay-lister): channel-rules, market-json schema, spec fields for channel check"
```

---

### Task 6: SKILL.md step 1c + README

**Files:**
- Modify: `ebay-lister/skills/ebay-lister/SKILL.md` (insert after step 1b, before "### 2. Gather the listing facts")
- Modify: `ebay-lister/README.md` (Scripts table + a "Channel check" paragraph)

- [ ] **Step 1: Insert step 1c into SKILL.md**

Insert before `### 2. Gather the listing facts`:
```markdown
### 1c. Marketplace check — eBay, BrokerBin, or both

Before drafting, decide where the units should sell. This is scripted advice,
not a gate.

1. Ask the operator for two Seller Hub screenshots: Research → Product
   Research → **Sold** and **Active** for the MPN, category **All Categories**,
   window 3 years (slow enterprise gear) or 6 months (fast movers).
2. **You filter, never the operator**: keep only exact-SKU rows, drop
   variants/accessories/unrelated hits, unit-weight the counts, compute
   all-in prices, and write `01_Clients/mtgi/work/ebay/market/<MPN>.json`
   (schema and rules in `reference/market-json.md`). Show the exclusions in
   one line so the operator can sanity-check.
3. Run the check (BrokerBin is fetched live and cached; ~3 calls per MPN of a
   50/day quota):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ebay-lister/scripts/channel_check.py" <SKU-or-MPN>
```

4. Present the table as printed: eBay-only / BrokerBin-only / combo net at 3
   and 6 months, the unbounded footnote, the verdict and its one-line
   rationale, and the flags. Say which assumptions drove it
   (`reference/channel-rules.md`).
5. The operator decides. Record it with `--apply` (writes a `channel` block
   into the draft). If the verdict is `brokerbin` or `combo`, tell the operator
   what to change on MTGI's BrokerBin line (price/qty) — BrokerBin upload is
   MTGI's existing file process, not this skill — and note that eBay sales
   must be mirrored to BrokerBin qty.

If `market/<MPN>.json` does not exist the script says so and exits cleanly;
do not guess figures. If BrokerBin is unreachable it prints why and runs the
eBay-only side.
```

- [ ] **Step 2: Update README.md**

In the Scripts table add:
```markdown
| `brokerbin_api.py` | BrokerBin Search API v2: `search` / `rfq` / `supply` / `summary`, 60-day cache |
| `channel_check.py` | eBay vs BrokerBin vs combo net at 3 & 6 months; `--apply` records the verdict on the draft |
```
Add a section after "Safety":
```markdown
## Channel check

Not every SKU belongs on eBay. `channel_check.py` reads exact-SKU eBay sold
and active figures (from Seller Hub Product Research, filtered by the skill)
plus live BrokerBin asks and quote-request counts, and prints eBay-only /
BrokerBin-only / combo net revenue at 3 and 6 months with a recommendation.
Rules and constants: `skills/ebay-lister/reference/channel-rules.md`. Needs
Keychain `brokerbin-mtgi-api-token` (optional `brokerbin-mtgi-login`).
```

- [ ] **Step 3: Run the full test suite once more**

Run: `cd ebay-lister/skills/ebay-lister && python3 -m pytest tests -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add ebay-lister/skills/ebay-lister/SKILL.md ebay-lister/README.md
git commit -m "docs(ebay-lister): step 1c marketplace check + README"
```

---

### Task 7: Calibrate on the five researched SKUs

**Files:**
- Create: `01_Clients/mtgi/work/ebay/market/{ET91000SM20,C6800-16P10G,828,HD223,4K1042-WW}.json` (client workspace, not the repo)
- Modify: the five drafts in `01_Clients/mtgi/work/ebay/drafts/` (via `--apply`)
- Modify: `01_Clients/mtgi/work/ebay/drafts/README.md` (per-SKU verdict line)

- [ ] **Step 1: Write the five market files from the research already on file** (numbers from the drafts README, 2026-08-18):

`ET91000SM20.json` — window 36, sold_units 12 (≈4/yr per memory), sold_avg_allin 68, sold_median_allin 68, volume_seller null, lots_per_unit [], active_count 6, active_bare_range [180, 260], watchers_max 0, exclusions "none", notes "SFP-included units $75–100; no-SFP $34.99".
`C6800-16P10G.json` — window 36, sold_units 54, sold_avg_allin 101.83, sold_median_allin 85, volume_seller {127.76, 17}, lots_per_unit [], active_count 17, active_bare_range [64, 260], watchers_max 2, exclusions "7 -XL / 32-port / transceiver rows".
`828.json` — window 36, sold_units 5, sold_avg_allin 142.49, sold_median_allin 145.89, volume_seller null, lots_per_unit [], active_count 2, active_bare_range [103.55, 229], watchers_max 0, exclusions "3x 828WP, 890 LRE, 4 iPhone rows".
`HD223.json` — the fixture.
`4K1042-WW.json` — window 36, sold_units 64, sold_avg_allin 37.65, sold_median_allin 40, volume_seller {40, 23}, lots_per_unit [38.58, 35], active_count 12, active_bare_range [37.5, 80], watchers_max 2, exclusions "$5 auction, ISSUE-READ, AS/IS lot, lot-of-6 auction, 2 AC-adapter rows".

Add `eol_date` to the HD223 draft (`2026-12-01`), the 4K1042 draft (`2023-02-28` is past — use `null`; note EOTS in `notes`), and the C6800 draft (`2027-04-30`).

- [ ] **Step 2: Run live for all five** (15 quota calls):

```bash
S=~/Documents/02_Projects/mtgi-skills/ebay-lister/skills/ebay-lister/scripts
for k in MTGI-ET91000SM20 MTGI-C6800-16P10G MTGI-ENABLEIT-828 MTGI-HD223 MTGI-4K1042-WW; do python3 "$S/channel_check.py" $k; echo; done
```

- [ ] **Step 3: Sanity-check against the 2026-08-18 manual analysis** — expected shape: HD223 and C6800 → `ebay`; ET91000SM20, 828, 4K1042 → `combo` or `brokerbin`. If a verdict is obviously wrong, adjust one constant in `RULES` + `channel-rules.md` (dated note) and re-run; do not hand-edit results.

- [ ] **Step 4: Apply and record**

`--apply` on each; add a "Channel: <verdict> (<date>)" line to each SKU's section in `drafts/README.md`.

- [ ] **Step 5: Commit the plugin side (client workspace files are not in git)**

```bash
cd ~/Documents/02_Projects/mtgi-skills && git add -A ebay-lister && git commit -m "feat(ebay-lister): channel check calibrated on the first five SKUs"
```
