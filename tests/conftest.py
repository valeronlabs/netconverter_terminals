import pytest


@pytest.fixture(autouse=True)
def _no_real_sign_in(request, monkeypatch):
    """Tests never read the developer's real OS sign-in or auth override.

    A test that needs a sign-in patches ``cli._clerk_session`` itself, or uses
    the in-memory ``vault`` credential store (tests/test_clerk.py).
    """
    from netconverter_cli import cli

    monkeypatch.delenv("NETCONVERTER_AUTH", raising=False)
    monkeypatch.delenv("NETCONVERTER_MCP_STRICT", raising=False)
    monkeypatch.delenv("NETCONVERTER_MCP_VIEW", raising=False)
    # The license is accepted for tests unless a test removes this; acceptance
    # records go to a temporary folder, never the developer's real config.
    monkeypatch.setenv("NETCONVERTER_ACCEPT_LICENSE", "1")
    monkeypatch.setenv("NETCONVERTER_CONFIG_HOME",
                       str(request.getfixturevalue("tmp_path_factory").mktemp("nc-config")))
    # No test reaches GitHub or the developer's real update cache.
    from netconverter_cli import update

    monkeypatch.setenv("NETCONVERTER_NO_UPDATE_CHECK", "1")
    cache = request.getfixturevalue("tmp_path_factory").mktemp("nc-cache")
    monkeypatch.setattr(update, "cache_dir", lambda: cache)
    if "vault" not in request.fixturenames:
        monkeypatch.setattr(cli, "_clerk_session", lambda: None)


@pytest.fixture(autouse=True)
def _no_real_stored_key(request, monkeypatch):
    """First-run setup never sees an API key stored in the developer's real keyring."""
    if "vault" not in request.fixturenames:
        from netconverter_cli import setup

        monkeypatch.setattr(setup, "load_secret", lambda name: "")
