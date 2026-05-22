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


def test_sessions_mnt_glob_picks_writable_dir(monkeypatch, tmp_path):
    # Simulate /sessions/abc/mnt/proj (writable) and /sessions/abc/mnt/locked (not).
    sessions = tmp_path / "sessions"
    proj = sessions / "abc" / "mnt" / "proj"
    proj.mkdir(parents=True)
    locked = sessions / "abc" / "mnt" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0o500)  # readable but not writable
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", sessions)
    assert workspace.workspace_dir() == proj


def test_sessions_mnt_glob_excludes_outputs_uploads_and_dotdirs(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    proj = sessions / "abc" / "mnt" / "proj"
    proj.mkdir(parents=True)
    for skip in ("outputs", "uploads", ".rfq-cache", ".claude"):
        (sessions / "abc" / "mnt" / skip).mkdir(parents=True)
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", sessions)
    assert workspace.workspace_dir() == proj


def test_sessions_mnt_glob_prefers_dir_with_creds_file(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    plain = sessions / "abc" / "mnt" / "plain"
    plain.mkdir(parents=True)
    preferred = sessions / "abc" / "mnt" / "preferred"
    preferred.mkdir(parents=True)
    (preferred / ".rfq-normalizer.env").write_text("BROKERBIN_API_KEY=x\n")
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", sessions)
    assert workspace.workspace_dir() == preferred


def test_sessions_mnt_glob_prefers_dir_with_cache_dir(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    plain = sessions / "abc" / "mnt" / "plain"
    plain.mkdir(parents=True)
    preferred = sessions / "abc" / "mnt" / "preferred"
    (preferred / ".rfq-cache").mkdir(parents=True)
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", sessions)
    assert workspace.workspace_dir() == preferred


def test_explicit_env_var_wins_over_sessions_glob(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    (sessions / "abc" / "mnt" / "proj").mkdir(parents=True)
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("RFQ_WORKSPACE_DIR", str(explicit))
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", sessions)
    assert workspace.workspace_dir() == explicit


def test_falls_back_to_home_when_no_glob_match(monkeypatch, tmp_path):
    monkeypatch.delenv("RFQ_WORKSPACE_DIR", raising=False)
    # Empty sessions root + empty static candidates
    monkeypatch.setattr(workspace, "_AUTODETECT_CANDIDATES", ())
    monkeypatch.setattr(workspace, "_SESSIONS_GLOB_ROOT", tmp_path / "nonexistent")
    assert workspace.workspace_dir() == Path.home()
