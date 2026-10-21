"""The Clerk sign-in is bound to trusted NetConverter hosts.

Security review 2026-10-18: a workspace's .netconverter/connection.json is
untrusted (a shared or cloned folder can carry one). It must not be able to
point the client at another server and receive the user's Clerk token, nor
select Clerk as the credential.
"""
import pytest

from netconverter_cli import cli


@pytest.mark.parametrize("url,ok", [
    ("https://api.netconverter.ai/external/v1", True),
    ("https://api.netconverter.ai/mcp/v1/", True),
    ("https://API.netconverter.ai/external/v1", True),
    ("http://api.netconverter.ai/external/v1", False),
    ("https://api.netconverter.ai.evil.example/external/v1", False),
    ("https://evil.example/external/v1", False),
    ("https://api.netconverter.ai@evil.example/external/v1", False),
    ("", False),
])
def test_clerk_only_to_trusted_https_hosts(monkeypatch, url, ok):
    monkeypatch.delenv("NETCONVERTER_TRUSTED_HOSTS", raising=False)
    assert cli.clerk_allowed(url) is ok


def test_user_environment_can_trust_another_host(monkeypatch):
    monkeypatch.setenv("NETCONVERTER_TRUSTED_HOSTS", "staging.netconverter.ai")
    assert cli.clerk_allowed("https://staging.netconverter.ai/external/v1")


def test_workspace_settings_cannot_select_clerk(monkeypatch):
    monkeypatch.delenv("NETCONVERTER_AUTH", raising=False)
    assert cli.clerk_preferred({"auth": "clerk"}) is False
    monkeypatch.setenv("NETCONVERTER_AUTH", "clerk")
    assert cli.clerk_preferred({}) is True


def test_rest_credential_refuses_untrusted_server_with_clerk(monkeypatch):
    monkeypatch.setenv("NETCONVERTER_AUTH", "clerk")
    monkeypatch.delenv("NETCONVERTER_TRUSTED_HOSTS", raising=False)
    monkeypatch.setattr(cli, "_clerk_session", lambda: pytest.fail("token must not be loaded"))
    with pytest.raises(SystemExit):
        cli.rest_credential("https://evil.example/external/v1", {})


def test_mcp_bridge_never_hands_the_token_to_an_untrusted_url(monkeypatch):
    monkeypatch.delenv("NETCONVERTER_TRUSTED_HOSTS", raising=False)
    sentinel = object()
    seen = {}

    class FakeRemote:
        def __init__(self, url, credential, client_version=None):
            seen["url"], seen["credential"] = url, credential

        def close(self):
            pass

    import netconverter_cli.mcp_server as mcp_server
    import netconverter_cli.remote_mcp as remote_mcp

    monkeypatch.setattr(cli, "_clerk_session", lambda: sentinel)
    monkeypatch.setattr(cli, "get_secret", lambda *a, **k: "")
    monkeypatch.setattr(remote_mcp, "RemoteMCP", FakeRemote)
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: seen.setdefault("rest", bridge))
    monkeypatch.setattr(mcp_server, "Bridge", lambda ws, server, rest, remote, **kw: rest)

    args = type("A", (), {"server": "https://evil.example/external/v1", "auth": "auto",
                          "mcp_url": "https://evil.example/mcp/v1/", "no_remote": False,
                          "workspace": "."})()
    cli.run_mcp(args)
    assert seen.get("credential") is not sentinel
    assert seen.get("rest") is not sentinel
