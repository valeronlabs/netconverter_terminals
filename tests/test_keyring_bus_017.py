"""#17: an AI client that starts the bridge without DBUS_SESSION_BUS_ADDRESS.

Codex, Cursor CLI and OpenClaw launch stdio MCP servers with a near-empty
environment on Linux. jeepney (keyring → SecretService) reads only that
variable, so the Secret Service sign-in is invisible and every tool said "not
signed in". The client now finds the user's bus socket itself and, when no
keyring is reachable, says so and names the fix. No real keyring is touched.
"""

import json

from netconverter_cli import credentials
from netconverter_cli.mcp_server import Bridge


def fallback(environ, present, platform="linux", uid=1000):
    return credentials.session_bus_fallback(environ, platform=platform, uid=uid, exists=lambda p: p in present)


def test_session_bus_fallback_prefers_xdg_runtime_dir_then_run_user():
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert fallback(env, {"/run/user/1000/bus"}) == "/run/user/1000/bus"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    env = {}
    assert fallback(env, {"/run/user/1000/bus"}) == "/run/user/1000/bus"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


def test_session_bus_fallback_leaves_an_existing_address_and_other_platforms_alone():
    env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/custom/bus"}
    assert fallback(env, {"/run/user/1000/bus"}) is None
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/custom/bus"
    for platform in ("darwin", "win32"):
        env = {}
        assert fallback(env, {"/run/user/1000/bus"}, platform=platform) is None
        assert "DBUS_SESSION_BUS_ADDRESS" not in env


def test_session_bus_fallback_without_a_socket_sets_nothing():
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert fallback(env, set()) is None
    assert "DBUS_SESSION_BUS_ADDRESS" not in env


class FailKeyring:
    """What keyring picks on Linux without a reachable Secret Service."""


def test_keyring_problem_names_the_missing_bus(monkeypatch):
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: FailKeyring())
    monkeypatch.setattr(credentials, "session_bus_fallback", lambda *a, **k: None)
    monkeypatch.setattr(credentials.sys, "platform", "linux")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    problem = credentials.keyring_problem()
    assert "DBUS_SESSION_BUS_ADDRESS" in problem and "/run/user/<uid>/bus" in problem
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    assert "did not answer" in credentials.keyring_problem()


def test_keyring_problem_is_empty_for_an_os_store(monkeypatch):
    class Backend:
        pass
    Backend.__module__ = "keyring.backends.SecretService"
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: Backend())
    assert credentials.keyring_problem() == ""


def test_bridge_without_a_credential_explains_an_unreachable_keyring(tmp_path, monkeypatch):
    from netconverter_cli import mcp_server

    monkeypatch.setattr(mcp_server, "keyring_problem",
                        lambda: "no D-Bus session bus: DBUS_SESSION_BUS_ADDRESS is not set")
    bridge = Bridge(tmp_path, "https://api.example/external/v1", None)
    result = bridge.call("job_status", {"job_id": "trm_1"})
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is True and payload["error"] == "keyring_unreachable"
    assert "DBUS_SESSION_BUS_ADDRESS" in payload["message"] and "NETCONVERTER_API_KEY" in payload["message"]
    assert "not signed in" not in payload["message"].lower()
    # The account tool answers with the same status instead of a bare "not signed in".
    account = json.loads(bridge.call("account", {})["content"][0]["text"])
    assert account["status"] == "keyring_unreachable" and account["signed_in"] is False  # a status (#21)
    assert "DBUS_SESSION_BUS_ADDRESS" in account["message"]


def test_bridge_without_a_credential_and_a_working_keyring_says_sign_in(tmp_path, monkeypatch):
    from netconverter_cli import mcp_server

    monkeypatch.setattr(mcp_server, "keyring_problem", lambda: "")
    bridge = Bridge(tmp_path, "https://api.example/external/v1", None)
    payload = json.loads(bridge.call("job_status", {"job_id": "trm_1"})["content"][0]["text"])
    assert payload["error"] == "not_signed_in" and "netconverter login" in payload["message"]


def test_mcp_startup_line_names_the_unreachable_keyring(monkeypatch, capsys):
    from netconverter_cli import cli

    monkeypatch.setattr(cli, "_clerk_session", lambda: None)
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "")
    monkeypatch.setattr(cli, "keyring_problem", lambda: "no D-Bus session bus: DBUS_SESSION_BUS_ADDRESS is not set")
    rest, remote, source, notes = cli.choose_mcp_credential(
        "auto", "https://api.netconverter.ai/external/v1", "https://api.netconverter.ai/mcp/v1/")
    assert rest is None and remote is None and source == "none"
    assert any("DBUS_SESSION_BUS_ADDRESS" in n for n in notes)
