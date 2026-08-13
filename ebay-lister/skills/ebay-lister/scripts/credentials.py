#!/usr/bin/env python3
"""Per-user credential store for the ebay-lister skill.

Mirrors the resolution order used by rfq-normalizer's credentials.py so both
plugins behave identically:

  1. Environment variable (dev / CI / power users)
  2. chmod-600 file (durable persistence -- survives sandbox resets)
  3. System keyring (local Macs with a real backend)
  4. None -- caller routes the user to /ebay-setup

File path resolution:
  1. $EBAY_LISTER_CREDS_FILE      (explicit override)
  2. $HOME/.ebay-lister.env       (default)

File format: `KEY=value` lines, keys matching the `env` names below.

CLI:
    python credentials.py status
    python credentials.py get ebay_client_id
    python credentials.py set ebay_client_id XXXXX
    python credentials.py delete ebay_client_id
    python credentials.py backend
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import keyring
    import keyring.errors

    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False


CREDENTIAL_SCHEMA: dict[str, dict[str, str]] = {
    "ebay_client_id": {
        "env": "EBAY_CLIENT_ID",
        "label": "eBay App ID (Client ID)",
        "help": "From developer.ebay.com > Application Keys > Production.",
    },
    "ebay_client_secret": {
        "env": "EBAY_CLIENT_SECRET",
        "label": "eBay Cert ID (Client Secret)",
        "help": "From developer.ebay.com > Application Keys > Production.",
    },
    "ebay_redirect_uri": {
        "env": "EBAY_REDIRECT_URI",
        "label": "eBay RuName (redirect URI)",
        "help": "The RuName string, NOT a URL. developer.ebay.com > User Tokens > Get a Token from eBay via Your Application.",
    },
    "ebay_refresh_token": {
        "env": "EBAY_REFRESH_TOKEN",
        "label": "eBay refresh token",
        "help": "Written by /ebay-setup after the one-time OAuth flow. Valid ~18 months.",
    },
    "ebay_refresh_expires_at": {
        "env": "EBAY_REFRESH_EXPIRES_AT",
        "label": "Refresh token expiry (ISO 8601)",
        "help": "Written by /ebay-setup alongside the refresh token. Used to warn before the 18-month wall.",
    },
    "ebay_environment": {
        "env": "EBAY_ENVIRONMENT",
        "label": "eBay environment",
        "help": "`production` or `sandbox`. Defaults to production.",
    },
    "r2_bucket": {
        "env": "EBAY_LISTER_R2_BUCKET",
        "label": "Cloudflare R2 bucket",
        "help": "Bucket that stages listing images. Defaults to `mtgi`.",
    },
    "r2_public_base": {
        "env": "EBAY_LISTER_R2_PUBLIC_BASE",
        "label": "R2 public base URL",
        "help": "Public custom domain for the bucket, no trailing slash. Defaults to https://assets.mtgi-inc.com.",
    },
    "r2_prefix": {
        "env": "EBAY_LISTER_R2_PREFIX",
        "label": "R2 key prefix",
        "help": "Key prefix for staged images. Defaults to `listings`.",
    },
}

# Values used when a credential is unset. These are configuration, not secrets.
DEFAULTS: dict[str, str] = {
    "ebay_environment": "production",
    "r2_bucket": "mtgi",
    "r2_public_base": "https://assets.mtgi-inc.com",
    "r2_prefix": "listings",
}

# Credentials the skill cannot run without. `/ebay-setup` prompts for these.
REQUIRED: tuple[str, ...] = (
    "ebay_client_id",
    "ebay_client_secret",
    "ebay_redirect_uri",
    "ebay_refresh_token",
)

KEYRING_SERVICE = "ebay-lister"


def _assert_known(name: str) -> dict[str, str]:
    schema = CREDENTIAL_SCHEMA.get(name)
    if not schema:
        raise KeyError(f"Unknown credential '{name}'. Known: {sorted(CREDENTIAL_SCHEMA)}")
    return schema


def _creds_file_path() -> Path:
    explicit = os.environ.get("EBAY_LISTER_CREDS_FILE")
    if explicit:
        return Path(explicit)
    return Path.home() / ".ebay-lister.env"


def _file_read_all() -> dict[str, str]:
    path = _creds_file_path()
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _file_write_all(values: dict[str, str]) -> None:
    path = _creds_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(values.items())]
    content = "\n".join(lines) + ("\n" if lines else "")
    # O_CREAT|O_WRONLY|O_TRUNC at 0o600 so the file is never world-readable,
    # even briefly; then atomic replace so a crash can't truncate the live file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def _file_get(name: str) -> str | None:
    return _file_read_all().get(CREDENTIAL_SCHEMA[name]["env"])


def _keyring_get(name: str) -> str | None:
    if not _KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.NoKeyringError:
        return None


def get(name: str, use_default: bool = True) -> str | None:
    """Resolve a credential. Falls back to DEFAULTS unless use_default=False."""
    schema = _assert_known(name)
    env_value = os.environ.get(schema["env"])
    if env_value:
        return env_value
    file_value = _file_get(name)
    if file_value:
        return file_value
    kr_value = _keyring_get(name)
    if kr_value:
        return kr_value
    return DEFAULTS.get(name) if use_default else None


def set_(name: str, value: str) -> None:
    """Persist a credential to the chmod-600 file, or the keyring if unwritable."""
    _assert_known(name)
    if not value:
        raise ValueError(f"Refusing to store empty value for {name}")
    env_name = CREDENTIAL_SCHEMA[name]["env"]
    path = _creds_file_path()
    try:
        values = _file_read_all()
        values[env_name] = value
        _file_write_all(values)
        return
    except OSError as file_err:
        if not _KEYRING_AVAILABLE:
            raise RuntimeError(
                f"Could not write credentials file at {path}: {file_err}. "
                f"Set the env var {env_name} instead, or set "
                f"EBAY_LISTER_CREDS_FILE to a writable path."
            ) from file_err
        try:
            keyring.set_password(KEYRING_SERVICE, name, value)
        except keyring.errors.NoKeyringError as e:
            raise RuntimeError(
                f"Could not write {path} ({file_err}) and no system keyring is "
                f"available ({e}). Set the env var {env_name} instead."
            ) from e


def delete(name: str) -> None:
    """Remove a credential from both file and keyring. Silent if absent."""
    _assert_known(name)
    env_name = CREDENTIAL_SCHEMA[name]["env"]
    try:
        values = _file_read_all()
        if env_name in values:
            del values[env_name]
            _file_write_all(values)
    except OSError:
        pass
    if _KEYRING_AVAILABLE:
        try:
            keyring.delete_password(KEYRING_SERVICE, name)
        except (keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
            pass


def status() -> dict[str, dict]:
    """Report each credential's source and presence.

    `set` is True only for a real stored value -- a DEFAULTS fallback reports
    source "default" so /ebay-setup can tell configuration from secrets.
    """
    out: dict[str, dict] = {}
    file_values = _file_read_all()
    for name, schema in CREDENTIAL_SCHEMA.items():
        entry = {
            "label": schema["label"],
            "required": name in REQUIRED,
            "source": None,
            "set": False,
        }
        if os.environ.get(schema["env"]):
            entry.update(source="env", set=True)
        elif file_values.get(schema["env"]):
            entry.update(source="file", set=True)
        elif _keyring_get(name):
            entry.update(source="keyring", set=True)
        elif name in DEFAULTS:
            entry.update(source="default", set=True, value=DEFAULTS[name])
        out[name] = entry
    return out


def missing_required() -> list[str]:
    """Required credential names with no stored value."""
    return [n for n in REQUIRED if not get(n, use_default=False)]


def backend_name() -> str:
    """Diagnostic -- where would set_() store a new value?"""
    path = _creds_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".ebay-lister-write-probe"
        fd = os.open(probe, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.close(fd)
        os.unlink(probe)
        return f"file:{path}"
    except OSError:
        return "keyring" if _KEYRING_AVAILABLE else "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ebay-lister credential store")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("backend")
    sub.add_parser("missing")
    g = sub.add_parser("get")
    g.add_argument("name")
    s = sub.add_parser("set")
    s.add_argument("name")
    s.add_argument("value")
    d = sub.add_parser("delete")
    d.add_argument("name")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "status":
            print(json.dumps(status(), indent=2))
        elif args.cmd == "missing":
            print(json.dumps(missing_required()))
        elif args.cmd == "backend":
            print(backend_name())
        elif args.cmd == "get":
            value = get(args.name)
            if value is None:
                print(f"{args.name} is not set", file=sys.stderr)
                return 1
            print(value)
        elif args.cmd == "set":
            set_(args.name, args.value)
            print(f"stored {args.name}")
        elif args.cmd == "delete":
            delete(args.name)
            print(f"deleted {args.name}")
    except (KeyError, ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
