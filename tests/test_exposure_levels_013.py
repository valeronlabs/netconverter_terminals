"""#13: user-controlled exposure levels (none / masked / selected / full).

The level is per workspace (default masked), can be raised only with a
confirmation typed in a terminal, is never changeable through MCP, is
audited locally, is sent to the server on every remote request and is
applied again to every tool result by the bridge. Secrets are stripped at
every level. Mocked transport and synthetic RFC 5737 / RFC 1918 data only.
"""

import json

import httpx
import pytest

from netconverter_cli import exposure
from netconverter_cli.api import StaticCredential
from netconverter_cli.mcp_server import Bridge, StdioServer
from netconverter_cli.remote_mcp import RemoteMCP
from tests.test_mcp import LOCAL, QuickServer

PSK = "Synth3ticPsk!42"
COMMUNITY = "synthCommunity77"
CRYPT = "$6$saltsalt$abcdefghijklmnopqrstuvwxyz0123456789"
TYPE7 = "0822455D0A16"
NAME = "SYNTH_OBJECT_DMZ_WEB"

# One job's results as a remote server might serve them (deliberately leaky: the
# server is not trusted to have applied any view).
RESULT = {
    "tool": "get_report", "success": True, "error": None,
    "data": {
        "job_id": "tra_0123456789abcdef", "translation_status": "needs_review", "verdict": "needs_review",
        "counts": {"rules": 12, "findings": 3},
        "summary": f"object {NAME} host 192.0.2.10 behind 10.20.30.1/24",
        "findings": [
            {"severity": "high", "category": "vpn", "message": f"tunnel to 198.51.100.7 pre-shared-key {PSK}"},
            {"severity": "low", "category": "snmp", "message": f"snmp-server community {COMMUNITY} RO"},
            {"severity": "medium", "category": "auth", "message": f"username admin password 7 {TYPE7}"},
        ],
        "vpn": {"peer": "198.51.100.7", "psk": PSK, "psk_configured": True},
        "users": [{"name": "admin", "password_hash": CRYPT}],
        "text_included": True,
        "raw_line": f"enable secret 5 {CRYPT}",
    },
}
SECRETS = (PSK, COMMUNITY, CRYPT, TYPE7)
ADDRESSES = ("192.0.2.10", "10.20.30.1/24", "198.51.100.7")
TOOLS = ("get_account", "get_report", "get_evidence", "get_job_brief", "fetch", "get_nat_summary",
         "get_route_summary")


class JobServer:
    def __init__(self, view_mode="default"):
        self.view_mode, self.requests = view_mode, []

    def __call__(self, request):
        self.requests.append(request)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        method, params = message["method"], message.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "r"}}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": "d", "inputSchema": {"type": "object"}} for n in TOOLS]}
        else:
            payload = ({"tool": "get_account", "success": True, "data": {"view_mode": self.view_mode}}
                       if params["name"] == "get_account" else RESULT)
            result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                      "structuredContent": payload, "isError": False}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def calls(self):
        return [json.loads(r.content)["params"]["name"] for r in self.requests
                if json.loads(r.content).get("method") == "tools/call"]


def bridge_at(tmp_path, level, sections=()):
    server = JobServer()
    remote = RemoteMCP("https://api.example/mcp/v1/", StaticCredential("REMOTE_TOKEN"),
                       transport=httpx.MockTransport(server), view_mode=level)
    bridge = Bridge(tmp_path, "https://api.example/external/v1", StaticCredential("nck_synthetic"), remote,
                    transport=httpx.MockTransport(QuickServer()), level=level, sections=sections)
    return bridge, server


def report(tmp_path, level, sections=()):
    bridge, server = bridge_at(tmp_path, level, sections)
    result = bridge.call("get_report", {"job_id": "tra_0123456789abcdef"})
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result, server


# -- per-level golden results over one job ----------------------------------

@pytest.mark.parametrize("level", exposure.LEVELS)
def test_secrets_are_absent_at_every_level(tmp_path, level):
    result, _ = report(tmp_path, level)
    wire = json.dumps(result)
    for secret in SECRETS:
        assert secret not in wire


def test_full_is_as_served_apart_from_secrets(tmp_path):
    result, server = report(tmp_path, "full")
    data = result["structuredContent"]["data"]
    assert data["summary"] == RESULT["data"]["summary"]  # addresses and names as served
    assert data["vpn"] == {"peer": "198.51.100.7", "psk": "<secret>", "psk_configured": True}
    assert data["users"] == [{"name": "admin", "password_hash": "<secret>"}]
    assert data["findings"][0]["message"] == "tunnel to 198.51.100.7 pre-shared-key <secret>"
    assert data["findings"][1]["message"] == "snmp-server community <secret> RO"
    assert data["findings"][2]["message"] == "username admin password 7 <secret>"
    assert data["raw_line"] == "enable secret 5 <secret>"
    assert all(r.headers["X-NetConverter-View"] == "full" for r in server.requests)


def test_masked_is_the_strict_view_with_addresses_masked(tmp_path):
    result, server = report(tmp_path, "masked")
    data = result["structuredContent"]["data"]
    assert data["summary"] == f"object {NAME} host <ip> behind <cidr>"
    assert data["vpn"]["peer"] == "<ip>" and data["vpn"]["psk"] == "<secret>"
    for raw in ADDRESSES:
        assert raw not in json.dumps(result)
    assert all(r.headers["X-NetConverter-View"] == "masked" for r in server.requests)


def test_none_keeps_only_verdicts_and_counts(tmp_path):
    result, server = report(tmp_path, "none")
    data = result["structuredContent"]["data"]
    assert data == {
        "job_id": "tra_0123456789abcdef", "translation_status": "needs_review", "verdict": "needs_review",
        "counts": {"rules": 12, "findings": 3},
        "findings": [{"severity": "high", "category": "vpn"}, {"severity": "low", "category": "snmp"},
                     {"severity": "medium", "category": "auth"}],
        "vpn": {"psk_configured": True},
        "text_included": True,
    }
    wire = json.dumps(result)
    assert NAME not in wire and "admin" not in wire
    assert all(r.headers["X-NetConverter-View"] == "none" for r in server.requests)


def test_none_withholds_text_that_is_not_json(tmp_path):
    from netconverter_cli.mcp_server import apply_exposure

    result = {"content": [{"type": "text", "text": f"object {NAME} host 192.0.2.10"}], "isError": False}
    out = apply_exposure(result, exposure.Exposure("none"))
    assert NAME not in json.dumps(out) and "withheld" in out["content"][0]["text"]


def test_selected_widens_only_the_chosen_sections(tmp_path):
    bridge, server = bridge_at(tmp_path, "selected", ("nat",))
    names = [t["name"] for t in bridge.list_tools()]
    assert "get_nat_summary" in names and "get_route_summary" not in names
    result = bridge.call("get_nat_summary", {"job_id": "j"})
    assert result["isError"] is False and "192.0.2.10" not in json.dumps(result)  # still masked
    assert bridge.call("get_route_summary", {"job_id": "j"})["isError"] is True
    refused = bridge.call("get_evidence", {"job_id": "j", "section": "unparsed_lines"})
    assert refused["isError"] is True
    bridge, server = bridge_at(tmp_path, "selected", ("unparsed_lines",))
    assert bridge.call("get_evidence", {"job_id": "j", "section": "unparsed_lines"})["isError"] is False
    assert all(r.headers["X-NetConverter-View"] == "selected" for r in server.requests)


def test_masked_and_none_list_only_the_strict_tool_set(tmp_path):
    for level in ("none", "masked"):
        bridge, _ = bridge_at(tmp_path, level)
        names = [t["name"] for t in bridge.list_tools()]
        assert names == LOCAL + ["get_account", "get_report", "get_evidence", "get_job_brief", "fetch"]
    bridge, _ = bridge_at(tmp_path, "full")
    assert "get_nat_summary" in [t["name"] for t in bridge.list_tools()]


def test_local_results_lose_secret_values_too():
    from netconverter_cli.exposure import strip_secrets

    assert strip_secrets({"password": "x", "psk_count": 2, "secret_present": True}) == \
        {"password": "<secret>", "psk_count": 2, "secret_present": True}
    assert strip_secrets("key ENC abcdefghij== and -AQ==abcdEFGH12345") == "key ENC <secret> and <secret>"
    # Prose about passwords is not a value.
    assert strip_secrets("the password policy is weak") == "the password policy is weak"


# -- the workspace level: storage, raise confirmation, audit -----------------

def test_default_level_is_masked(tmp_path):
    assert exposure.load(tmp_path) == exposure.Exposure("masked")


def test_lowering_needs_no_terminal_and_is_audited(tmp_path):
    exposure.set_level(tmp_path, "none", interactive=False, user="tester")
    assert exposure.load(tmp_path).level == "none"
    entries = [json.loads(line) for line in exposure.audit_path(tmp_path).read_text().splitlines()]
    assert entries[-1]["old"] == "masked" and entries[-1]["new"] == "none"
    assert entries[-1]["user"] == "tester" and entries[-1]["workspace"] == str(tmp_path.resolve())
    assert entries[-1]["confirmed"] == "not_needed" and "time" in entries[-1]


def test_raising_without_a_terminal_is_refused(tmp_path):
    with pytest.raises(exposure.ExposureError, match="terminal"):
        exposure.set_level(tmp_path, "full", interactive=False)
    assert exposure.load(tmp_path).level == "masked"
    assert not exposure.audit_path(tmp_path).exists()


def test_raising_needs_the_typed_phrase(tmp_path):
    with pytest.raises(exposure.ExposureError, match="not confirmed"):
        exposure.set_level(tmp_path, "full", interactive=True, ask=lambda prompt: "yes")
    assert exposure.load(tmp_path).level == "masked"
    prompts = []
    exposure.set_level(tmp_path, "full", interactive=True,
                       ask=lambda prompt: prompts.append(prompt) or "raise to full")
    assert exposure.load(tmp_path).level == "full" and "raise to full" in prompts[0]
    last = json.loads(exposure.audit_path(tmp_path).read_text().splitlines()[-1])
    assert last["new"] == "full" and last["confirmed"] == "tty"


def test_adding_a_section_is_a_raise(tmp_path):
    exposure.set_level(tmp_path, "selected", ["nat"], interactive=True, ask=lambda p: "raise to selected")
    with pytest.raises(exposure.ExposureError):
        exposure.set_level(tmp_path, "selected", ["nat", "routes"], interactive=False)
    exposure.set_level(tmp_path, "selected", [], interactive=False)  # dropping one lowers
    assert exposure.load(tmp_path) == exposure.Exposure("selected", ())


def test_unknown_level_or_section_is_refused(tmp_path):
    with pytest.raises(exposure.ExposureError):
        exposure.set_level(tmp_path, "everything", interactive=True, ask=lambda p: "x")
    with pytest.raises(exposure.ExposureError):
        exposure.set_level(tmp_path, "selected", ["passwords"], interactive=True, ask=lambda p: "x")


def test_a_hand_edited_raise_without_its_audit_entry_counts_as_masked(tmp_path, capsys):
    state = tmp_path / ".netconverter"
    state.mkdir()
    (state / "privacy.json").write_text(json.dumps({"version": 1, "level": "full", "sections": []}))
    assert exposure.load(tmp_path).level == "masked"
    assert "audit" in capsys.readouterr().err


def test_lower_is_the_minimum():
    E = exposure.Exposure
    assert exposure.lower(E("full"), E("masked")) == E("masked")
    assert exposure.lower(E("none"), E("full")) == E("none")
    assert exposure.lower(E("selected", ("nat", "routes")), E("full")) == E("selected", ("nat", "routes"))
    assert exposure.lower(E("selected", ("nat", "routes")), E("selected", ("nat",))) == E("selected", ("nat",))
    assert exposure.lower(E("full"), E("selected")) == E("selected", ())
    assert exposure.normalize("strict") == "masked" and exposure.normalize("full") == "full"


# -- never through MCP --------------------------------------------------------

def test_no_mcp_tool_can_change_the_level(tmp_path):
    bridge, _ = bridge_at(tmp_path, "masked")
    server = StdioServer(bridge)
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    for tool in tools:
        text = json.dumps(tool).lower()
        assert "privacy" not in tool["name"] and "level" not in tool["name"]
        assert "set_level" not in text and "exposure" not in tool["name"]
    for name, arguments in (("privacy_level", {"level": "full"}), ("set_level", {"level": "full"}),
                            ("account", {"level": "full"}), ("download", {"job_id": "j", "dest_dir": ".netconverter"})):
        reply = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": name, "arguments": arguments}})
        assert reply["result"]["isError"] is True
    assert exposure.load(tmp_path).level == "masked"
    assert not exposure.audit_path(tmp_path).exists()


def test_the_audit_log_is_never_reachable_through_mcp(tmp_path):
    exposure.set_level(tmp_path, "none", interactive=False)
    bridge, _ = bridge_at(tmp_path, "none")
    for path in (".netconverter/privacy-audit.jsonl", str(exposure.audit_path(tmp_path)),
                 ".netconverter/privacy.json"):
        result = bridge.call("submit_file", {"path": path, "source_vendor": "cisco_asa",
                                             "target_vendor": "palo_alto_set"})
        assert result["isError"] is True and "invalid_path" in result["content"][0]["text"]


def test_a_bridge_process_cannot_raise_the_level(tmp_path, monkeypatch):
    """The MCP bridge runs on a pipe: a raise from there is refused like any non-TTY raise."""
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(exposure.ExposureError):
        exposure.set_level(tmp_path, "full")  # interactive defaults to "is stdin/stdout a TTY"


def test_the_bridge_follows_a_lowered_workspace_level_mid_session(tmp_path):
    server = JobServer()
    remote = RemoteMCP("https://api.example/mcp/v1/", StaticCredential("REMOTE_TOKEN"),
                       transport=httpx.MockTransport(server), view_mode="masked")
    bridge = Bridge(tmp_path, "https://api.example/external/v1", StaticCredential("nck_synthetic"), remote,
                    transport=httpx.MockTransport(QuickServer()), level="full", workspace_level=True)
    assert bridge.exposure.level == "masked"  # the workspace default caps --full
    exposure.set_level(tmp_path, "none", interactive=False)
    result = bridge.call("get_report", {"job_id": "j"})
    assert NAME not in json.dumps(result)
    assert server.requests[-1].headers["X-NetConverter-View"] == "none"
