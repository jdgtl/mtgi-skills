#!/usr/bin/env python3
"""Pre-flight for the ebay-lister skill.

Reports every prerequisite as ok / warn / fail so the skill can either proceed,
offer to fix the gap in-conversation, or route the operator to /ebay-setup.

Exit code 0 when publishing is possible, 1 when something blocks it.

    python check_setup.py
    python check_setup.py --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import credentials

REFRESH_WARN_DAYS = 30


def _check(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"check": name, "status": status, "detail": detail, "fix": fix}


def check_credentials() -> list[dict]:
    missing = credentials.missing_required()
    if missing:
        labels = [credentials.CREDENTIAL_SCHEMA[m]["label"] for m in missing]
        return [
            _check(
                "credentials",
                "fail",
                f"Not configured: {', '.join(labels)}",
                "Run /ebay-setup.",
            )
        ]
    return [_check("credentials", "ok", "eBay app keys and refresh token are stored.")]


def check_token() -> list[dict]:
    try:
        import auth
    except ImportError as e:
        return [_check("token", "fail", f"Could not import auth.py: {e}")]

    if credentials.missing_required():
        return [_check("token", "fail", "Cannot mint a token without credentials.", "Run /ebay-setup.")]

    out = []
    try:
        auth.get_access_token()
        out.append(_check("token", "ok", "Access token minted from the stored refresh token."))
    except auth.AuthError as e:
        return [
            _check(
                "token",
                "fail",
                str(e),
                "If the refresh token expired, re-run /ebay-setup to re-authorize.",
            )
        ]

    days = auth.refresh_days_remaining()
    if days is None:
        out.append(_check("refresh_expiry", "warn", "Refresh token expiry is unknown."))
    elif days < 0:
        out.append(_check("refresh_expiry", "fail", "Refresh token has expired.", "Run /ebay-setup."))
    elif days < REFRESH_WARN_DAYS:
        out.append(
            _check(
                "refresh_expiry",
                "warn",
                f"Refresh token expires in {days} days.",
                "Re-run /ebay-setup before it lapses.",
            )
        )
    else:
        out.append(_check("refresh_expiry", "ok", f"Refresh token valid for {days} more days."))
    return out


def check_policies() -> list[dict]:
    try:
        import ebay_api
        policies = ebay_api.list_policies()
    except Exception as e:  # noqa: BLE001 -- surface any failure as a check result
        return [_check("policies", "fail", f"Could not read business policies: {e}")]

    out = []
    for kind in ("fulfillment", "payment", "return"):
        entries = [p for p in policies.get(kind, []) if p.get("policyId")]
        if entries:
            names = ", ".join(p["name"] for p in entries[:3] if p.get("name"))
            out.append(_check(f"policy:{kind}", "ok", f"{len(entries)} found ({names})"))
        else:
            out.append(
                _check(
                    f"policy:{kind}",
                    "fail",
                    f"No {kind} policy on the account.",
                    f"The skill can create one -- ask it to set up a {kind} policy.",
                )
            )
    return out


def check_locations() -> list[dict]:
    try:
        import ebay_api
        locations = ebay_api.list_locations()
    except Exception as e:  # noqa: BLE001
        return [_check("location", "fail", f"Could not read inventory locations: {e}")]

    enabled = [l for l in locations if (l.get("status") or "ENABLED").upper() == "ENABLED"]
    if not enabled:
        return [
            _check(
                "location",
                "fail",
                "No enabled inventory location. publishOffer requires one.",
                "The skill can create one -- ask it to set up an inventory location.",
            )
        ]
    keys = ", ".join(l["merchantLocationKey"] for l in enabled[:3] if l.get("merchantLocationKey"))
    return [_check("location", "ok", f"{len(enabled)} enabled ({keys})")]


def check_r2() -> list[dict]:
    out = []
    if not shutil.which("npx"):
        out.append(
            _check("npx", "fail", "`npx` not found. Node.js is required to stage images.", "Install Node.js.")
        )
    else:
        out.append(_check("npx", "ok", "npx is available for `wrangler r2 object put`."))

    token_set = bool(
        __import__("os").environ.get("CLOUDFLARE_API_TOKEN")
        or __import__("os").environ.get("CLOUDFLARE_API_KEY")
    )
    if token_set:
        out.append(_check("cloudflare_auth", "ok", "CLOUDFLARE_API_TOKEN is set."))
    else:
        # `wrangler login` writes an OAuth config instead; can't detect it cheaply.
        out.append(
            _check(
                "cloudflare_auth",
                "warn",
                "CLOUDFLARE_API_TOKEN is not set. Uploads rely on a prior `npx wrangler login`.",
                "Set CLOUDFLARE_API_TOKEN with R2 write scope if uploads fail to authenticate.",
            )
        )

    base = (credentials.get("r2_public_base") or "").rstrip("/")
    if not base:
        out.append(_check("r2_public_base", "fail", "R2 public base URL is not configured.", "Run /ebay-setup."))
        return out

    try:
        req = urllib.request.Request(base + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except urllib.error.URLError as e:
        out.append(
            _check("r2_public_base", "fail", f"{base} is unreachable: {e.reason}", "Check the custom domain in Cloudflare.")
        )
        return out

    # A 404 at the bucket root is expected and healthy -- there is no object at "/".
    if status in (200, 401, 403, 404):
        out.append(_check("r2_public_base", "ok", f"{base} responds (HTTP {status})."))
    else:
        out.append(_check("r2_public_base", "warn", f"{base} returned HTTP {status}."))
    return out


def run_all() -> dict:
    results: list[dict] = []
    results += check_credentials()
    blocked = any(r["status"] == "fail" for r in results)
    if not blocked:
        results += check_token()
        blocked = any(r["status"] == "fail" for r in results)
    if not blocked:
        results += check_policies()
        results += check_locations()
    results += check_r2()

    return {
        "ok": not any(r["status"] == "fail" for r in results),
        "warnings": [r for r in results if r["status"] == "warn"],
        "failures": [r for r in results if r["status"] == "fail"],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ebay-lister pre-flight")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = run_all()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        symbols = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
        for r in report["results"]:
            print(f"[{symbols[r['status']]}] {r['check']}: {r['detail']}")
            if r["fix"] and r["status"] != "ok":
                print(f"         -> {r['fix']}")
        print()
        print("Ready to publish." if report["ok"] else "Blocked -- resolve the FAIL items above.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
