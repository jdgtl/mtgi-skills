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

    brave_ready = cred_status.get("brave_search_api_key", {}).get("set", False)
    icecat_ready = cred_status.get("icecat_token", {}).get("set", False)

    print("Enrichment tier status:")
    brave_detail = "configured" if brave_ready else "run /rfq-setup to add Brave Search key"
    icecat_detail = "configured" if icecat_ready else "optional — rarely useful on enterprise drives"
    print(f"  ✓ Decoder engine          — always available (offline, free)")
    print(f"  {_tick(brave_ready)} Brave web search         — {brave_detail}")
    print(f"  {_tick(icecat_ready)} ICEcat (optional)        — {icecat_detail}")
    print()

    # The decoder engine resolves most rows with no credentials at all. Brave is
    # the network fallback for type/interface/form on rows the decoders can't
    # resolve; without it, those rows go to the needs-review list.
    if not brave_ready:
        print("Brave not configured — decoders still run, but unresolved rows can't use "
              "the web fallback and will land on the needs-review list. Run /rfq-setup to add it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
