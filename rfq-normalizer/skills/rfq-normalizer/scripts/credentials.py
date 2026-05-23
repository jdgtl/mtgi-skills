#!/usr/bin/env python3
"""Per-user credential store for the rfq-normalizer skill.

Resolution order for each credential (first match wins):
  1. Environment variable (for dev / CI / power users)
  2. chmod-600 file in the workspace folder (Cowork-durable persistence)
  3. System keyring (genuine local-Mac installs with a real backend)
  4. None — caller should prompt the user via /rfq-setup

The file path resolves in this order:
  1. $RFQ_CREDS_FILE                       (explicit override)
  2. <workspace_dir>/.rfq-normalizer.env   (default)
  3. $HOME/.rfq-normalizer.env             (last resort)

File format: `KEY=value` lines. The keys match the env-var names in
CREDENTIAL_SCHEMA (BROKERBIN_API_KEY, BRAVE_SEARCH_API_KEY, etc.).

CLI:
    python credentials.py status
    python credentials.py get brokerbin_api_key
    python credentials.py set brokerbin_api_key sk-XXXXX
    python credentials.py delete brokerbin_api_key
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
    "brokerbin_api_key": {
        "env": "BROKERBIN_API_KEY",
        "label": "BrokerBin API key",
        "help": "Contact your BrokerBin account rep to provision.",
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

KEYRING_SERVICE = "rfq-normalizer"


def _assert_known(name: str) -> dict[str, str]:
    schema = CREDENTIAL_SCHEMA.get(name)
    if not schema:
        raise KeyError(
            f"Unknown credential '{name}'. Known: {sorted(CREDENTIAL_SCHEMA)}"
        )
    return schema


def _creds_file_path() -> Path:
    explicit = os.environ.get("RFQ_CREDS_FILE")
    if explicit:
        return Path(explicit)
    try:
        from workspace import workspace_dir
        return workspace_dir() / ".rfq-normalizer.env"
    except Exception:
        return Path.home() / ".rfq-normalizer.env"


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
    # Open with O_CREAT | O_WRONLY | O_TRUNC at mode 0o600 so the file is
    # never world-readable, even briefly. Then os.replace() into place
    # atomically so a crash mid-write can't truncate the live file.
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
    env_name = CREDENTIAL_SCHEMA[name]["env"]
    return _file_read_all().get(env_name)


def _keyring_get(name: str) -> str | None:
    if not _KEYRING_AVAILABLE:
        return None
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
    file_value = _file_get(name)
    if file_value:
        return file_value
    return _keyring_get(name)


def set_(name: str, value: str) -> None:
    """Persist a credential to the workspace file (preferred) or keyring.

    Writes to the file source by default — that's the only storage that
    survives a Cowork sandbox reset. Keyring is only used when the file path
    isn't writable (e.g. a hardened sandbox).
    """
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
                f"RFQ_CREDS_FILE to a writable path."
            ) from file_err
        try:
            keyring.set_password(KEYRING_SERVICE, name, value)
        except keyring.errors.NoKeyringError as e:
            raise RuntimeError(
                f"Could not write {path} ({file_err}) and no system keyring "
                f"is available ({e}). Set the env var {env_name} instead, "
                f"or set RFQ_CREDS_FILE to a writable path."
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
    """Report each known credential's source and presence.

    Returns {name: {"label": str, "source": "env"|"file"|"keyring"|None, "set": bool}}.
    """
    out: dict[str, dict] = {}
    file_values = _file_read_all()
    for name, schema in CREDENTIAL_SCHEMA.items():
        label = schema["label"]
        if os.environ.get(schema["env"]):
            out[name] = {"label": label, "source": "env", "set": True}
            continue
        if file_values.get(schema["env"]):
            out[name] = {"label": label, "source": "file", "set": True}
            continue
        if _keyring_get(name):
            out[name] = {"label": label, "source": "keyring", "set": True}
        else:
            out[name] = {"label": label, "source": None, "set": False}
    return out


def backend_name() -> str:
    """Human-readable diagnostic — where would set_() store a new value?"""
    path = _creds_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.access(path.parent, os.W_OK):
            return f"file: {path}"
    except OSError:
        pass
    if _KEYRING_AVAILABLE:
        try:
            return f"keyring: {keyring.get_keyring()}"
        except Exception as e:
            return f"<keyring unavailable: {e}>"
    return "<no writable backend — use env vars>"


def _main() -> int:
    ap = argparse.ArgumentParser(description="rfq-normalizer credential store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show source + presence of every known credential")
    sub.add_parser("backend", help="show where set_() would write (diagnostic)")
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
