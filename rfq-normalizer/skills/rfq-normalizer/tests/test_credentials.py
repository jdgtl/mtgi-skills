import importlib
import stat

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


def test_set_preserves_sibling_keys(monkeypatch, tmp_path):
    creds_file = tmp_path / ".rfq-normalizer.env"
    creds_file.write_text(
        "BRAVE_SEARCH_API_KEY=brave-existing\nBROKERBIN_LOGIN=alice\n"
    )
    creds_file.chmod(0o600)
    c = _reload(
        monkeypatch,
        BROKERBIN_API_KEY=None,
        BRAVE_SEARCH_API_KEY=None,
        BROKERBIN_LOGIN=None,
        RFQ_CREDS_FILE=str(creds_file),
        RFQ_WORKSPACE_DIR=None,
    )
    c.set_("brokerbin_api_key", "new-key")
    text = creds_file.read_text()
    assert "BROKERBIN_API_KEY=new-key" in text
    assert "BRAVE_SEARCH_API_KEY=brave-existing" in text
    assert "BROKERBIN_LOGIN=alice" in text
    # mode preserved
    import stat
    mode = stat.S_IMODE(creds_file.stat().st_mode)
    assert mode == 0o600
