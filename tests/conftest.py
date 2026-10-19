import pytest


@pytest.fixture(autouse=True)
def _no_real_sign_in(request, monkeypatch):
    """Tests never read the developer's real OS sign-in or auth override.

    A test that needs a sign-in patches ``cli._clerk_session`` itself, or uses
    the in-memory ``vault`` credential store (tests/test_clerk.py).
    """
    from netconverter_cli import cli

    monkeypatch.delenv("NETCONVERTER_AUTH", raising=False)
    if "vault" not in request.fixturenames:
        monkeypatch.setattr(cli, "_clerk_session", lambda: None)
