"""`connect` replaces an assistant's direct NetConverter server entry with the bridge.

Since the server honours only known apps, a desktop assistant pointed straight at
https://api.netconverter.ai/mcp/v1/ is refused (oauth_client_not_enrolled). The
bridge signs in with NetConverter's own client, so connecting it removes the
refused entry and keeps every unrelated server.
"""
import json

from netconverter_cli import connect


def _config(path, servers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))


DIRECT = {"url": "https://api.netconverter.ai/mcp/v1/"}
OTHER = {"url": "https://mcp.example.com/sse"}


def test_cursor_direct_entry_is_replaced_by_the_bridge(tmp_path, monkeypatch):
    path = tmp_path / ".cursor" / "mcp.json"
    _config(path, {"netconverter-server": DIRECT, "github": OTHER})
    monkeypatch.setattr(connect, "_cursor_path", lambda: path)
    change = connect.plan("cursor", tmp_path)
    assert "netconverter-server" in change.summary and "refuses" in change.summary
    change.apply()
    servers = json.loads(path.read_text())["mcpServers"]
    assert "netconverter-server" not in servers
    assert servers["github"] == OTHER
    assert servers["netconverter"]["args"][0] == "mcp"


def test_json_clients_drop_direct_entries_too(tmp_path, monkeypatch):
    path = tmp_path / ".gemini" / "settings.json"
    _config(path, {"nc": {"serverUrl": "https://api.netconverter.ai/mcp/v1"}, "other": OTHER})
    monkeypatch.setattr(connect, "_gemini_path", lambda: path)
    change = connect.plan("gemini", tmp_path)
    assert "nc" in change.summary
    change.apply()
    servers = json.loads(path.read_text())["mcpServers"]
    assert set(servers) == {"other", "netconverter"}


def test_nothing_to_replace_keeps_the_old_summary(tmp_path, monkeypatch):
    path = tmp_path / ".cursor" / "mcp.json"
    _config(path, {"github": OTHER})
    monkeypatch.setattr(connect, "_cursor_path", lambda: path)
    change = connect.plan("cursor", tmp_path)
    assert "Removes" not in change.summary
    change.apply()
    assert set(json.loads(path.read_text())["mcpServers"]) == {"github", "netconverter"}
