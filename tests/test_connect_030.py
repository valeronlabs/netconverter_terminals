"""0.3.0 connect targets: Claude Desktop and the Claude Code read rule. Home is a temp folder."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconverter_cli import cli, connect


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "executable", lambda: "/opt/bin/netconverter")
    work = tmp_path / "migrations"
    work.mkdir()
    return tmp_path, work


def desktop_file(home_dir):
    return home_dir / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def test_claude_desktop_merges_entry_keeps_keys_and_backs_up(home, monkeypatch):
    home_dir, work = home
    monkeypatch.setattr(connect, "_platform", lambda: "darwin")
    path = desktop_file(home_dir)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "globalShortcut": "Cmd+Space"}))
    change = connect.plan("claude-desktop", work)
    assert change.can_apply and change.where == str(path)
    assert '+    "netconverter": {' in change.preview and change.preview.startswith("---")
    assert not connect._desktop_configured()
    change.apply()
    data = json.loads(path.read_text())
    assert data["globalShortcut"] == "Cmd+Space" and data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["netconverter"] == {
        "command": "/opt/bin/netconverter", "args": ["mcp", "--workspace", str(work.resolve())]}
    assert json.loads(path.with_name(path.name + ".bak").read_text())["globalShortcut"] == "Cmd+Space"
    assert connect._desktop_configured()
    assert "Claude Desktop" in connect.configured_clients(work)


def test_claude_desktop_new_file_and_windows_path(home, monkeypatch):
    home_dir, work = home
    monkeypatch.setattr(connect, "_platform", lambda: "win32")
    monkeypatch.setenv("APPDATA", str(home_dir / "Roaming"))
    change = connect.plan("claude-desktop", work)
    expected = home_dir / "Roaming" / "Claude" / "claude_desktop_config.json"
    assert change.where == str(expected) and "/dev/null" in change.preview
    change.apply()
    assert "netconverter" in json.loads(expected.read_text())["mcpServers"]


def test_claude_desktop_refuses_invalid_json_and_unsupported_platform(home, monkeypatch):
    home_dir, work = home
    monkeypatch.setattr(connect, "_platform", lambda: "darwin")
    path = desktop_file(home_dir)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert connect.plan("claude-desktop", work).can_apply is False
    path.write_text('{"mcpServers": []}')
    assert connect.plan("claude-desktop", work).can_apply is False
    assert path.read_text() == '{"mcpServers": []}'
    monkeypatch.setattr(connect, "_platform", lambda: "linux")
    assert connect.plan("claude-desktop", work).can_apply is False


@pytest.mark.parametrize("root,rule", [
    ("/Users/pilot/migrations", "Read(//Users/pilot/migrations/**)"),
    ("C:/Users/pilot/migrations", "Read(//c/Users/pilot/migrations/**)"),
])
def test_read_deny_rule_uses_absolute_rule_syntax(root, rule):
    assert connect.read_deny_rule(Path(root)) == rule


def test_claude_code_offers_read_deny_rule_and_merges(home):
    home_dir, work = home
    settings = home_dir / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"model": "x", "permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read(./docs/**)"]}}))
    change = connect.plan("claude-code", work)
    [extra] = change.followups
    rule = connect.read_deny_rule(work.resolve())
    assert extra.default_yes and extra.can_apply and rule in extra.preview
    assert "bridge uploads configurations by path" in extra.summary
    extra.apply()
    data = json.loads(settings.read_text())
    assert data["permissions"]["deny"] == ["Bash(rm:*)", rule]
    assert data["permissions"]["allow"] == ["Read(./docs/**)"] and data["model"] == "x"
    assert settings.with_name("settings.json.bak").exists()
    again = connect.plan("claude-code", work).followups[0]
    assert again.can_apply is False  # already present: nothing to add


def test_claude_code_read_rule_refuses_unmergeable_settings(home):
    home_dir, work = home
    settings = home_dir / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"permissions": {"deny": "Bash"}}')
    assert connect.plan("claude-code", work).followups[0].can_apply is False
    settings.write_text("not json")
    assert connect.plan("claude-code", work).followups[0].can_apply is False
    assert settings.read_text() == "not json"


def connect_args(work, client="claude-code", yes=False, print_only=False):
    return SimpleNamespace(workspace=str(work), client=client, yes=yes, print_only=print_only)


def fake_claude(monkeypatch):
    calls = []
    monkeypatch.setattr(connect.shutil, "which", lambda name: "/opt/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(connect.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    return calls


@pytest.mark.parametrize("answers,applied", [(["y", ""], True), (["y", "y"], True), (["y", "n"], False)])
def test_cli_connect_prompts_for_read_rule_default_yes(home, monkeypatch, capsys, answers, applied):
    home_dir, work = home
    calls = fake_claude(monkeypatch)
    replies, prompts = iter(answers), []
    cli.run_connect(connect_args(work), ask=lambda prompt: prompts.append(prompt) or next(replies))
    assert calls and calls[0][:4] == ["/opt/bin/claude", "mcp", "add", "--scope"]
    assert prompts[0].endswith("[y/N] ") and prompts[1].endswith("[Y/n] ")
    settings = home_dir / ".claude" / "settings.json"
    assert settings.exists() is applied


def test_cli_connect_declined_main_change_offers_nothing(home, monkeypatch, capsys):
    home_dir, work = home
    calls = fake_claude(monkeypatch)
    prompts = []
    cli.run_connect(connect_args(work), ask=lambda prompt: prompts.append(prompt) or "n")
    assert calls == [] and len(prompts) == 1
    assert not (home_dir / ".claude" / "settings.json").exists()


def test_cli_connect_print_shows_read_rule_without_writing(home, monkeypatch, capsys):
    home_dir, work = home
    fake_claude(monkeypatch)
    cli.run_connect(connect_args(work, print_only=True), ask=lambda prompt: pytest.fail("prompted"))
    out = capsys.readouterr().out
    assert connect.read_deny_rule(work.resolve()) in out
    assert not (home_dir / ".claude" / "settings.json").exists()


def test_cli_connect_yes_applies_both(home, monkeypatch):
    home_dir, work = home
    fake_claude(monkeypatch)
    cli.run_connect(connect_args(work, yes=True), ask=lambda prompt: pytest.fail("prompted"))
    data = json.loads((home_dir / ".claude" / "settings.json").read_text())
    assert data["permissions"]["deny"] == [connect.read_deny_rule(work.resolve())]


def test_connect_parser_accepts_claude_desktop():
    assert cli.parser().parse_args(["connect", "claude-desktop"]).client == "claude-desktop"


@pytest.mark.asyncio
async def test_app_connect_offers_the_read_rule_after_claude_code(home, monkeypatch):
    from unittest.mock import Mock
    from textual.widgets import RichLog
    from netconverter_cli.controller import Controller
    from netconverter_cli.tui import Terminal

    home_dir, work = home
    fake_claude(monkeypatch)
    client = Mock()
    client.capabilities.return_value = {"remaining": {"convert": 2}}
    app = Terminal(Controller(work, client))
    async with app.run_test(size=(126, 41)) as pilot:
        await pilot.pause()
        app.apply_connect(connect.plan("claude-code", work))
        await pilot.pause()
        text = "\n".join(line.text for line in app.query_one(RichLog).lines)
        assert "Claude Code connected" in text and "Claude Code read rule" in text
        assert not (home_dir / ".claude" / "settings.json").exists()  # still waiting for a yes
