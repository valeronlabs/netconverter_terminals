"""#14: client config locations and formats re-checked against vendor docs (2026-10-29).

- Gemini CLI strips environment variables whose names contain KEY, TOKEN, AUTH,
  SECRET, PASSWORD, CREDENTIAL, ... unless the server's ``env`` lists them, and
  connects no MCP server in an untrusted folder (tester finding MCP-C3).
- Codex CLI starts MCP servers with a cleared environment; ``env_vars`` forwards
  named variables.
- Windsurf is now Devin Desktop; its default agent reads the Devin CLI config.
- Claude Desktop for Linux is a beta with no documented config path.
The live pass/fail matrix on real clients is a tester run (docs/connect/compatibility.md).
"""

import json
import tomllib
from pathlib import Path

import pytest

from netconverter_cli import connect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "executable", lambda: "/opt/bin/netconverter")
    monkeypatch.setattr(connect.shutil, "which", lambda name: None)
    monkeypatch.setattr(connect, "_platform", lambda: "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    work = tmp_path / "migrations"
    work.mkdir()
    return tmp_path, work


def test_gemini_entry_lists_the_bridge_variables_it_would_strip(home, monkeypatch):
    home_dir, work = home
    monkeypatch.setenv("NETCONVERTER_API_KEY", "nck_SYNTHETIC_SHOULD_NOT_BE_WRITTEN")
    change = connect.plan("gemini", work)
    message = change.apply()
    raw = (home_dir / ".gemini" / "settings.json").read_text()
    assert "nck_SYNTHETIC_SHOULD_NOT_BE_WRITTEN" not in raw  # a reference, never a value
    env = json.loads(raw)["mcpServers"]["netconverter"]["env"]
    for name in ("NETCONVERTER_API_KEY", "NETCONVERTER_AUTH", "NETCONVERTER_MCP_AUTH",
                 "NETCONVERTER_CREDENTIAL_PASSPHRASE", "NETCONVERTER_CREDENTIAL_STORE",
                 "NETCONVERTER_KEYRING_TIMEOUT_S"):
        assert env[name] == "$" + name
    assert "trust" in change.summary.lower() and "trust" in message.lower()


def test_codex_forwards_the_bridge_variables(home):
    home_dir, work = home
    change = connect.plan("codex", work)
    change.apply()
    table = tomllib.loads((home_dir / ".codex" / "config.toml").read_text())["mcp_servers"]["netconverter"]
    # 0.5.0: no view flag; the folder's privacy level (#13) is the ceiling
    assert table["args"][:2] == ["mcp", "--workspace"] and "--strict" not in table["args"]
    assert {"NETCONVERTER_API_KEY", "NETCONVERTER_CREDENTIAL_PASSPHRASE",
            "DBUS_SESSION_BUS_ADDRESS"} <= set(table["env_vars"])


def test_devin_desktop_uses_the_devin_cli_config(home, monkeypatch):
    home_dir, work = home
    path = home_dir / ".config" / "devin" / "mcp_config.json"
    assert connect.CLIENTS["devin"].title.startswith("Devin")
    change = connect.plan("devin", work)
    assert change.where == str(path)
    change.apply()
    entry = json.loads(path.read_text())["mcpServers"]["netconverter"]
    assert entry["args"] == ["mcp", "--workspace", str(work.resolve())]  # no view flag (#13)
    assert connect.CLIENTS["devin"].configured()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_dir / "xdg"))
    assert connect.plan("devin", work).where == str(home_dir / "xdg" / "devin" / "mcp_config.json")


def test_windsurf_is_named_as_the_legacy_cascade_config(home):
    _, work = home
    change = connect.plan("windsurf", work)
    assert "legacy" in change.summary.lower() and "devin" in change.summary.lower()


def test_claude_desktop_on_linux_points_at_edit_config(home):
    _, work = home
    change = connect.plan("claude-desktop", work)
    assert not change.can_apply
    assert "Linux" in change.summary and "Edit Config" in change.manual


def test_compatibility_matrix_covers_every_local_client():
    text = (ROOT / "docs" / "connect" / "compatibility.md").read_text(encoding="utf-8")
    assert "2026-10-29" in text and "to verify" in text
    for key, spec in connect.CLIENTS.items():
        if spec.kind == "local":
            assert f"`{key}`" in text, key
    for url in ("code.claude.com/docs/en/mcp", "cursor.com/docs", "code.visualstudio.com/docs",
                "geminicli.com/docs", "docs.devin.ai", "lmstudio.ai", "docs.openclaw.ai"):
        assert url in text, url
