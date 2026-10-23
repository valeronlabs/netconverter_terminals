"""#16: one principal per `netconverter mcp` process.

The bridge honours NETCONVERTER_AUTH, prefers the signed-in session in auto
mode, and never sends one credential to the REST API and another to the
remote MCP tools. Nothing here reaches a server or a real keyring.
"""

import pytest

from netconverter_cli import cli

PROD = "https://api.netconverter.ai/external/v1"


class FakeSession:
    kind = "clerk"
    signed_in = True


@pytest.fixture
def harness(monkeypatch):
    """Capture what run_mcp hands to the bridge (REST) and to RemoteMCP (remote)."""
    from netconverter_cli import mcp_server, remote_mcp

    seen = {}

    class FakeRemote:
        def __init__(self, url, credential, client_version=None, **kw):
            seen["remote"] = credential

        def close(self):
            pass

    class FakeBridge:
        def __init__(self, ws, server, rest, remote, **kw):
            seen["rest"], seen["bridge_kw"] = rest, kw

    for name in ("NETCONVERTER_AUTH", "NETCONVERTER_MCP_AUTH", "NETCONVERTER_API_KEY",
                 "NETCONVERTER_TRUSTED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(remote_mcp, "RemoteMCP", FakeRemote)
    monkeypatch.setattr(mcp_server, "Bridge", FakeBridge)
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: None)
    return seen


def run(monkeypatch, argv, *, session=None, key=""):
    monkeypatch.setattr(cli, "_clerk_session", lambda: session)
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: key)
    args = cli.parser().parse_args(["--server", PROD, "mcp", *argv])
    cli.run_mcp(args)
    return args


def test_netconverter_auth_clerk_is_honoured_by_mcp(monkeypatch, harness, capsys):
    monkeypatch.setenv("NETCONVERTER_AUTH", "clerk")
    monkeypatch.setenv("NETCONVERTER_API_KEY", "nck_env_synthetic")
    session = FakeSession()
    args = run(monkeypatch, [], session=session, key="nck_env_synthetic")
    assert args.auth == "clerk"
    assert harness["rest"] is session and harness["remote"] is session
    assert "nck_env_synthetic" not in capsys.readouterr().err


def test_auto_with_both_prefers_the_session_and_names_the_ignored_key(monkeypatch, harness, capsys):
    monkeypatch.setenv("NETCONVERTER_API_KEY", "nck_env_synthetic")
    session = FakeSession()
    run(monkeypatch, [], session=session, key="nck_env_synthetic")
    assert harness["rest"] is session and harness["remote"] is session
    err = capsys.readouterr().err
    assert "NETCONVERTER_API_KEY" in err and "ignor" in err and "nck_env_synthetic" not in err
    assert harness["bridge_kw"]["credential_source"] == "clerk_session"


def test_auto_with_a_stored_key_and_a_session_prefers_the_session(monkeypatch, harness, capsys):
    session = FakeSession()
    run(monkeypatch, [], session=session, key="nck_stored_synthetic")
    assert harness["rest"] is session and harness["remote"] is session
    assert "credential store" in capsys.readouterr().err


def test_auto_with_only_a_key_uses_it_for_rest_and_remote(monkeypatch, harness, capsys):
    monkeypatch.setenv("NETCONVERTER_API_KEY", "nck_env_synthetic")
    run(monkeypatch, [], session=None, key="nck_env_synthetic")
    assert harness["rest"] == "nck_env_synthetic" and harness["remote"] == "nck_env_synthetic"
    assert harness["bridge_kw"]["credential_source"] == "api_key_environment"
    err = capsys.readouterr().err
    assert "NETCONVERTER_API_KEY" in err and "nck_env_synthetic" not in err


def test_auth_key_uses_the_key_even_when_signed_in(monkeypatch, harness):
    monkeypatch.setenv("NETCONVERTER_AUTH", "key")
    run(monkeypatch, [], session=FakeSession(), key="nck_stored_synthetic")
    assert harness["rest"] == "nck_stored_synthetic" and harness["remote"] == "nck_stored_synthetic"
    assert harness["bridge_kw"]["credential_source"] == "api_key_stored"


@pytest.mark.parametrize("env,argv,expected", [
    ({}, [], "auto"),
    ({"NETCONVERTER_AUTH": "clerk"}, [], "clerk"),
    ({"NETCONVERTER_AUTH": "key"}, [], "key"),
    ({"NETCONVERTER_AUTH": "bogus"}, [], "auto"),
    ({"NETCONVERTER_AUTH": "clerk", "NETCONVERTER_MCP_AUTH": "key"}, [], "key"),  # the specific one wins
    ({"NETCONVERTER_AUTH": "clerk"}, ["--auth", "key"], "key"),  # the flag wins over both
])
def test_mcp_auth_default_follows_the_environment(monkeypatch, env, argv, expected):
    for name in ("NETCONVERTER_AUTH", "NETCONVERTER_MCP_AUTH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.parser().parse_args(["mcp", *argv]).auth == expected


def test_account_reports_the_credential_source(tmp_path, monkeypatch):
    import httpx

    from netconverter_cli import update
    from netconverter_cli.api import StaticCredential
    from netconverter_cli.mcp_server import Bridge
    from tests.test_mcp import AccountServer, call

    monkeypatch.setattr(update, "status", lambda: {"latest": None, "update_available": None})
    bridge = Bridge(tmp_path, "https://api.example/external/v1", StaticCredential("nck_synthetic"),
                    transport=httpx.MockTransport(AccountServer({"principal": {"kind": "api_key"}})),
                    credential_source="api_key_environment")
    _, payload = call(bridge, "account")
    assert payload["credential_source"] == "api_key_environment" and payload["auth_kind"] == "api_key"
