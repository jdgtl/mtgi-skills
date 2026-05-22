# rfq-normalizer v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all 7 changes from `rfq-normalizer-v2-spec.md` so the skill runs end-to-end in Cowork without manual workarounds: credentials and cache persist across sandbox resets, batch enrichment is parallel and resumable, historical pricing isn't destroyed by consolidation, and small bugs in size parsing and MPN scoring are fixed.

**Architecture:** Surgical edits to a working pipeline. We do **not** rewrite the core (`parse_vendor`, `write_template`, the BrokerBin/Brave clients, `manufacturer_aliases`, `analyze_columns`). We rewrite two environment-coupled modules (`credentials.py`, `cache.py`) and the `enrich_mpn.py` batch loop, and we apply surgical fixes elsewhere. Persistence model switches from "OS keyring" to "chmod-600 file in a persistent workspace folder," because that's the only storage that survives a Cowork sandbox reset.

**Tech Stack:** Python 3.11+ (stdlib + `keyring` + `pytest`). The skill scripts are CLIs invoked by SKILL.md; no service layer. Tests are pytest, added in Task 1.

---

## File Structure

**Create:**
- `rfq-normalizer/skills/rfq-normalizer/tests/__init__.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/conftest.py` — pytest fixture wiring; adds `scripts/` to `sys.path`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_credentials.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_check_setup.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_consolidate_historical.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_mpn_patterns.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/test_candidate_validation.py`
- `rfq-normalizer/skills/rfq-normalizer/tests/fixtures/agis-sample.json` (sanitized regression fixture)
- `rfq-normalizer/skills/rfq-normalizer/scripts/workspace.py` — shared workspace-dir detection helper
- `rfq-normalizer/skills/rfq-normalizer/requirements-dev.txt`

**Modify:**
- `rfq-normalizer/skills/rfq-normalizer/scripts/cache.py` — resolution order + file locking
- `rfq-normalizer/skills/rfq-normalizer/scripts/credentials.py` — add file source
- `rfq-normalizer/skills/rfq-normalizer/scripts/check_setup.py` — render `file` source
- `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py` — batch loop rewrite (lines 685-711) + candidate validation in `tier_web_search` (lines 346-368) + confidence policy
- `rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py` — decimal GB/MB regex (line 21) + multi-text-source API
- `rfq-normalizer/skills/rfq-normalizer/scripts/consolidate_duplicates.py` — historical key
- `rfq-normalizer/skills/rfq-normalizer/scripts/mpn_patterns.py` — prefix DB + brand-prefix strip
- `rfq-normalizer/skills/rfq-normalizer/commands/rfq-setup.md` — write to workspace env file, not keychain
- `rfq-normalizer/skills/rfq-normalizer/SKILL.md` — confidence policy, settings form, Cowork pre-flight
- `rfq-normalizer/skills/rfq-normalizer/requirements.txt` — pin `keyring` only (already there)
- `rfq-normalizer/.claude-plugin/plugin.json` — bump version to 0.5.0 in final task

**Keep verbatim:** `parse_vendor.py`, `write_template.py`, `brokerbin_client.py`, `brave_client.py`, `manufacturer_aliases.py`, `analyze_columns.py`.

---

## Conventions

- **All commands run from the repo root** (`mtgi-skills/`) unless noted.
- **Pytest invocation:** `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/ -v`
- **Skill root abbreviation:** `SR=rfq-normalizer/skills/rfq-normalizer` — used in this doc to keep lines short. When typing commands, expand it.
- **Workspace dir env var:** `RFQ_WORKSPACE_DIR` (new). Defaults to autodetect → `$HOME`.
- **Commit style:** matches existing `chore: …` / `feat: …` short imperatives. Include the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

---

## Phase 1 — Environment & persistence (Cowork-native)

### Task 1: Bootstrap pytest harness

**Files:**
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/__init__.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/conftest.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/requirements-dev.txt`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_smoke.py` (deleted at end of task)

- [ ] **Step 1: Create the dev requirements file**

Write `rfq-normalizer/skills/rfq-normalizer/requirements-dev.txt`:

```
# Test-time dependencies. Install with:
#   python -m pip install --user -r requirements-dev.txt
pytest>=8.0
```

- [ ] **Step 2: Create the test package init**

Write `rfq-normalizer/skills/rfq-normalizer/tests/__init__.py` as an empty file.

- [ ] **Step 3: Create conftest.py to add scripts/ to sys.path**

Write `rfq-normalizer/skills/rfq-normalizer/tests/conftest.py`:

```python
"""Shared pytest configuration for the rfq-normalizer test suite.

Adds the skill's scripts/ folder to sys.path so tests can `import cache`,
`import credentials`, etc. without packaging the skill.
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
```

- [ ] **Step 4: Write a smoke test that imports a real module**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_smoke.py`:

```python
def test_can_import_cache_module():
    import cache
    assert hasattr(cache, "get")
    assert hasattr(cache, "put")
```

- [ ] **Step 5: Install pytest and run the smoke test**

Run:

```bash
python -m pip install --user -r rfq-normalizer/skills/rfq-normalizer/requirements-dev.txt
cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/ -v
```

Expected: `1 passed`. If `import keyring` fails, install via `pip install --user keyring`.

- [ ] **Step 6: Delete the smoke test (it was just proving the harness works)**

Run: `rm rfq-normalizer/skills/rfq-normalizer/tests/test_smoke.py`

- [ ] **Step 7: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/tests/__init__.py \
        rfq-normalizer/skills/rfq-normalizer/tests/conftest.py \
        rfq-normalizer/skills/rfq-normalizer/requirements-dev.txt
git commit -m "$(cat <<'EOF'
chore: add pytest harness for rfq-normalizer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Workspace-dir helper (`workspace.py`)

**Files:**
- Create: `rfq-normalizer/skills/rfq-normalizer/scripts/workspace.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_workspace.py`

- [ ] **Step 1: Write the failing test**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_workspace.py`:

```python
import os
from pathlib import Path

import workspace


def test_explicit_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("RFQ_WORKSPACE_DIR", str(tmp_path))
    assert workspace.workspace_dir() == tmp_path


def test_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    # Force the autodetect candidates to be unreachable
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    result = workspace.workspace_dir()
    assert result == Path.home()


def test_autodetect_picks_first_existing(monkeypatch, tmp_path):
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", (tmp_path,))
    assert workspace.workspace_dir() == tmp_path


def test_creates_dir_if_writable_but_missing(monkeypatch, tmp_path):
    target = tmp_path / "deep" / "subdir"
    monkeypatch.setenv("RFQ_WORKSPACE_DIR", str(target))
    result = workspace.workspace_dir()
    assert result == target
    assert target.is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_workspace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'workspace'`.

- [ ] **Step 3: Implement `workspace.py`**

Write `rfq-normalizer/skills/rfq-normalizer/scripts/workspace.py`:

```python
"""Workspace-folder detection for the rfq-normalizer skill.

Returns a directory that persists across Cowork sandbox resets, so the
skill can store credentials and cache files there.

Resolution order:
  1. $RFQ_WORKSPACE_DIR (explicit override)
  2. First writable path from _AUTODETECT_CANDIDATES (Cowork mounts)
  3. $HOME

Always returns a directory that exists and is writable.
"""
from __future__ import annotations
import os
from pathlib import Path

# Common persistent-mount paths in Cowork-style sandboxes, in priority order.
_AUTODETECT_CANDIDATES: tuple[Path, ...] = (
    Path("/mnt/user-data"),
    Path("/workspace"),
)


def _is_writable_dir(p: Path) -> bool:
    return p.is_dir() and os.access(p, os.W_OK)


def workspace_dir() -> Path:
    explicit = os.environ.get("RFQ_WORKSPACE_DIR")
    if explicit:
        p = Path(explicit)
        p.mkdir(parents=True, exist_ok=True)
        return p

    for candidate in _AUTODETECT_CANDIDATES:
        if _is_writable_dir(candidate):
            return candidate

    return Path.home()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_workspace.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/workspace.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_workspace.py
git commit -m "$(cat <<'EOF'
feat: add workspace-dir helper for persistent storage

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Cache directory resolution + never crash on read-only skill folder

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/cache.py` (lines 8-12, 34-42)
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py`

- [ ] **Step 1: Write the failing test**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py`:

```python
import importlib
import os
import stat
from pathlib import Path

import cache


def _reload(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    importlib.reload(cache)
    return cache


def test_explicit_cache_dir_env_var_wins(monkeypatch, tmp_path):
    target = tmp_path / "explicit-cache"
    c = _reload(monkeypatch, RFQ_CACHE_DIR=str(target), RFQ_WORKSPACE_DIR=None)
    assert c._cache_dir() == target
    assert target.is_dir()


def test_falls_back_to_workspace_when_no_env(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    c = _reload(
        monkeypatch,
        RFQ_CACHE_DIR=None,
        RFQ_WORKSPACE_DIR=str(workspace),
    )
    resolved = c._cache_dir()
    assert resolved.is_dir()
    # Must be under the workspace, not the skill folder
    assert workspace in resolved.parents or resolved == workspace / ".rfq-cache"


def test_does_not_default_to_read_only_skill_folder(monkeypatch, tmp_path):
    """The original bug: cache.py crashed on a read-only skill folder."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    c = _reload(
        monkeypatch,
        RFQ_CACHE_DIR=None,
        RFQ_WORKSPACE_DIR=str(workspace),
    )
    # Just don't raise — the read-only-skill-folder path must not be used.
    path = c._cache_dir()
    assert path.is_dir()


def test_put_then_get_roundtrip(monkeypatch, tmp_path):
    c = _reload(monkeypatch, RFQ_CACHE_DIR=str(tmp_path / "rt"), RFQ_WORKSPACE_DIR=None)
    c.put(
        "TEST-MPN-001",
        fields={"size": "1.6TB"},
        field_confidence={"size": 0.92},
        source="brokerbin",
    )
    got = c.get("TEST-MPN-001")
    assert got is not None
    assert got["fields"]["size"] == "1.6TB"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_cache.py -v`
Expected: most tests fail because `_cache_dir()` currently uses `skill_root / ".cache"` and the docstring's `$HOME/.cache` fallback isn't implemented.

- [ ] **Step 3: Rewrite the cache-directory resolution**

In `rfq-normalizer/skills/rfq-normalizer/scripts/cache.py`, replace the docstring header block (lines 8-12):

```python
"""Persistent MPN enrichment cache.

Stores enrichment results keyed by uppercased MPN. Shared across all RFQs
imported by the team — a cache hit returns instantly with no API call,
preserving the BrokerBin quota.

Cache location (in priority order):
  1. $RFQ_CACHE_DIR env var (explicit override)
  2. <workspace_dir>/.rfq-cache/  (workspace.workspace_dir())
  3. $HOME/.cache/rfq-normalizer/  (last-resort fallback)

The skill folder is NEVER used — it's read-only in Cowork.

TTLs:
  - successful enrichment: CACHE_TTL_DAYS (default 60d — specs are stable)
  - "no listings" miss:    CACHE_MISS_TTL_DAYS (default 7d — vendor may list later)
  - errors:                not cached (assumed transient)

The cache is a single JSON file. For 10k MPNs that's ~5MB on disk — fine.
If it ever grows past that, swap for SQLite.
"""
```

And replace `_cache_dir` (lines 34-42):

```python
def _cache_dir() -> Path:
    explicit = os.environ.get("RFQ_CACHE_DIR")
    if explicit:
        p = Path(explicit)
    else:
        try:
            from workspace import workspace_dir
            p = workspace_dir() / ".rfq-cache"
        except Exception:
            p = Path.home() / ".cache" / "rfq-normalizer"
    p.mkdir(parents=True, exist_ok=True)
    return p
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_cache.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/cache.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py
git commit -m "$(cat <<'EOF'
fix: route cache to workspace dir, never the read-only skill folder

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Credentials file source

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/credentials.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_credentials.py`

- [ ] **Step 1: Write the failing tests**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_credentials.py`:

```python
import importlib
import os
import stat
from pathlib import Path

import credentials


def _reload(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    importlib.reload(credentials)
    return credentials


def test_env_var_still_wins_over_file(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text("BROKERBIN_API_KEY=from-file\n")
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY="from-env",
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    assert c.get("brokerbin_api_key") == "from-env"


def test_file_source_resolves_when_no_env(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text("BROKERBIN_API_KEY=stored-in-file\n")
    creds_file.chmod(0o600)
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY=None,
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    assert c.get("brokerbin_api_key") == "stored-in-file"


def test_set_writes_chmod_600_file(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY=None,
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    c.set_("brokerbin_api_key", "sk-test")
    assert creds_file.exists()
    mode = stat.S_IMODE(creds_file.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"
    assert "BROKERBIN_API_KEY=sk-test" in creds_file.read_text()


def test_status_reports_file_source(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text("BROKERBIN_API_KEY=x\n")
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY=None,
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    s = c.status()
    assert s["brokerbin_api_key"]["set"] is True
    assert s["brokerbin_api_key"]["source"] == "file"


def test_delete_removes_from_file(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text("BROKERBIN_API_KEY=x\nBRAVE_SEARCH_API_KEY=y\n")
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY=None,
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    c.delete("brokerbin_api_key")
    text = creds_file.read_text()
    assert "BROKERBIN_API_KEY" not in text
    assert "BRAVE_SEARCH_API_KEY=y" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_credentials.py -v`
Expected: failures — `source` is `"keyring"` not `"file"`, `set_` writes to keyring not a file, etc.

- [ ] **Step 3: Rewrite credentials.py to add file source**

Replace the contents of `rfq-normalizer/skills/rfq-normalizer/scripts/credentials.py` with:

```python
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
import re
import stat
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
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    path.chmod(0o600)


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_credentials.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Smoke-test on a local Mac with keyring** (regression check)

Run: `python rfq-normalizer/skills/rfq-normalizer/scripts/credentials.py status`
Expected: JSON output, no exceptions. (This is the spec's Phase 1 acceptance criterion #4.)

- [ ] **Step 6: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/credentials.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_credentials.py
git commit -m "$(cat <<'EOF'
feat: add workspace-file credential source for Cowork persistence

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `check_setup.py` reports the file source

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/check_setup.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_check_setup.py`

- [ ] **Step 1: Write the failing test**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_check_setup.py`:

```python
import io
import importlib
import sys
from contextlib import redirect_stdout

import check_setup
import credentials


def test_renders_file_source(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text(
        "BROKERBIN_API_KEY=x\nBROKERBIN_LOGIN=y\nBRAVE_SEARCH_API_KEY=z\n"
    )
    monkeypatch.setenv("RFQ_CREDS_FILE", str(creds_file))
    monkeypatch.delenv("BROKERBIN_API_KEY", raising=False)
    monkeypatch.delenv("BROKERBIN_LOGIN", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    importlib.reload(credentials)
    importlib.reload(check_setup)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_setup.main()
    output = buf.getvalue()
    assert "file" in output
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_check_setup.py -v`
Expected: FAIL — current `check_setup.py` only renders the source string verbatim, but ensure the test asserts the substring `file` is present (the literal source label).

- [ ] **Step 3: Update check_setup.py to render the new `file` source label**

The existing code at `rfq-normalizer/skills/rfq-normalizer/scripts/check_setup.py:32` already does `info["source"] or "not configured"` — that will render `"file"` correctly without code changes. The only real edit is the comment block. Replace the module docstring (lines 1-10):

```python
#!/usr/bin/env python3
"""Report credential and enrichment-tier configuration for rfq-normalizer.

Run after install — or any time you suspect a tier isn't firing — to see
where each credential is being read from (env / file / keyring) and which
enrichment tiers are ready to run.

Exit code: 0 if all required tiers are configured, 1 otherwise. Useful for
scripted post-install verification.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_check_setup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/check_setup.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_check_setup.py
git commit -m "$(cat <<'EOF'
docs: note 'file' as a valid credential source in check_setup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `/rfq-setup` command writes to workspace file

**Files:**
- Modify: `rfq-normalizer/commands/rfq-setup.md`

- [ ] **Step 1: Replace the body of rfq-setup.md**

Write the following as the new content of `rfq-normalizer/commands/rfq-setup.md`:

```markdown
---
name: rfq-setup
description: Configure credentials for the rfq-normalizer skill (BrokerBin + Brave Search). Run once per workspace.
---

Walk the user through entering credentials for each enrichment tier the
rfq-normalizer skill uses. Store each value via the skill's credential
helper, which writes a chmod-600 file in the persistent workspace folder
so values survive Cowork sandbox resets.

## Steps

0. **Install dependencies.** The skill uses the `keyring` PyPI package as a
   fallback credential store on hosts with a working OS keychain. Run:

   ```bash
   python -m pip install --user -r "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/requirements.txt"
   ```

   If `pip` reports any package is already installed, that's fine — continue.

1. Show current credential status:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" status
   ```

   Output is JSON keyed by credential name with `source` (`env` / `file` /
   `keyring` / `null`) and `set` (bool). Summarize for the user in plain
   language — "BrokerBin API key: not configured", etc.

2. For each unset credential, prompt the user via AskUserQuestion or an
   elicitation form, using these labels and help text verbatim:

   | Credential name | Label | Help text |
   |---|---|---|
   | `brokerbin_api_key` | BrokerBin API key | Contact your BrokerBin account rep to provision (David Lewis: david@brokerbin.com). |
   | `brokerbin_login` | BrokerBin login (username) | Your BrokerBin account username. Some accounts require this in addition to the API key. |
   | `brave_search_api_key` | Brave Search API key | Sign up at https://api.search.brave.com/app/signup (free tier: 2000 queries/month). |

   Skipped prompts save nothing — the tier silently disables rather than failing.

3. Save each entered value:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/credentials.py" set <name> <value>
   ```

   This writes to `<workspace>/.rfq-normalizer.env` (chmod 600). Set
   `RFQ_WORKSPACE_DIR` or `RFQ_CREDS_FILE` first to override the location.

4. Verify:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/check_setup.py"
   ```

   Report the tier status table to the user.

5. Smoke-test any keys that were configured:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/brokerbin_client.py" --test-connection HUS726060ALA640
   python "${CLAUDE_PLUGIN_ROOT}/skills/rfq-normalizer/scripts/brave_client.py" --test-connection "test"
   ```

   Confirm each returns `{"ok": true, "error": null}`.

## Notes for the agent

- **Per-user accounts.** BrokerBin appears to provision per-user. Don't suggest sharing a key.
- **File location.** `python credentials.py backend` shows the active backend (file path or keyring backend name). Useful for diagnosing why a value isn't being read.
- **Plaintext credentials.** The workspace env file is plaintext; that's acceptable for an internal tool but document it and keep the file out of any synced/shared folder.
- **Env-var overrides.** If a user has set the corresponding env var (e.g. `BROKERBIN_API_KEY`) the credentials script will return that and skip the file — useful for dev workflows.
- **Resetting credentials.** `python credentials.py delete <name>` removes the value from both the file and the keyring.
- **Headless / unsupported environments.** If no writable file path is found AND no keyring backend exists, `credentials.py set` raises a clear error pointing to the env-var workaround.
```

- [ ] **Step 2: Commit**

```bash
git add rfq-normalizer/commands/rfq-setup.md
git commit -m "$(cat <<'EOF'
docs: rewrite /rfq-setup for workspace-file credential model

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Parallel & resumable batch enrichment

### Task 7: File-lock the cache for parallel-safe writes

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/cache.py` (add lock, modify `_save_all` and `put`)
- Create test: append to `rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py`

- [ ] **Step 1: Add the failing test**

Append to `rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py`:

```python
def test_concurrent_writers_do_not_drop_entries(monkeypatch, tmp_path):
    """Stress: 8 workers each writing 25 distinct MPNs must produce 200 entries."""
    import multiprocessing as mp

    cache_dir = tmp_path / "concurrent"

    def _writer(prefix, env_path):
        os.environ["RFQ_CACHE_DIR"] = str(env_path)
        import importlib
        import cache as c
        importlib.reload(c)
        for i in range(25):
            c.put(
                f"{prefix}-{i:03d}",
                fields={"size": "1.6TB"},
                field_confidence={"size": 0.9},
                source="brokerbin",
            )

    procs = [
        mp.Process(target=_writer, args=(f"P{i}", cache_dir))
        for i in range(8)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    monkeypatch.setenv("RFQ_CACHE_DIR", str(cache_dir))
    import importlib
    import cache as c
    importlib.reload(c)
    data = c._load_all()
    assert len(data) == 200, f"expected 200 entries, got {len(data)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_cache.py::test_concurrent_writers_do_not_drop_entries -v`
Expected: FAIL — current `put()` reads → writes without a lock, so concurrent writers clobber each other.

- [ ] **Step 3: Add file locking to `_save_all` and `put`**

In `rfq-normalizer/skills/rfq-normalizer/scripts/cache.py`, near the top imports add:

```python
import fcntl
from contextlib import contextmanager
```

Add a lock helper after `_cache_path()`:

```python
@contextmanager
def _cache_lock():
    """Exclusive lock over the cache dir, so concurrent put() calls serialize."""
    lock_path = _cache_dir() / ".lock"
    # touch the lockfile
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
```

Modify `put` to read-modify-write inside the lock so workers don't overwrite each other (replace the body of `put`):

```python
def put(
    mpn: str,
    fields: dict,
    field_confidence: dict,
    source: str,
    is_miss: bool = False,
    extras: dict | None = None,
) -> None:
    """Store enrichment result. Pass is_miss=True for empty/no-listings results.

    `extras` is an optional free-form dict for tier-specific data that doesn't
    fit the flat fields/field_confidence shape — e.g. web_search's
    candidate_real_mpn. Old cache entries without `extras` read as {}.

    Parallel-safe: serialized via an fcntl lock on the cache dir.
    """
    entry = {
        "cached_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "fields": fields,
        "field_confidence": field_confidence,
        "is_miss": is_miss,
    }
    if extras:
        entry["extras"] = extras
    with _cache_lock():
        data = _load_all()
        data[_normalize_key(mpn)] = entry
        _save_all(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_cache.py -v`
Expected: all tests pass, including the new concurrent-writers stress.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/cache.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_cache.py
git commit -m "$(cat <<'EOF'
fix: file-lock cache writes so parallel workers don't clobber entries

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Streaming/resumable batch output (JSONL)

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py` (replace batch loop, lines 685-711)
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`

- [ ] **Step 1: Write the failing test**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
ENRICH = SKILL_ROOT / "scripts" / "enrich_mpn.py"


def _run_batch(tmp_path, mpns, **env):
    inputs = tmp_path / "in.json"
    inputs.write_text(json.dumps([{"mpn": m, "need": []} for m in mpns]))
    out = tmp_path / "out.jsonl"
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs),
        "--results-jsonl", str(out),
        "--no-cache",
    ]
    proc_env = {**os.environ, **env, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    # Force all tiers to be skipped: don't set BROKERBIN_API_KEY / BRAVE_SEARCH_API_KEY
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    subprocess.run(cmd, env=proc_env, check=True, capture_output=True)
    return out


def test_batch_writes_one_jsonl_line_per_mpn(tmp_path):
    out = _run_batch(tmp_path, ["A-1", "B-2", "C-3"])
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 3
    mpns_written = {json.loads(l)["mpn"] for l in lines}
    assert mpns_written == {"A-1", "B-2", "C-3"}


def test_batch_resumes_skipping_completed_mpns(tmp_path):
    out = _run_batch(tmp_path, ["A-1", "B-2"])
    # Append a fake completion for "C-3" so resume should skip it
    out_path = out
    # Second run with an extra MPN — already-completed ones must not duplicate
    inputs2 = tmp_path / "in2.json"
    inputs2.write_text(json.dumps([
        {"mpn": "A-1", "need": []},
        {"mpn": "B-2", "need": []},
        {"mpn": "C-3", "need": []},
    ]))
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs2),
        "--results-jsonl", str(out_path),
        "--no-cache",
    ]
    proc_env = {**os.environ, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    subprocess.run(cmd, env=proc_env, check=True, capture_output=True)
    lines = out_path.read_text().strip().splitlines()
    assert len(lines) == 3, f"expected 3 lines after resume, got {len(lines)}"
    mpns_written = [json.loads(l)["mpn"] for l in lines]
    assert mpns_written.count("A-1") == 1
    assert mpns_written.count("B-2") == 1
    assert mpns_written.count("C-3") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py -v`
Expected: FAIL — `--results-jsonl` argument doesn't exist yet.

- [ ] **Step 3: Add `--results-jsonl` and streaming loop in `enrich_mpn.py`**

In `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`, replace the batch section in `main()` (lines 685-711) with:

```python
    # Batch mode: keep a single process so rate limiters in each tier client persist.
    items = _load_batch(args.batch, default_need)

    if args.results_jsonl:
        out_path = args.results_jsonl
        done_mpns = _read_completed_mpns(out_path)
        items = [it for it in items if it["mpn"] not in done_mpns]
        cache_hits = 0
        results_count = len(done_mpns)
        with open(out_path, "a") as out_f:
            for item in items:
                r = enrich(
                    item["mpn"],
                    item.get("need", default_need),
                    current_values=item.get("current"),
                    use_cache=use_cache,
                    vendor_manufacturer=item.get("vendor_manufacturer"),
                )
                if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
                    cache_hits += 1
                r["mpn"] = item["mpn"]
                out_f.write(json.dumps(r, default=str) + "\n")
                out_f.flush()
                results_count += 1
        json.dump(
            {"count": results_count, "cache_hits": cache_hits,
             "api_calls_saved": cache_hits, "output": out_path,
             "resumed_skipped": len(done_mpns)},
            sys.stdout, default=str, indent=2,
        )
        return 0

    # Legacy single-blob output
    results = []
    cache_hits = 0
    for item in items:
        r = enrich(
            item["mpn"],
            item.get("need", default_need),
            current_values=item.get("current"),
            use_cache=use_cache,
            vendor_manufacturer=item.get("vendor_manufacturer"),
        )
        if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
            cache_hits += 1
        results.append(r)
    json.dump(
        {
            "count": len(results),
            "cache_hits": cache_hits,
            "api_calls_saved": cache_hits,
            "results": results,
        },
        sys.stdout,
        default=str,
        indent=2,
    )
    return 0
```

Add the new argument to the argparse block (just before `args = ap.parse_args()`):

```python
    ap.add_argument(
        "--results-jsonl",
        default=None,
        help="Stream one result per line to this JSONL file (resumable). When set, suppresses the aggregated stdout JSON list.",
    )
```

Add `_read_completed_mpns` as a top-level helper (place it just above `def _load_batch`):

```python
def _read_completed_mpns(path: str) -> set[str]:
    """Return MPNs already present in a JSONL results file.

    Reads each line as JSON and pulls the "mpn" field. Malformed lines are
    skipped silently — they'll be overwritten when their MPN is re-enriched.
    """
    try:
        with open(path) as f:
            done: set[str] = set()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = obj.get("mpn")
                if m:
                    done.add(m)
            return done
    except FileNotFoundError:
        return set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py
git commit -m "$(cat <<'EOF'
feat: streaming/resumable batch enrichment via --results-jsonl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Parallel worker pool (`--parallel N`)

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`
- Append test: `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`

- [ ] **Step 1: Append the failing test**

Append to `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`:

```python
def test_parallel_n_processes_all_mpns_without_duplicates(tmp_path):
    mpns = [f"MPN-{i:03d}" for i in range(20)]
    inputs = tmp_path / "in.json"
    inputs.write_text(json.dumps([{"mpn": m, "need": []} for m in mpns]))
    out = tmp_path / "out.jsonl"
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs),
        "--results-jsonl", str(out),
        "--parallel", "4",
        "--no-cache",
    ]
    proc_env = {**os.environ, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    subprocess.run(cmd, env=proc_env, check=True, capture_output=True)
    lines = out.read_text().strip().splitlines()
    written = [json.loads(l)["mpn"] for l in lines]
    assert sorted(written) == sorted(mpns)
    assert len(written) == len(set(written)), "duplicates emitted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py::test_parallel_n_processes_all_mpns_without_duplicates -v`
Expected: FAIL — `--parallel` not recognized.

- [ ] **Step 3: Add parallel execution**

In `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`, add the argparse option (alongside `--results-jsonl`):

```python
    ap.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Process N MPNs concurrently via a thread pool (safe up to ~10 per session vs Brave). Default 1.",
    )
```

In the JSONL branch, replace the `for item in items:` loop body with this dispatcher (keep the surrounding `if args.results_jsonl:` block, the `done_mpns` filtering, and the summary stdout output):

```python
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        write_lock = threading.Lock()

        def _process(item):
            r = enrich(
                item["mpn"],
                item.get("need", default_need),
                current_values=item.get("current"),
                use_cache=use_cache,
                vendor_manufacturer=item.get("vendor_manufacturer"),
            )
            r["mpn"] = item["mpn"]
            return r

        with open(out_path, "a") as out_f, \
             ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            futures = [pool.submit(_process, it) for it in items]
            for fut in as_completed(futures):
                r = fut.result()
                if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
                    cache_hits += 1
                with write_lock:
                    out_f.write(json.dumps(r, default=str) + "\n")
                    out_f.flush()
                results_count += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py -v`
Expected: all batch tests pass.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py
git commit -m "$(cat <<'EOF'
feat: --parallel N for concurrent batch enrichment

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `--budget-seconds S` for clean partial exits

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`
- Append test: `rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py`

- [ ] **Step 1: Append the failing test**

```python
import time


def test_budget_seconds_returns_cleanly_with_partial_results(tmp_path, monkeypatch):
    # 5 MPNs, but a tight budget — at least some should land before exit, none lost.
    inputs = tmp_path / "in.json"
    inputs.write_text(json.dumps([
        {"mpn": f"X-{i}", "need": []} for i in range(5)
    ]))
    out = tmp_path / "out.jsonl"
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs),
        "--results-jsonl", str(out),
        "--budget-seconds", "1",
        "--no-cache",
    ]
    proc_env = {**os.environ, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    result = subprocess.run(cmd, env=proc_env, capture_output=True)
    # Process must exit 0 even when budget hit (clean partial)
    assert result.returncode == 0
    if out.exists():
        lines = out.read_text().strip().splitlines()
        # Every line is valid JSON (no torn writes)
        for l in lines:
            json.loads(l)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py::test_budget_seconds_returns_cleanly_with_partial_results -v`
Expected: FAIL — `--budget-seconds` doesn't exist.

- [ ] **Step 3: Add the budget flag**

In the argparse block of `enrich_mpn.py`:

```python
    ap.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help="Soft wall-time budget. When exceeded, stop submitting work and exit cleanly with whatever has streamed.",
    )
```

Just before the `with open(out_path, "a") as out_f, ...` block, add:

```python
        import time as _time
        deadline = (_time.monotonic() + args.budget_seconds) if args.budget_seconds else None
```

Modify the dispatch loop body to check the deadline before submitting and to skip-on-deadline:

```python
        with open(out_path, "a") as out_f, \
             ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            futures = []
            for it in items:
                if deadline is not None and _time.monotonic() >= deadline:
                    break
                futures.append(pool.submit(_process, it))
            for fut in as_completed(futures):
                if deadline is not None and _time.monotonic() >= deadline:
                    # Stop draining — let in-flight tasks finish naturally on pool exit
                    break
                r = fut.result()
                if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
                    cache_hits += 1
                with write_lock:
                    out_f.write(json.dumps(r, default=str) + "\n")
                    out_f.flush()
                results_count += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_enrich_batch.py -v`
Expected: all batch tests pass.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_enrich_batch.py
git commit -m "$(cat <<'EOF'
feat: --budget-seconds for clean partial exits under execution-window caps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Consolidation + Size parsing

### Task 11: GB/MB decimal regex + size rounding

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py` (line 21)
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py`

- [ ] **Step 1: Write the failing tests**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py`:

```python
from split_description import extract_size


def test_decimal_gb_rounds_to_marketing_size():
    assert extract_size("Drive 120.03 GB SATA SSD") == "120GB"


def test_decimal_gb_near_480():
    assert extract_size("Capacity 480.1 GB") == "480GB"


def test_integer_gb_unchanged():
    assert extract_size("256 GB drive") == "256GB"


def test_decimal_tb_kept_as_is():
    assert extract_size("1.6 TB SATA SSD") == "1.6TB"


def test_integer_tb_strips_zero():
    assert extract_size("14.0 TB HDD") == "14TB"


def test_no_size_returns_none():
    assert extract_size("Generic widget") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_split_description.py -v`
Expected: FAIL on the first two ("120.03 GB" parses to "3GB").

- [ ] **Step 3: Fix the GB/MB regex and add rounding**

In `rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py`, replace the SIZE_PATTERNS block (lines 19-23):

```python
SIZE_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*TB\b", re.I), "TB"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.I), "GB"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*MB\b", re.I), "MB"),
]
```

Replace `extract_size` (lines 59-74):

```python
def extract_size(desc: str) -> str | None:
    for pattern, unit in SIZE_PATTERNS:
        m = pattern.search(desc)
        if not m:
            continue
        val = float(m.group(1))
        # Sanity bounds
        if unit == "TB" and (val < 0.001 or val > 1000):
            continue
        if unit == "GB" and (val < 1 or val > 1_000_000):
            continue
        if unit == "MB" and (val < 1 or val > 10_000_000):
            continue
        # Round to marketing sizes — vendors quote raw byte-derived capacities
        # like 120.03 GB (= 128.04 GB binary) or 480.1 GB. Snap to nearest int
        # for GB/MB; keep decimals for TB only.
        if unit == "TB":
            if val == int(val):
                return f"{int(val)}TB"
            return f"{val}TB"
        return f"{int(round(val))}{unit}"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_split_description.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py
git commit -m "$(cat <<'EOF'
fix: parse decimal GB/MB sizes and round to marketing capacity

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Multi-column spec mining

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py` (add `split_row`)
- Append test: `rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py`

- [ ] **Step 1: Append the failing tests**

```python
from split_description import split_row


def test_split_row_merges_across_text_columns():
    row = {
        "MPN": "ST12000NM006J",
        "Description": "Seagate Exos",
        "Size": "12TB 7.2K SAS-12GBPS",
    }
    result = split_row(row, text_columns=["Description", "Size"])
    assert result["size"] == "12TB"
    assert result["interface"] == "SAS"


def test_split_row_uses_description_only_when_others_unspecified():
    row = {"Description": "1.6TB SATA SSD 2.5\""}
    result = split_row(row, text_columns=["Description"])
    assert result["size"] == "1.6TB"
    assert result["interface"] == "SATA"
    assert result["drive_type"] == "SSD"
    assert result["form_factor"] == "2.5in"


def test_split_row_skips_missing_columns():
    row = {"Description": "480GB SSD"}
    result = split_row(row, text_columns=["Description", "Size", "Notes"])
    assert result["size"] == "480GB"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_split_description.py -v`
Expected: FAIL — `split_row` doesn't exist.

- [ ] **Step 3: Add `split_row` to split_description.py**

Append to `rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py` (just after `def split(...)`):

```python
def split_row(row: dict, text_columns: list[str]) -> dict:
    """Run spec extraction across multiple text columns of a single row.

    Vendors hide spec hints in Size, Notes, and Description columns. Running
    the regex over a concatenated text blob catches all of them in one pass
    while preserving the existing single-column `split()` behavior used in
    BrokerBin/Brave consensus scoring.
    """
    parts = [str(row[c]) for c in text_columns if c in row and row[c]]
    blob = " | ".join(parts)
    return split(blob)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_split_description.py -v`
Expected: all tests pass.

- [ ] **Step 5: Update SKILL.md step 4 to use `split_row` over all text columns**

In `rfq-normalizer/skills/rfq-normalizer/SKILL.md`, update step "### 4. Split descriptions into spec columns" — replace the first paragraph:

```markdown
### 4. Split descriptions into spec columns

Run `scripts/split_description.py` over each row, mining **all text columns** (the vendor's `Description`, `Size`, `Notes`, etc.), not just the primary description. Vendors frequently hide spec hints in the Size column (e.g., "1.2 TB 10K SAS", "7.68TB SSD NVMe"). Use `split_row(row, text_columns=[...])` from the script's API; pass the list of text columns the column-mapping step identified.
```

- [ ] **Step 6: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/split_description.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_split_description.py \
        rfq-normalizer/skills/rfq-normalizer/SKILL.md
git commit -m "$(cat <<'EOF'
feat: split_row mines spec hints across all row text columns

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Historical consolidation key

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/consolidate_duplicates.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_consolidate_historical.py`

- [ ] **Step 1: Write the failing tests**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_consolidate_historical.py`:

```python
from consolidate_duplicates import consolidate


def test_historical_keeps_distinct_bid_events():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3,
         "Bid Price": "95",  "Winning Bid": "120", "Outcome": "lost"},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="historical",
        bid_col="Bid Price",
        win_col="Winning Bid",
        outcome_col="Outcome",
    )
    assert len(result["consolidated"]) == 2, "distinct bid events must NOT merge"


def test_historical_merges_true_duplicates():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="historical",
        bid_col="Bid Price",
        win_col="Winning Bid",
        outcome_col="Outcome",
    )
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 8


def test_live_mode_keeps_old_mpn_only_key():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="live",
    )
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 8


def test_total_quantity_conserved():
    rows = [
        {"MPN": "A", "Quantity": 5, "Bid Price": "10", "Winning Bid": "12", "Outcome": "won"},
        {"MPN": "A", "Quantity": 3, "Bid Price": "10", "Winning Bid": "12", "Outcome": "won"},
        {"MPN": "B", "Quantity": 1, "Bid Price": "20", "Winning Bid": "25", "Outcome": "lost"},
    ]
    result = consolidate(
        rows, mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    assert result["qty_in"] == 9
    assert result["qty_out"] == 9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_consolidate_historical.py -v`
Expected: FAIL — `rfq_mode`, `bid_col`, etc. not recognized as kwargs.

- [ ] **Step 3: Extend `consolidate()` to accept historical mode**

In `rfq-normalizer/skills/rfq-normalizer/scripts/consolidate_duplicates.py`, replace the entire `consolidate` function (lines 52-101):

```python
def consolidate(
    rows: list[dict],
    mpn_col: str,
    qty_col: str | None,
    condition_col: str | None,
    mode: str = "sum",
    rfq_mode: str = "live",
    bid_col: str | None = None,
    win_col: str | None = None,
    outcome_col: str | None = None,
) -> dict:
    if mode not in ("sum", "count"):
        raise ValueError(f"mode must be 'sum' or 'count', got {mode!r}")
    if rfq_mode not in ("live", "historical"):
        raise ValueError(f"rfq_mode must be 'live' or 'historical', got {rfq_mode!r}")

    output_qty_col = qty_col if mode == "sum" else COUNT_COLUMN

    def _key_for(row: dict) -> tuple:
        mpn = (row.get(mpn_col) or "").strip() if isinstance(row.get(mpn_col), str) else row.get(mpn_col)
        condition = row.get(condition_col) if condition_col else None
        base = (str(mpn), str(condition) if condition is not None else None)
        if rfq_mode != "historical":
            return base
        # Historical: pricing events with different bids/outcomes are distinct
        bid = str(row.get(bid_col)) if bid_col and row.get(bid_col) is not None else None
        win = str(row.get(win_col)) if win_col and row.get(win_col) is not None else None
        outcome = str(row.get(outcome_col)) if outcome_col and row.get(outcome_col) is not None else None
        return base + (bid, win, outcome)

    groups: dict[tuple, dict] = defaultdict(lambda: {"qty": 0, "_sample": None})
    qty_in = 0

    for row in rows:
        mpn = (row.get(mpn_col) or "").strip() if isinstance(row.get(mpn_col), str) else row.get(mpn_col)
        if mpn is None or mpn == "":
            continue
        key = _key_for(row)

        if mode == "count":
            increment = 1
        else:
            try:
                increment = int(float(row.get(qty_col) or 1))
            except (TypeError, ValueError):
                increment = 1

        qty_in += increment
        groups[key]["qty"] += increment
        if groups[key]["_sample"] is None:
            groups[key]["_sample"] = row

    consolidated = []
    qty_out = 0
    for key, data in groups.items():
        merged = dict(data["_sample"])
        merged[mpn_col] = key[0]
        merged[output_qty_col] = data["qty"]
        if condition_col and key[1] is not None:
            merged[condition_col] = key[1]
        consolidated.append(merged)
        qty_out += data["qty"]

    all_mpns = [str(r.get(mpn_col, "")).strip() for r in rows if r.get(mpn_col)]
    ambiguous = find_ambiguous_pairs(all_mpns)

    if qty_in != qty_out:
        raise AssertionError(
            f"quantity not conserved: in={qty_in} out={qty_out} (mode={mode}, rfq_mode={rfq_mode})"
        )

    return {
        "consolidated": consolidated,
        "ambiguous_pairs": ambiguous,
        "mode": mode,
        "rfq_mode": rfq_mode,
        "qty_column": output_qty_col,
        "qty_in": qty_in,
        "qty_out": qty_out,
    }
```

Then extend `main()` to accept the new fields from stdin (replace `main` lines 104-119):

```python
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None, help="JSON file (default: stdin)")
    args = ap.parse_args()

    raw = json.load(open(args.input) if args.input else sys.stdin)
    rows = raw["rows"]
    mpn_col = raw.get("mpn_col", "MPN")
    qty_col = raw.get("qty_col", "Quantity")
    condition_col = raw.get("condition_col")
    mode = raw.get("mode", "sum")
    rfq_mode = raw.get("rfq_mode", "live")
    bid_col = raw.get("bid_col")
    win_col = raw.get("win_col")
    outcome_col = raw.get("outcome_col")

    result = consolidate(
        rows, mpn_col, qty_col, condition_col,
        mode=mode, rfq_mode=rfq_mode,
        bid_col=bid_col, win_col=win_col, outcome_col=outcome_col,
    )
    json.dump(result, sys.stdout, default=str, indent=2)
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_consolidate_historical.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Update SKILL.md step 3 to wire the new mode**

In `rfq-normalizer/skills/rfq-normalizer/SKILL.md`, replace the "### 3. Consolidate duplicate rows" body with:

```markdown
### 3. Consolidate duplicate rows

Run `scripts/consolidate_duplicates.py` with the `mode` and `rfq_mode` detected by `analyze_columns`:

- `mode='sum'` (default) — each row already has a Quantity column; sum the values
- `mode='count'` — each row is one physical item; count rows per MPN

And, critically, pass `rfq_mode`:

- `rfq_mode='live'` — group by (MPN, condition) only. For sourcing lists.
- `rfq_mode='historical'` — group by (MPN, condition, bid_price, winning_bid, outcome). **Never merges distinct bid events** — preserves pricing history.

`analyze_columns.py` already emits `suggested_rfq_mode` and the relevant column names (`bid_price_column`, `outcome_column`); pass them through.

Returns:
- `consolidated[]` — one row per unique key
- `ambiguous_pairs[]` — MPNs differing only by case/whitespace
- `qty_in`, `qty_out` — total quantity in vs out (must match — script raises if not)

For every ambiguous pair, ask the user: "These look like the same part — should I merge them?" Show both raw strings. Never auto-merge.
```

- [ ] **Step 6: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/consolidate_duplicates.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_consolidate_historical.py \
        rfq-normalizer/skills/rfq-normalizer/SKILL.md
git commit -m "$(cat <<'EOF'
fix: historical consolidation keys on bid + win + outcome so pricing isn't lost

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Policy, MPN scoring, settings form

### Task 14: MPN prefix DB expansion + brand-prefix stripping

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/mpn_patterns.py`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_mpn_patterns.py`

- [ ] **Step 1: Write the failing tests**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_mpn_patterns.py`:

```python
from mpn_patterns import score_mpn, strip_brand_prefix


def test_intel_ssd_recognized():
    s = score_mpn("SSDSC2BB012T6")
    assert s.has_known_prefix


def test_micron_ssd_recognized():
    s = score_mpn("MTFDDAK480TDS")
    assert s.has_known_prefix


def test_toshiba_kioxia_kpm():
    s = score_mpn("KPM5XRUG960G")
    assert s.has_known_prefix


def test_toshiba_kioxia_kxg():
    s = score_mpn("KXG60ZNV512G")
    assert s.has_known_prefix


def test_hgst_oem_prefix():
    s = score_mpn("0F22811")
    assert s.has_known_prefix


def test_sandisk_sdfam():
    s = score_mpn("SDFAB-960G-XXX")
    assert s.has_known_prefix


def test_strip_intel_prefix():
    cleaned, original = strip_brand_prefix("INTEL SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert original == "INTEL SSDSC2BB012T6"


def test_strip_toshiba_prefix():
    cleaned, original = strip_brand_prefix("TOSHIBA AL15SEB060N")
    assert cleaned == "AL15SEB060N"


def test_strip_hgst_prefix():
    cleaned, original = strip_brand_prefix("HGST HUS726T6TALE6L4")
    assert cleaned == "HUS726T6TALE6L4"


def test_no_strip_when_no_prefix():
    cleaned, original = strip_brand_prefix("SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert original == "SSDSC2BB012T6"


def test_no_strip_for_unknown_prefix():
    # Vendor brand prefixes outside the allowlist must NOT be stripped.
    cleaned, original = strip_brand_prefix("ACME WIDGET-42")
    assert cleaned == "ACME WIDGET-42"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_mpn_patterns.py -v`
Expected: failures on the new prefix recognitions and `strip_brand_prefix` doesn't exist.

- [ ] **Step 3: Extend `mpn_patterns.py`**

In `rfq-normalizer/skills/rfq-normalizer/scripts/mpn_patterns.py`, replace the PATTERNS list (lines 25-61) by adding the new entries before the generic catch-all (keep all existing patterns; add these in the appropriate section):

In the storage SSDs section, replace lines 39-42 with:

```python
    # ── Storage: SSDs ───────────────────────────────────────────────────────
    (re.compile(r"^MZ[0-9A-Z].*", re.I),        "Samsung",          "Samsung enterprise SSD (PM/SM series)"),
    (re.compile(r"^SSDPE[A-Z].*", re.I),        "Intel",            "Intel/Solidigm DC SSD (SSDPE series)"),
    (re.compile(r"^SSDS[A-Z][0-9].*", re.I),    "Intel",            "Intel client/server SSD (SSDSC/SSDSA)"),
    (re.compile(r"^MTFDD[A-Z].*", re.I),        "Micron",           "Micron client/enterprise SSD"),
    (re.compile(r"^MTFDH[A-Z].*", re.I),        "Micron",           "Micron mainstream SSD"),
    (re.compile(r"^THNSF[0-9A-Z].*", re.I),     "Toshiba",          "Toshiba/Kioxia client SSD"),
    (re.compile(r"^KPM[0-9A-Z].*", re.I),       "Kioxia",           "Kioxia datacenter SAS SSD (KPM5/KPM6)"),
    (re.compile(r"^KXG[0-9A-Z].*", re.I),       "Kioxia",           "Kioxia datacenter NVMe SSD"),
    (re.compile(r"^SDFA[A-Z]?[0-9-].*|^SDLF[A-Z]?[0-9-].*", re.I),
                                                "SanDisk",          "SanDisk/WD enterprise SSD"),
    (re.compile(r"^0F[0-9]{4,}.*", re.I),       "HGST",             "HGST OEM part numbers (0F22811 etc.)"),
```

Also in the storage drives section, ensure HGST `AL15` is matched — it already is via `^AL[0-9]{2}.*` (line 37) but verify after edits.

Now add the brand-prefix stripper. Append to the module:

```python
# Brand-prefix stripping — vendors sometimes prepend the manufacturer name to
# the MPN ("INTEL SSDSC2BB012T6"). When that happens, the part after the
# prefix should be the real MPN. We only strip prefixes we have high
# confidence in.
_BRAND_PREFIX_RE = re.compile(
    r"^(INTEL|TOSHIBA|HGST|WDC|SAMSUNG|MICRON|KIOXIA|SANDISK|SEAGATE)\s+([A-Z0-9][A-Z0-9\-]{3,})$",
    re.I,
)


def strip_brand_prefix(mpn: str) -> tuple[str, str]:
    """Strip a well-known brand prefix from an MPN.

    Returns (cleaned_mpn, original_string). When no known prefix is present,
    cleaned == original. The caller should preserve `original` somewhere
    (description column, provenance) so the swap is auditable.
    """
    if not isinstance(mpn, str):
        return mpn, mpn
    m = _BRAND_PREFIX_RE.match(mpn.strip())
    if not m:
        return mpn, mpn
    return m.group(2), mpn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_mpn_patterns.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/mpn_patterns.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_mpn_patterns.py
git commit -m "$(cat <<'EOF'
feat: expand MPN prefix DB; add brand-prefix stripping

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: `candidate_real_mpn` validation

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py` (around lines 346-368, `tier_web_search`)
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_candidate_validation.py`

- [ ] **Step 1: Write the failing tests**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_candidate_validation.py`:

```python
from enrich_mpn import _is_valid_candidate_mpn


def test_rejects_interface_token():
    # "SAS-12GBPS" is an interface spec, not a part number.
    assert _is_valid_candidate_mpn("SAS-12GBPS") is False


def test_rejects_product_family_name():
    # "D3-S4610" is an Intel SSD product family, not a real MPN.
    assert _is_valid_candidate_mpn("D3-S4610") is False


def test_rejects_short_token():
    assert _is_valid_candidate_mpn("ABC123") is False  # < 8 chars


def test_rejects_all_digits():
    assert _is_valid_candidate_mpn("12345678") is False


def test_accepts_plausible_mpn():
    assert _is_valid_candidate_mpn("MZILS3T8HMLH") is True


def test_accepts_dash_separated_mpn():
    assert _is_valid_candidate_mpn("HUS726T6TALE6L4") is True


def test_rejects_common_word():
    assert _is_valid_candidate_mpn("SPECIFICATIONS") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_candidate_validation.py -v`
Expected: FAIL — `_is_valid_candidate_mpn` doesn't exist.

- [ ] **Step 3: Add validation in enrich_mpn.py**

In `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`, just above `def tier_web_search`, add:

```python
# Tokens that look MPN-shaped but are actually interface specs, product
# family names, or common words. Reject them as candidate_real_mpn matches.
_CANDIDATE_REJECT_PATTERNS = (
    re.compile(r"^SAS-\d+", re.I),
    re.compile(r"^SATA-?\d*", re.I),
    re.compile(r"^NVME?", re.I),
    re.compile(r"^PCIE?", re.I),
    re.compile(r"^\d+\s*GBPS", re.I),
    re.compile(r"^\d+\s*GBE", re.I),
    # Intel SSD family names ("D3-S4610", "DC-P4510") look MPN-shaped.
    re.compile(r"^D[0-9]-S[0-9]+$", re.I),
    re.compile(r"^DC-P[0-9]+$", re.I),
)

_CANDIDATE_REJECT_WORDS = {
    "SPECIFICATIONS", "DATASHEET", "DOWNLOAD", "MANUFACTURER",
    "ENTERPRISE", "PERFORMANCE", "COMPATIBLE",
}


def _is_valid_candidate_mpn(token: str) -> bool:
    """Validate a candidate_real_mpn token from web search results.

    Filters out interface specs (SAS-12GBPS), product family names (D3-S4610),
    and common English words that happen to be ≥8 chars and ALL CAPS.
    """
    if not token or len(token) < 8:
        return False
    upper = token.upper()
    # Must contain at least one digit AND one letter
    if not any(c.isdigit() for c in upper) or not any(c.isalpha() for c in upper):
        return False
    if upper in _CANDIDATE_REJECT_WORDS:
        return False
    for pattern in _CANDIDATE_REJECT_PATTERNS:
        if pattern.match(upper):
            return False
    return True
```

Then update the candidate-selection block inside `tier_web_search` (the lines that currently set `candidate_real_mpn = top_token` around line 366):

```python
    candidate_real_mpn: str | None = None
    if token_counts:
        # Walk the ranking until we find a token that passes validation.
        for top_token, top_count in token_counts.most_common():
            if top_count < 3:
                break
            if _is_valid_candidate_mpn(top_token):
                candidate_real_mpn = top_token
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_candidate_validation.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py \
        rfq-normalizer/skills/rfq-normalizer/tests/test_candidate_validation.py
git commit -m "$(cat <<'EOF'
fix: validate candidate_real_mpn against interface tokens and family names

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Reconcile the confidence policy

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py` (CONFIDENCE_AUTO_ACCEPT block at line 37 + WEB_FIELD_FILL_FLOOR at line 74)
- Modify: `rfq-normalizer/skills/rfq-normalizer/SKILL.md` (lines 98, 117)

- [ ] **Step 1: Update the policy constants in enrich_mpn.py**

In `rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py`, replace lines 37 and the comment block around 64-74:

```python
# Per-field policy:
#   * MEDIUM_FLOOR (0.60) — auto-fill optional spec fields (interface,
#     drive_type, form_factor, size). Tag with `tagged_low_confidence` when
#     below CONFIDENCE_AUTO_ACCEPT. Web search caps at 0.85 so this floor is
#     what actually applies in practice.
#   * CONFIDENCE_AUTO_ACCEPT (0.90) — clean auto-fill, no tag.
#   * Required fields and MPN swaps — ALWAYS confirm; never auto-apply.
CONFIDENCE_AUTO_ACCEPT = 0.90
MEDIUM_FLOOR = 0.60

# Description-specific floor: we fill descriptions even when confidence is
# below auto-accept, because a low-consensus seller-authored description is
# still more useful than a blank cell. Annotated with a confidence tag so
# the operator knows to verify.
DESCRIPTION_FILL_FLOOR = 0.50

# Web-tier floor — alias of MEDIUM_FLOOR for backward compatibility with
# existing call sites. Both name the same threshold.
WEB_FIELD_FILL_FLOOR = MEDIUM_FLOOR
```

- [ ] **Step 2: Update SKILL.md**

In `rfq-normalizer/skills/rfq-normalizer/SKILL.md`, replace line 98 (`Stop as soon as a tier fills the gaps with high confidence (≥0.90).`) with:

```markdown
Stop as soon as a tier fills the gaps. Per-field policy:

- **Optional spec fields** (size, interface, drive_type, form_factor): fill at confidence ≥ 0.60. Below 0.90, the cell is tagged `tagged_low_confidence` in provenance and gets an `[unverified — {source} consensus N%]` note inline. No per-cell prompting — the operator audits via the provenance log.
- **Required fields** (MPN, Quantity, Condition) and **MPN swaps**: never auto-fill or auto-apply. Always confirm with the operator.

The run summary reports the confidence mix (e.g., "133 medium, 8 low, 0 blocked") rather than blocking the pipeline.
```

And replace line 117 (`**Critical:** if confidence < 0.9 for any field, do NOT auto-fill. Surface to user with: "I found X via Y with Z% confidence — accept?"`) with:

```markdown
**Critical:** for required fields, ALWAYS surface to user with: "I found X via Y with Z% confidence — accept?" For optional spec fields, see the per-field policy above; auto-fill at ≥ 0.60 with provenance tagging.
```

- [ ] **Step 3: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/scripts/enrich_mpn.py \
        rfq-normalizer/skills/rfq-normalizer/SKILL.md
git commit -m "$(cat <<'EOF'
docs: reconcile confidence policy with how tiers actually score

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: One settings form in SKILL.md

**Files:**
- Modify: `rfq-normalizer/skills/rfq-normalizer/SKILL.md`

- [ ] **Step 1: Replace the post-analyze section of SKILL.md**

Edit `rfq-normalizer/skills/rfq-normalizer/SKILL.md`. Just after the existing step "### 1b. Analyze the sheet structure" insert a new step "### 1c. Settings form" before "### 2. Map vendor columns to MTGI fields":

```markdown
### 1c. Settings form

After analyze surfaces its warnings, ask the operator a **single** settings card (one elicitation, not four separate prompts) covering:

| Setting | Default | Where the default comes from |
|---|---|---|
| Default Condition for the file | `used_good` | Detected from a `Grade` column; ask explicitly if no grade is present. |
| Outcome Date source | `filename` if a date is parseable from the input filename, else `ask`. | Parse `YYYY-MM-DD` or `M-D-YYYY` patterns from the input filename. |
| Consolidation policy | `historical` if `analyze_columns` returned `suggested_rfq_mode='historical'`, else `live`. | step 1b output. |
| Enrichment scope | `full` | `free-only` (regex + cache only), `top-N` (cap API calls), or `full` (run all configured tiers). |

Present all four with sensible defaults pre-filled. After this single interaction, only ambiguous-merge prompts (step 3) and confirmations (vendor-SKU swaps in step 5) should require operator input.
```

Also remove the now-redundant "Confirm with the user that this matches what they expected before proceeding" line from step 1 and the column-mapping confirmation from step 2 — both are subsumed into the settings card or deferred to the per-step confirmations that genuinely need operator judgment.

- [ ] **Step 2: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/SKILL.md
git commit -m "$(cat <<'EOF'
docs: single settings form after analyze (replaces 4 sequential prompts)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final task — Regression fixture + version bump

### Task 18: AGIS sanitized regression fixture + version bump

**Files:**
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/fixtures/agis-sample.json`
- Create: `rfq-normalizer/skills/rfq-normalizer/tests/test_agis_regression.py`
- Modify: `rfq-normalizer/.claude-plugin/plugin.json` (version 0.4.0 → 0.5.0)

- [ ] **Step 1: Create the sanitized fixture**

Write `rfq-normalizer/skills/rfq-normalizer/tests/fixtures/agis-sample.json`:

```json
{
  "headers": ["MPN", "Description", "Size", "Grade", "Quantity", "Bid Price", "Winning Bid", "Outcome"],
  "rows": [
    {"MPN": "INTEL SSDSC2BB012T6", "Description": "Intel DC S3500 1.2TB SATA SSD", "Size": "1.2 TB SATA", "Grade": "B", "Quantity": 5, "Bid Price": "85", "Winning Bid": "92", "Outcome": "won"},
    {"MPN": "INTEL SSDSC2BB012T6", "Description": "Intel DC S3500 1.2TB SATA SSD", "Size": "1.2 TB SATA", "Grade": "B", "Quantity": 3, "Bid Price": "85", "Winning Bid": "92", "Outcome": "won"},
    {"MPN": "ST12000NM006J",       "Description": "Seagate Exos 12TB SAS",       "Size": "12TB SAS-12GBPS", "Grade": "B", "Quantity": 4, "Bid Price": "120", "Winning Bid": "135", "Outcome": "won"},
    {"MPN": "HUS726T6TALE6L4",     "Description": "WD/HGST 6TB SATA Enterprise","Size": "6 TB SATA", "Grade": "B", "Quantity": 10, "Bid Price": "55", "Winning Bid": "62", "Outcome": "lost"},
    {"MPN": "HUS726T6TALE6L4",     "Description": "WD/HGST 6TB SATA Enterprise","Size": "6 TB SATA", "Grade": "B", "Quantity": 2, "Bid Price": "58", "Winning Bid": "62", "Outcome": "lost"},
    {"MPN": "303-276-000B-02",     "Description": "Vendor-internal SKU",        "Size": "480.1 GB SSD", "Grade": "B", "Quantity": 1, "Bid Price": "30", "Winning Bid": "35", "Outcome": "won"},
    {"MPN": "303-276-000b-02",     "Description": "Vendor-internal SKU",        "Size": "480.1 GB SSD", "Grade": "B", "Quantity": 1, "Bid Price": "30", "Winning Bid": "35", "Outcome": "won"}
  ]
}
```

- [ ] **Step 2: Write end-to-end regression test**

Write `rfq-normalizer/skills/rfq-normalizer/tests/test_agis_regression.py`:

```python
"""End-to-end regression covering the issues seen in the AGIS session:
- decimal GB sizes (480.1 GB → 480GB)
- Size column mining (SAS interface from Size, not Description)
- historical consolidation keeps distinct bid events
- brand-prefix stripping (INTEL SSDSC2BB012T6 → SSDSC2BB012T6)
- case-collision ambiguity detection (303-...B-02 vs 303-...b-02)
- quantity conservation
"""
import json
from pathlib import Path

from consolidate_duplicates import consolidate
from mpn_patterns import strip_brand_prefix
from split_description import split_row

FIXTURE = Path(__file__).parent / "fixtures" / "agis-sample.json"


def _load_fixture():
    return json.loads(FIXTURE.read_text())


def test_decimal_size_normalized():
    data = _load_fixture()
    sku_row = next(r for r in data["rows"] if r["MPN"].startswith("303-276-000B"))
    out = split_row(sku_row, text_columns=["Description", "Size"])
    assert out["size"] == "480GB"


def test_size_column_mining_recovers_sas_interface():
    data = _load_fixture()
    exos_row = next(r for r in data["rows"] if r["MPN"] == "ST12000NM006J")
    out = split_row(exos_row, text_columns=["Description", "Size"])
    assert out["interface"] == "SAS"


def test_historical_keeps_distinct_bid_events():
    data = _load_fixture()
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    # HUS726T6TALE6L4 has two rows at different (Bid Price=55) and (Bid Price=58)
    # — must stay 2 rows, not collapse to 1.
    hus_rows = [r for r in result["consolidated"] if r["MPN"] == "HUS726T6TALE6L4"]
    assert len(hus_rows) == 2


def test_brand_prefix_stripped():
    cleaned, original = strip_brand_prefix("INTEL SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert original == "INTEL SSDSC2BB012T6"


def test_case_collision_surfaces_as_ambiguous():
    data = _load_fixture()
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    pairs = result["ambiguous_pairs"]
    assert any(
        "303-276-000B-02" in (p["mpn_a"], p["mpn_b"])
        and "303-276-000b-02" in (p["mpn_a"], p["mpn_b"])
        for p in pairs
    )


def test_quantity_conserved():
    data = _load_fixture()
    expected_in = sum(r["Quantity"] for r in data["rows"])
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    assert result["qty_in"] == expected_in
    assert result["qty_out"] == expected_in
```

- [ ] **Step 3: Run the regression**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/test_agis_regression.py -v`
Expected: `6 passed`.

- [ ] **Step 4: Run the whole suite**

Run: `cd rfq-normalizer/skills/rfq-normalizer && python -m pytest tests/ -v`
Expected: all tests across all files pass.

- [ ] **Step 5: Bump plugin version**

In `rfq-normalizer/.claude-plugin/plugin.json`, change `"version": "0.4.0"` to `"version": "0.5.0"`.

- [ ] **Step 6: Build the .plugin artifact**

Run: `scripts/build-plugin.sh`
Expected output: `Built /…/dist/rfq-normalizer-0.5.0.plugin (~60K)`.

- [ ] **Step 7: Commit**

```bash
git add rfq-normalizer/skills/rfq-normalizer/tests/fixtures/agis-sample.json \
        rfq-normalizer/skills/rfq-normalizer/tests/test_agis_regression.py \
        rfq-normalizer/.claude-plugin/plugin.json
git commit -m "$(cat <<'EOF'
chore: release rfq-normalizer v0.5.0 (Cowork-native + parallel enrichment)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** Change 1 → Tasks 2–6; Change 2 → Tasks 7–10; Change 3 → Task 13; Change 4 → Task 16; Change 5 → Tasks 14, 15; Change 6 → Tasks 11, 12; Change 7 → Task 17. Final integration in Task 18.
- **Open risk (from spec) deferred deliberately:** the question of whether BrokerBin should run *concurrently* with Brave (rather than as a serial fallback) is **not** in this plan — it requires a real BrokerBin smoke test and a category-hint design that's beyond the spec's "surgical fix" framing. Track as a follow-up.
- **Phase 1 acceptance criterion #4** (local-Mac keyring regression) is exercised by manual Step 5 in Task 4 rather than an automated test — the keyring backend is environment-dependent and isn't easily mocked.
- **Workspace auto-detection** uses a hardcoded candidate list (`/mnt/user-data`, `/workspace`). Cowork may use a different mount; `RFQ_WORKSPACE_DIR` is the escape hatch.
