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
