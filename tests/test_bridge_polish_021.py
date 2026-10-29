"""devnexthop#21: bridge refusals and status that say what to do next."""

import json
from pathlib import Path

import pytest

from netconverter_cli import errors, mcp_server
from netconverter_cli.mcp_server import Bridge

ROOT = Path(__file__).resolve().parents[1]
SERVER = "https://api.example/external/v1"


def payload(result):
    return json.loads(result["content"][0]["text"])


def test_oversized_options_name_the_size_the_limit_and_the_terminal_path(tmp_path):
    (tmp_path / "edge.cfg").write_text("config system global\nend\n")
    bridge = Bridge(tmp_path, SERVER, "nck_synthetic")
    big = {"yaml_v2": "zone_mappings:\n" + "  inside: Trust\n" * 1200}
    result = bridge.call("submit_file", {"path": "edge.cfg", "source_vendor": "fortinet",
                                         "target_vendor": "palo_alto_xml", "options": big})
    body = payload(result)
    assert result["isError"] is True and body["error"] == "invalid_arguments"
    assert body["limit_chars"] == 16_000 and body["options_chars"] > 16_000
    assert "pass settings, not configuration text" not in body["message"]
    assert "yaml_v2" in body["message"] and "netconverter convert" in body["message"]


def test_account_while_signed_out_is_a_status_not_an_error(tmp_path, monkeypatch):
    from netconverter_cli import __version__, update

    monkeypatch.setattr(mcp_server, "keyring_problem", lambda: "")
    monkeypatch.setattr(update, "status", lambda: {"latest": "9.9.9", "update_available": True})
    result = Bridge(tmp_path, SERVER, None).call("account", {})
    assert result["isError"] is False
    body = result["structuredContent"]
    assert body["status"] == "signed_out" and body["signed_in"] is False
    assert body["client_version"] == __version__
    assert body["update_available"] is True and body["latest_version"] == "9.9.9"
    assert body["message"] == errors.SIGNED_OUT


def test_not_signed_in_says_login_then_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "keyring_problem", lambda: "")
    body = payload(Bridge(tmp_path, SERVER, None).call("job_status", {"job_id": "trm_1"}))
    assert body["error"] == "not_signed_in"
    assert "Sign in with `netconverter login`" in body["message"] and "then retry" in body["message"]
    assert "restart" not in body["message"]


def test_a_sign_in_made_after_start_is_used_on_retry(tmp_path, monkeypatch):
    """"then retry" is true: the bridge looks for a credential again instead of needing a restart."""
    monkeypatch.setattr(mcp_server, "keyring_problem", lambda: "")
    found = []
    bridge = Bridge(tmp_path, SERVER, None, credential_loader=lambda: found[0] if found else (None, None, "none", []))
    assert payload(bridge.call("job_status", {"job_id": "trm_1"}))["error"] == "not_signed_in"
    found.append(("nck_synthetic", "nck_synthetic", "api_key_stored", []))
    monkeypatch.setattr(mcp_server, "detect_profile", lambda *a, **k: ("external", frozenset({"convert"})))
    assert bridge.profile() == ("external", frozenset({"convert"}))
    assert bridge.rest_credential == "nck_synthetic" and bridge.credential_source == "api_key_stored"


def test_yaml_v2_import_path_is_documented():
    for doc in ("docs/COMMANDS.md", "README.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert '"yaml_v2"' in text and "--options" in text, doc
