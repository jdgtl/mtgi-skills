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
