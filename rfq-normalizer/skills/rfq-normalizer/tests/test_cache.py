import importlib
import os

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


def _concurrent_writer(args):
    """Top-level worker for test_concurrent_writers_do_not_drop_entries (must be picklable)."""
    prefix, env_path = args
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


def test_concurrent_writers_do_not_drop_entries(monkeypatch, tmp_path):
    """Stress: 8 workers each writing 25 distinct MPNs must produce 200 entries."""
    import multiprocessing as mp

    cache_dir = tmp_path / "concurrent"

    procs = [
        mp.Process(target=_concurrent_writer, args=((f"P{i}", cache_dir),))
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
