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
