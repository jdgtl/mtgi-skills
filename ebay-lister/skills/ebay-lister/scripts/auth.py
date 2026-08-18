#!/usr/bin/env python3
"""eBay OAuth for the ebay-lister skill. Stdlib only.

Token model:
  authorization code  ~299s, single use   -- you paste it, ONCE
  refresh token       ~18 months          -- stored, machine-only
  access token        ~2 hours            -- cached, minted silently

After /ebay-setup you never touch OAuth again until the refresh token expires.

CLI:
    python auth.py url                 # build the consent URL (open in browser)
    python auth.py exchange <code>     # code -> refresh token, stored
    python auth.py token               # print a valid access token (refreshing if needed)
    python auth.py whoami              # token state + refresh expiry
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import credentials

# Refresh this far ahead of expiry so a token never dies mid-flight.
TOKEN_REFRESH_BUFFER_S = 60
REQUEST_TIMEOUT_S = 30

# The 12 scopes this skill needs. Joined with %20 -- NOT `+` and NOT %2B.
SCOPES: tuple[str, ...] = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
)

_HOSTS = {
    "production": {
        "api": "https://api.ebay.com",
        "auth": "https://auth.ebay.com/oauth2/authorize",
    },
    "sandbox": {
        "api": "https://api.sandbox.ebay.com",
        "auth": "https://auth.sandbox.ebay.com/oauth2/authorize",
    },
}


class AuthError(RuntimeError):
    """OAuth failed in a way the operator has to resolve."""


def environment() -> str:
    env = (credentials.get("ebay_environment") or "production").strip().lower()
    if env not in _HOSTS:
        raise AuthError(f"Unknown eBay environment '{env}'. Use production or sandbox.")
    return env


def api_base() -> str:
    return _HOSTS[environment()]["api"]


def _token_cache_path() -> Path:
    override = os.environ.get("EBAY_LISTER_TOKEN_CACHE")
    if override:
        return Path(override)
    return Path.home() / ".ebay-lister-token.json"


def _cache_read() -> dict:
    path = _token_cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _cache_write(data: dict) -> None:
    path = _token_cache_path()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def _require(name: str) -> str:
    value = credentials.get(name, use_default=False)
    if not value:
        label = credentials.CREDENTIAL_SCHEMA[name]["label"]
        raise AuthError(f"{label} is not configured. Run /ebay-setup.")
    return value


def _basic_auth_header() -> str:
    raw = f"{_require('ebay_client_id')}:{_require('ebay_client_secret')}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _post_token(payload: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"{api_base()}/identity/v1/oauth2/token",
        data=body,
        headers={
            "Authorization": _basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise AuthError(f"eBay token endpoint returned {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise AuthError(f"Could not reach eBay token endpoint: {e.reason}") from e


def build_consent_url(state: str = "ebay_lister") -> str:
    """Build the consent URL by hand.

    eBay's own `get_oauth_url` helpers have historically emitted a broken URL
    (empty state=, trailing hd=, a signin.ebay.com/signin?ru= wrapper that eBay
    rejects with invalid_request). Building it from the documented params avoids
    all of that. Scopes are %20-joined via quote(), never `+`.
    """
    params = {
        "client_id": _require("ebay_client_id"),
        "response_type": "code",
        "redirect_uri": _require("ebay_redirect_uri"),  # the RuName, not a URL
        "scope": " ".join(SCOPES),
        "state": state,
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{_HOSTS[environment()]['auth']}?{query}"


def exchange_code(code: str) -> dict:
    """Exchange a single-use authorization code for a refresh token.

    The code expires in ~299 seconds. Store the refresh token immediately --
    eBay will not hand it out again without a fresh consent round-trip.
    """
    # eBay URL-encodes the code in the redirect. Decode before sending it back.
    data = _post_token(
        {
            "grant_type": "authorization_code",
            "code": urllib.parse.unquote(code.strip()),
            "redirect_uri": _require("ebay_redirect_uri"),
        }
    )
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise AuthError(f"No refresh_token in eBay's response: {json.dumps(data)[:400]}")

    credentials.set_("ebay_refresh_token", refresh_token)
    expires_in = int(data.get("refresh_token_expires_in", 0))
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        credentials.set_("ebay_refresh_expires_at", expires_at.isoformat())

    _cache_access_token(data)
    return {
        "refresh_token_stored": True,
        "refresh_expires_at": credentials.get("ebay_refresh_expires_at"),
        "access_token_expires_in": data.get("expires_in"),
    }


def _cache_access_token(data: dict) -> str:
    access_token = data.get("access_token")
    if not access_token:
        raise AuthError(f"No access_token in eBay's response: {json.dumps(data)[:400]}")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 7200)))
    _cache_write({"access_token": access_token, "expires_at": expires_at.isoformat()})
    return access_token


def get_access_token(force_refresh: bool = False) -> str:
    """Return a valid access token, minting a new one from the refresh token
    when the cached one is inside the expiry buffer. Silent and automatic."""
    if not force_refresh:
        cached = _cache_read()
        raw_expiry = cached.get("expires_at")
        if cached.get("access_token") and raw_expiry:
            try:
                expires_at = datetime.fromisoformat(raw_expiry)
                remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
                if remaining > TOKEN_REFRESH_BUFFER_S:
                    return cached["access_token"]
            except ValueError:
                pass  # Malformed cache -- fall through and refresh.

    data = _post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": _require("ebay_refresh_token"),
            "scope": " ".join(SCOPES),
        }
    )
    # eBay may rotate the refresh token. Persist a new one if it sends it.
    rotated = data.get("refresh_token")
    if rotated:
        credentials.set_("ebay_refresh_token", rotated)
        rotated_expiry = data.get("refresh_token_expires_in")
        if rotated_expiry:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(rotated_expiry))
            credentials.set_("ebay_refresh_expires_at", expires_at.isoformat())
    return _cache_access_token(data)


def refresh_days_remaining() -> int | None:
    """Days until the refresh token expires, or None if unknown."""
    raw = credentials.get("ebay_refresh_expires_at", use_default=False)
    if not raw:
        return None
    try:
        return (datetime.fromisoformat(raw) - datetime.now(timezone.utc)).days
    except ValueError:
        return None


def whoami() -> dict:
    cached = _cache_read()
    return {
        "environment": environment(),
        "refresh_token_stored": bool(credentials.get("ebay_refresh_token", use_default=False)),
        "refresh_expires_at": credentials.get("ebay_refresh_expires_at", use_default=False),
        "refresh_days_remaining": refresh_days_remaining(),
        "access_token_cached": bool(cached.get("access_token")),
        "access_token_expires_at": cached.get("expires_at"),
        "missing_credentials": credentials.missing_required(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eBay OAuth for ebay-lister")
    sub = parser.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("url")
    u.add_argument("--state", default="ebay_lister")
    e = sub.add_parser("exchange")
    e.add_argument("code")
    t = sub.add_parser("token")
    t.add_argument("--force-refresh", action="store_true")
    sub.add_parser("whoami")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "url":
            print(build_consent_url(args.state))
        elif args.cmd == "exchange":
            print(json.dumps(exchange_code(args.code), indent=2))
        elif args.cmd == "token":
            print(get_access_token(force_refresh=args.force_refresh))
        elif args.cmd == "whoami":
            print(json.dumps(whoami(), indent=2))
    except AuthError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
