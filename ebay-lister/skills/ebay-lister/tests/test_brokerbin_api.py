import credentials


def test_brokerbin_credentials_are_in_schema():
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["keychain"] == "brokerbin-mtgi-api-token"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_api_token"]["env"] == "BROKERBIN_API_KEY"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["keychain"] == "brokerbin-mtgi-login"
    assert credentials.CREDENTIAL_SCHEMA["brokerbin_login"]["env"] == "BROKERBIN_LOGIN"


def test_brokerbin_env_override(monkeypatch):
    monkeypatch.setenv("BROKERBIN_API_KEY", "env-token")
    assert credentials.get("brokerbin_api_token") == "env-token"
