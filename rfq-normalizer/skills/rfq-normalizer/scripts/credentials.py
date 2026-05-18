#!/usr/bin/env python3
"""Per-user credential store for the rfq-normalizer skill.

Wraps the `keyring` PyPI package, which uses the native secure store on each
platform: macOS Keychain, Windows Credential Manager, or Linux Secret Service
(GNOME Keyring / KWallet). This gives consistent, OS-level protection across
all three platforms without OS-specific code paths in the skill.

Resolution order for each credential:
  1. Environment variable (for dev / CI / power users)
  2. System keyring (macOS / Windows / Linux native store)
  3. None — caller should prompt the user via /rfq-setup

CLI:
    python credentials.py status
    python credentials.py get brokerbin_api_key
    python credentials.py set brokerbin_api_key sk-XXXXX
    python credentials.py delete brokerbin_api_key

Requires: `pip install keyring`  (see requirements.txt at the skill root).
"""
from __future__ import annotations
import argparse
import json
import os
import sys

try:
    import keyring
    import keyring.errors
except ImportError:
    sys.stderr.write(
        "ERROR: the `keyring` Python package is required.\n"
        "Install it with:  python -m pip install --user keyring\n"
        "Or:               pip install -r skills/rfq-normalizer/requirements.txt\n"
    )
    sys.exit(2)


# Schema: every credential the skill knows about. Add entries here as new
# tiers come online. The /rfq-setup flow walks this dict.
CREDENTIAL_SCHEMA: dict[str, dict[str, str]] = {
    "brokerbin_api_key": {
        "env": "BROKERBIN_API_KEY",
        "label": "BrokerBin API key",
        "help": "Contact your BrokerBin account rep to provision (David Lewis: david@brokerbin.com).",
    },
    "brokerbin_login": {
        "env": "BROKERBIN_LOGIN",
        "label": "BrokerBin login (username)",
        "help": "Your BrokerBin account username. Some accounts require this in addition to the API key.",
    },
    "brave_search_api_key": {
        "env": "BRAVE_SEARCH_API_KEY",
        "label": "Brave Search API key",
        "help": "Sign up at https://api.search.brave.com/app/signup (free tier: 2000 queries/month).",
    },
}

# `service` is what keyring scopes the entry to; `account` is the credential
# name. On macOS this maps to Keychain's kSecAttrService / kSecAttrAccount;
# on Windows to Credential Manager's TargetName; on Linux to Secret Service
# label attributes. All three back-ends key on the pair.
KEYRING_SERVICE = "rfq-normalizer"


def _assert_known(name: str) -> dict[str, str]:
    schema = CREDENTIAL_SCHEMA.get(name)
    if not schema:
        raise KeyError(
            f"Unknown credential '{name}'. Known: {sorted(CREDENTIAL_SCHEMA)}"
        )
    return schema


def _keyring_get(name: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.NoKeyringError:
        return None


def get(name: str) -> str | None:
    """Resolve a credential by name. Returns None if unset everywhere."""
    schema = _assert_known(name)
    env_value = os.environ.get(schema["env"])
    if env_value:
        return env_value
    return _keyring_get(name)


def set_(name: str, value: str) -> None:
    """Persist a credential to the system keyring."""
    _assert_known(name)
    if not value:
        raise ValueError(f"Refusing to store empty value for {name}")
    try:
        keyring.set_password(KEYRING_SERVICE, name, value)
    except keyring.errors.NoKeyringError as e:
        raise RuntimeError(
            f"No system keyring available ({e}). Set the env var "
            f"{CREDENTIAL_SCHEMA[name]['env']} instead, or install a keyring "
            f"backend (macOS: built-in; Windows: built-in; Linux: install "
            f"`secretstorage` and run a Secret Service daemon)."
        ) from e


def delete(name: str) -> None:
    """Remove a credential from the system keyring. Silent if not present."""
    _assert_known(name)
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except (keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        pass


def status() -> dict[str, dict]:
    """Report each known credential's source and presence.

    Returns {name: {"label": str, "source": "env"|"keyring"|None, "set": bool}}.
    """
    out: dict[str, dict] = {}
    for name, schema in CREDENTIAL_SCHEMA.items():
        label = schema["label"]
        if os.environ.get(schema["env"]):
            out[name] = {"label": label, "source": "env", "set": True}
            continue
        if _keyring_get(name):
            out[name] = {"label": label, "source": "keyring", "set": True}
        else:
            out[name] = {"label": label, "source": None, "set": False}
    return out


def backend_name() -> str:
    """Human-readable name of the active keyring backend, for diagnostics."""
    try:
        return str(keyring.get_keyring())
    except Exception as e:
        return f"<unavailable: {e}>"


def _main() -> int:
    ap = argparse.ArgumentParser(description="rfq-normalizer credential store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show source + presence of every known credential")
    sub.add_parser("backend", help="show the active keyring backend (diagnostic)")
    p_get = sub.add_parser("get", help="print a credential value to stdout")
    p_get.add_argument("name")
    p_set = sub.add_parser("set", help="store a credential")
    p_set.add_argument("name")
    p_set.add_argument("value")
    p_del = sub.add_parser("delete", help="remove a credential")
    p_del.add_argument("name")
    args = ap.parse_args()

    if args.cmd == "status":
        json.dump(status(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.cmd == "backend":
        print(backend_name())
        return 0
    if args.cmd == "get":
        v = get(args.name)
        if v is None:
            print(f"<unset> ({args.name})", file=sys.stderr)
            return 1
        sys.stdout.write(v)
        return 0
    if args.cmd == "set":
        set_(args.name, args.value)
        print(f"saved {args.name}")
        return 0
    if args.cmd == "delete":
        delete(args.name)
        print(f"deleted {args.name}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main())
