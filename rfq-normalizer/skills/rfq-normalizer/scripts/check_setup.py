#!/usr/bin/env python3
"""Report credential and enrichment-tier configuration for rfq-normalizer.

Run after install — or any time you suspect a tier isn't firing — to see
where each credential is being read from (env / file / keyring) and which
enrichment tiers are ready to run.

Exit code: 0 if all required tiers are configured, 1 otherwise. Useful for
scripted post-install verification.
"""
from __future__ import annotations
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from credentials import status as credentials_status  # noqa: E402


def _tick(ok: bool) -> str:
    return "✓" if ok else "✗"


def main() -> int:
    cred_status = credentials_status()

    print("Credential status:")
    for info in cred_status.values():
        if info.get("deprecated"):
            continue  # deprecated creds (e.g. BrokerBin) are no longer reported
        source = info["source"] or "not configured"
        label = info["label"]
        print(f"  {_tick(info['set'])} {label:34s} — {source}")
    print()

    ebay_ready = (
        cred_status.get("ebay_app_id", {}).get("set", False)
        and cred_status.get("ebay_cert_id", {}).get("set", False)
    )
    brave_ready = cred_status.get("brave_search_api_key", {}).get("set", False)
    mtgi_ready = bool(
        os.environ.get("MTGI_API_URL") and os.environ.get("MTGI_API_TOKEN")
    )

    print("Enrichment tier status:")
    mtgi_detail = "configured" if mtgi_ready else "optional — set MTGI_API_URL + MTGI_API_TOKEN to enable"
    ebay_detail = "configured" if ebay_ready else "run /rfq-setup to add EBAY_APP_ID + EBAY_CERT_ID"
    brave_detail = "configured" if brave_ready else "run /rfq-setup to add Brave Search key"
    print(f"  {_tick(mtgi_ready)} MTGI catalog (optional)  — {mtgi_detail}")
    print(f"  {_tick(ebay_ready)} eBay Browse API          — {ebay_detail}")
    print(f"  {_tick(brave_ready)} Brave web search         — {brave_detail}")
    print()

    # Local tier (vendor columns + regex + cache) always works. Enrichment of
    # missing fields needs at least one of eBay / Brave configured.
    if not (ebay_ready or brave_ready):
        print("No enrichment tier configured — only local regex/cache will run. "
              "Run /rfq-setup to add eBay and/or Brave credentials.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
