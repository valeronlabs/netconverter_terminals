"""#15: `netconverter mcp --strict` requests the server's strict view and enforces it locally.

The server's view mode comes from the admin grant today; the bridge asks for
`strict` on every remote request (X-NetConverter-View), reads the view in
force from `get_account`, reports it, and until the server honours the
request it refuses the configuration-content calls the server's strict mode
refuses and masks addresses in every remote result. Mocked transport only.
"""

import json

import httpx
import pytest

from netconverter_cli.api import StaticCredential
from netconverter_cli.mcp_server import Bridge, mask_addresses
from netconverter_cli.remote_mcp import RemoteMCP
from tests.test_mcp import LOCAL, QuickServer

TOOLS = ("list_jobs", "get_account", "get_evidence", "get_job_brief", "fetch", "get_report", "search")
LEAK = "name-server 10.10.0.53 ; iface 10.10.0.1/24 ; v6 2001:db8::1 ; peer 2001:db8:0:1::5/64"


class ViewServer:
    """Remote MCP whose get_account reports the grant's view mode; other tools echo a raw line."""

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
        elif method == "tools/call":
            name = params["name"]
            data = ({"view_mode": self.view_mode, "tier": "trial"} if name == "get_account"
                    else {"text": LEAK, "items": [{"line": LEAK}], "text_included": True})
            payload = {"tool": name, "success": True, "data": data, "error": None}
            result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                      "structuredContent": payload, "isError": False}
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"],
                                             "error": {"code": -32601, "message": "nope"}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def calls(self):
        return [json.loads(r.content)["params"]["name"] for r in self.requests
                if json.loads(r.content).get("method") == "tools/call"]


def strict_bridge(tmp_path, view_mode="default", strict=True):
    server = ViewServer(view_mode)
    remote = RemoteMCP("https://api.example/mcp/v1/", StaticCredential("REMOTE_TOKEN"),
                       transport=httpx.MockTransport(server), view_mode="strict" if strict else None)
    bridge = Bridge(tmp_path, "https://api.example/external/v1", StaticCredential("nck_synthetic"), remote,
                    transport=httpx.MockTransport(QuickServer()), strict=strict)
    return bridge, server


def text_of(result):
    return json.loads(result["content"][0]["text"])


def test_strict_asks_the_server_for_the_strict_view_on_every_request(tmp_path):
    bridge, server = strict_bridge(tmp_path)
    bridge.list_tools()
    bridge.call("get_report", {"job_id": "j"})
    # #13: the header carries the exposure level; the server serves masked as its strict view.
    assert server.requests and all(r.headers.get("X-NetConverter-View") == "masked" for r in server.requests)
    bridge, server = strict_bridge(tmp_path, strict=False)
    bridge.list_tools()
    assert server.requests and all("X-NetConverter-View" not in r.headers for r in server.requests)


def test_account_reports_the_view_in_force_not_the_flag(tmp_path, monkeypatch, capsys):
    from netconverter_cli import update

    monkeypatch.setattr(update, "status", lambda: {"latest": None, "update_available": None})
    bridge, _ = strict_bridge(tmp_path, view_mode="default")
    payload = text_of(bridge.call("account", {}))
    assert payload["strict_mode"] is True and payload["view_mode"] == "default"
    assert payload["strict_enforced_by"] == "client"
    err = capsys.readouterr().err
    assert "view mode" in err and "default" in err and "strict" in err  # one honest startup line
    bridge, _ = strict_bridge(tmp_path, view_mode="strict")
    payload = text_of(bridge.call("account", {}))
    assert payload["view_mode"] == "strict" and payload["strict_enforced_by"] == "server"
    assert "view mode" not in capsys.readouterr().err
    bridge, _ = strict_bridge(tmp_path, strict=False)
    payload = text_of(bridge.call("account", {}))
    assert payload["strict_mode"] is False and payload["view_mode"] == "default"
    assert payload["strict_enforced_by"] is None


@pytest.mark.parametrize("name,arguments", [
    ("get_evidence", {"job_id": "j", "section": "unparsed_lines"}),
    ("get_job_brief", {"job_id": "j", "focus": "target"}),
    ("fetch", {"id": "job:tra_1"}),
])
def test_strict_refuses_configuration_content_calls_locally(tmp_path, name, arguments):
    bridge, server = strict_bridge(tmp_path, view_mode="default")
    result = bridge.call(name, arguments)
    payload = text_of(result)
    assert result["isError"] is True and payload["error"] == "strict_mode"
    assert name not in server.calls()  # refused before any network call
    assert LEAK.split()[1] not in json.dumps(result)


def test_strict_still_allows_summaries_and_kb_fetch(tmp_path):
    bridge, server = strict_bridge(tmp_path, view_mode="default")
    assert bridge.call("fetch", {"id": "kb:doc_1"})["isError"] is False
    assert bridge.call("get_evidence", {"job_id": "j", "section": "digest"})["isError"] is False
    assert bridge.call("get_job_brief", {"job_id": "j", "focus": "evidence"})["isError"] is False
    assert server.calls() == ["get_account", "fetch", "get_evidence", "get_job_brief"]


def test_strict_masks_addresses_in_every_remote_result(tmp_path):
    bridge, _ = strict_bridge(tmp_path, view_mode="default")
    result = bridge.call("get_report", {"job_id": "j"})
    wire = json.dumps(result)
    for raw in ("10.10.0.53", "10.10.0.1/24", "2001:db8::1", "2001:db8:0:1::5/64"):
        assert raw not in wire
    data = result["structuredContent"]["data"]
    assert data["text"] == "name-server <ip> ; iface <cidr> ; v6 <ip> ; peer <cidr>"
    assert data["items"][0]["line"] == data["text"] and data["text_included"] is True
    assert text_of(result)["data"] == data
    # Without --strict the result is proxied as-is.
    bridge, _ = strict_bridge(tmp_path, strict=False)
    assert "10.10.0.53" in json.dumps(bridge.call("get_report", {"job_id": "j"}))


def test_mask_addresses_leaves_versions_and_times_alone():
    assert mask_addresses("PAN-OS 10.1.9 at 12:30:45, rule 3.2.1.0/24 ok") == \
        "PAN-OS 10.1.9 at 12:30:45, rule <cidr> ok"
    assert mask_addresses({"a": ["192.0.2.1", 5, None, {"b": "::1"}]}) == {"a": ["<ip>", 5, None, {"b": "<ip>"}]}


def test_tools_list_then_strict_call_asks_get_account_once(tmp_path):
    bridge, server = strict_bridge(tmp_path, view_mode="strict")
    names = [t["name"] for t in bridge.list_tools()]
    assert names == LOCAL + list(TOOLS)
    bridge.call("get_report", {"job_id": "j"})
    bridge.call("search", {"query": "x"})
    assert server.calls().count("get_account") == 1


def test_mcp_strict_hands_the_strict_view_request_to_the_remote_client(monkeypatch):
    from netconverter_cli import cli, mcp_server, remote_mcp

    seen = {}

    class FakeRemote:
        def __init__(self, url, credential, client_version=None, view_mode=None):
            seen["view_mode"] = view_mode

        def close(self):
            pass

    monkeypatch.delenv("NETCONVERTER_TRUSTED_HOSTS", raising=False)
    monkeypatch.setattr(cli, "_clerk_session", lambda: None)
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_synthetic")
    monkeypatch.setattr(remote_mcp, "RemoteMCP", FakeRemote)
    monkeypatch.setattr(mcp_server, "Bridge", lambda ws, server, rest, remote, **kw: seen.setdefault("strict", kw["strict"]))
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: None)
    cli.run_mcp(cli.parser().parse_args(["--server", "https://api.netconverter.ai/external/v1", "mcp", "--strict"]))
    assert seen == {"view_mode": "strict", "strict": True}
    seen.clear()
    # #11: strict is the default; the wider view needs --full.
    cli.run_mcp(cli.parser().parse_args(["--server", "https://api.netconverter.ai/external/v1", "mcp"]))
    assert seen == {"view_mode": "strict", "strict": True}
    seen.clear()
    cli.run_mcp(cli.parser().parse_args(["--server", "https://api.netconverter.ai/external/v1", "mcp", "--full"]))
    assert seen == {"view_mode": None, "strict": False}
