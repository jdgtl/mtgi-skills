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
        source = info["source"] or "not configured"
        print(f"  {_tick(info['set'])} {info['label']:30s} — {source}")
    print()

    bb_ready = cred_status.get("brokerbin_api_key", {}).get("set", False)
    brave_ready = cred_status.get("brave_search_api_key", {}).get("set", False)
    mtgi_ready = bool(
        os.environ.get("MTGI_API_URL") and os.environ.get("MTGI_API_TOKEN")
    )

    print("Enrichment tier status:")
    mtgi_detail = "configured" if mtgi_ready else "needs MTGI_API_URL + MTGI_API_TOKEN env vars"
    bb_detail = "configured" if bb_ready else "run /rfq-setup to add BrokerBin credentials"
    brave_detail = "configured" if brave_ready else "run /rfq-setup to add Brave Search key"
    print(f"  {_tick(mtgi_ready)} Tier 1: MTGI catalog       — {mtgi_detail}")
    print(f"  {_tick(bb_ready)} Tier 2: BrokerBin           — {bb_detail}")
    print(f"  {_tick(brave_ready)} Tier 3: Brave web search   — {brave_detail}")
    print()

    if not (bb_ready and brave_ready):
        print("To configure missing credentials, run: claude /rfq-setup")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
