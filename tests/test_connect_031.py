"""0.3.1 connect targets: Gemini CLI, Windsurf, LM Studio, remote ChatGPT / claude.ai, --all."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconverter_cli import cli, connect


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "executable", lambda: "/opt/bin/netconverter")
    monkeypatch.setattr(connect.shutil, "which", lambda name: None)
    monkeypatch.setattr(connect, "_platform", lambda: "linux")  # no Claude Desktop
    work = tmp_path / "migrations"
    work.mkdir()
    return tmp_path, work


def _args(work, **kw):
    base = dict(workspace=str(work), client=None, print_only=False, yes=True, all=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("key,rel", [
    ("gemini", ".gemini/settings.json"),
    ("windsurf", ".codeium/windsurf/mcp_config.json"),
    ("lmstudio", ".lmstudio/mcp.json"),
])
def test_json_clients_merge_and_keep_other_keys(home, key, rel):
    home_dir, work = home
    path = home_dir / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))
    assert not connect.CLIENTS[key].configured()
    change = connect.plan(key, work)
    assert change.can_apply and change.preview.startswith("---")
    change.apply()
    data = json.loads(path.read_text())
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["netconverter"]["args"] == ["mcp", "--workspace", str(work.resolve())]
    assert path.with_name(path.name + ".bak").exists()
    assert connect.CLIENTS[key].configured()


def test_invalid_json_is_not_overwritten(home):
    home_dir, work = home
    path = home_dir / ".gemini" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    change = connect.plan("gemini", work)
    assert not change.can_apply and path.read_text() == "{not json"


@pytest.mark.parametrize("key", ["chatgpt", "claude-ai"])
def test_remote_clients_print_steps_and_exit_cleanly(home, key, capsys, monkeypatch):
    home_dir, work = home
    monkeypatch.setenv("NETCONVERTER_MCP_URL", "https://example.test/mcp/v1/")
    change = connect.plan(key, work)
    assert not change.can_apply and "https://example.test/mcp/v1" in change.preview
    cli.run_connect(_args(work, client=key))  # no SystemExit: steps are not a failure
    out = capsys.readouterr().out
    assert "https://example.test/mcp/v1" in out and not list(home_dir.rglob("*.json"))


def test_list_marks_connected_found_and_remote(home, capsys):
    home_dir, work = home
    (home_dir / ".gemini").mkdir()
    cli.run_connect(_args(work))
    out = capsys.readouterr().out
    assert "○ gemini" in out and "found on this computer" in out
    assert "↗ chatgpt" in out and "--all" in out


def test_all_connects_only_installed_local_clients(home, capsys):
    home_dir, work = home
    (home_dir / ".gemini").mkdir()
    (home_dir / ".lmstudio").mkdir()
    cli.run_connect(_args(work, all=True))
    assert connect.CLIENTS["gemini"].configured() and connect.CLIENTS["lmstudio"].configured()
    assert not (home_dir / ".codeium").exists() and not (home_dir / ".cursor" / "mcp.json").exists()
    cli.run_connect(_args(work, all=True))
    assert "already connected" in capsys.readouterr().out
