"""#11: the bridge defaults to the strict view; the wider view needs an explicit flag."""
import json

import pytest

from netconverter_cli import cli, connect


@pytest.mark.parametrize("argv,env,view", [
    (["mcp"], {}, "strict"),
    (["mcp", "--strict"], {}, "strict"),
    (["mcp", "--full"], {}, "full"),
    (["mcp", "--view", "full"], {}, "full"),
    (["mcp"], {"NETCONVERTER_MCP_VIEW": "full"}, "full"),
    (["mcp", "--strict"], {"NETCONVERTER_MCP_VIEW": "full"}, "strict"),
    (["mcp"], {"NETCONVERTER_MCP_STRICT": "0"}, "strict"),  # no longer widens on its own
    (["mcp"], {"NETCONVERTER_MCP_VIEW": "bogus"}, "strict"),
])
def test_view_flag_and_environment(monkeypatch, argv, env, view):
    monkeypatch.delenv("NETCONVERTER_MCP_VIEW", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.parser().parse_args(argv).view == view


def run(monkeypatch, argv):
    from netconverter_cli import mcp_server, remote_mcp

    seen = {}

    class FakeRemote:
        def __init__(self, url, credential, client_version=None, view_mode=None):
            seen["view_mode"] = view_mode

        def close(self):
            pass

    monkeypatch.delenv("NETCONVERTER_MCP_VIEW", raising=False)
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_synthetic")
    monkeypatch.setattr(remote_mcp, "RemoteMCP", FakeRemote)
    monkeypatch.setattr(mcp_server, "Bridge", lambda ws, server, rest, remote, **kw: seen.setdefault("strict", kw["strict"]))
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: None)
    cli.run_mcp(cli.parser().parse_args(["--server", "https://api.netconverter.ai/external/v1", *argv]))
    return seen


def test_mcp_without_a_flag_serves_the_strict_view(monkeypatch):
    assert run(monkeypatch, ["mcp"]) == {"view_mode": "strict", "strict": True}


def test_full_view_needs_the_explicit_flag(monkeypatch, capsys):
    assert run(monkeypatch, ["mcp", "--full"]) == {"view_mode": None, "strict": False}
    assert "full view" in capsys.readouterr().err


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(connect.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "executable", lambda: "/opt/bin/netconverter")
    monkeypatch.setattr(connect.shutil, "which", lambda name: None)
    work = tmp_path / "migrations"
    work.mkdir()
    return tmp_path, work


@pytest.mark.parametrize("key", ["claude-desktop", "cursor", "vscode", "gemini", "windsurf", "lmstudio"])
def test_connect_writes_strict_for_json_clients(home, monkeypatch, key):
    _, work = home
    monkeypatch.setattr(connect, "_platform", lambda: "darwin")
    change = connect.plan(key, work)
    assert '"--strict"' in change.preview or "--strict" in change.preview
    change.apply()
    path = change.where
    data = json.loads(open(path).read())
    servers = data.get("mcpServers") or data.get("servers")
    assert servers["netconverter"]["args"] == ["mcp", "--workspace", str(work.resolve()), "--strict"]


def test_connect_writes_strict_for_codex_and_claude_code(home):
    _, work = home
    codex = connect.plan("codex", work)
    assert '"--strict"' in codex.preview
    claude = connect.plan("claude-code", work)
    assert claude.preview.endswith("--strict")
