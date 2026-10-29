"""#12 (client half): the bridge proxies the server's guided-mapping tools (aws#774).

The server asks decision-only questions with every configuration name as a token,
validates answers and queues a re-conversion. The bridge lists the three tools in
both views, refuses them at level `none` (questions need name tokens), and asks the
user in the client's own dialog before an apply queues a new conversion.
"""

import io
import json

import httpx

from netconverter_cli.api import StaticCredential
from netconverter_cli.mcp_server import (MAPPING_TOOLS, REMOTE_TOOLS_DEFAULT, REMOTE_TOOLS_STRICT, Bridge,
                                         StdioServer)
from netconverter_cli.remote_mcp import RemoteMCP
from tests.test_mcp import QuickServer

QUESTIONS = {"tool": "get_mapping_questions", "success": True, "data": {
    "questions": [{"decision_id": "zone:<name:zone-a1b2>", "options": ["<name:zone-a1b2>", "trust"],
                   "recommended": "trust", "reason": "inside interface"}],
    "counts": {"questions": 1}}}


class MappingServer:
    TOOLS = ("get_account", "get_report", "get_mapping_questions", "validate_mapping", "apply_mapping_answers")

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        method, params = message["method"], message.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "r"}}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": "d", "inputSchema": {"type": "object"}}
                                for n in self.TOOLS]}
        else:
            name = params["name"]
            payload = ({"tool": name, "success": True, "data": {"view_mode": "strict"}} if name == "get_account"
                       else {"tool": name, "success": True, "data": {"new_job_id": "tra_new", "status": "queued"}}
                       if name == "apply_mapping_answers" else QUESTIONS)
            result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                      "structuredContent": payload, "isError": False}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def calls(self):
        return [json.loads(r.content)["params"]["name"] for r in self.requests
                if json.loads(r.content).get("method") == "tools/call"]


def bridge_at(tmp_path, level):
    server = MappingServer()
    remote = RemoteMCP("https://api.example/mcp/v1/", StaticCredential("REMOTE_TOKEN"),
                       transport=httpx.MockTransport(server), view_mode=level)
    bridge = Bridge(tmp_path, "https://api.example/external/v1", StaticCredential("nck_synthetic"), remote,
                    transport=httpx.MockTransport(QuickServer()), level=level)
    return bridge, server


ANSWERS = {"answers": [{"decision_id": "zone:<name:zone-a1b2>", "value": "trust"}]}


def test_mapping_tools_are_proxied_in_both_views():
    assert MAPPING_TOOLS == {"get_mapping_questions", "validate_mapping", "apply_mapping_answers"}
    assert MAPPING_TOOLS <= REMOTE_TOOLS_STRICT <= REMOTE_TOOLS_DEFAULT


def test_masked_level_lists_and_calls_the_questions_with_tokens(tmp_path):
    bridge, server = bridge_at(tmp_path, "masked")
    assert MAPPING_TOOLS <= {t["name"] for t in bridge.list_tools()}
    result = bridge.call("get_mapping_questions", {"job_id": "tra_0123456789abcdef"})
    assert result["isError"] is False, result
    assert "<name:zone-a1b2>" in json.dumps(result["structuredContent"])
    assert server.calls()[-1] == "get_mapping_questions"  # after the view check (get_account)


def test_level_none_refuses_mapping_without_a_network_call(tmp_path):
    bridge, server = bridge_at(tmp_path, "none")
    result = bridge.call("get_mapping_questions", {"job_id": "tra_0123456789abcdef"})
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["error"] == "level_none" and "netconverter privacy level masked" in body["message"]
    assert "get_mapping_questions" not in server.calls()


def test_declined_apply_sends_nothing(tmp_path):
    bridge, server = bridge_at(tmp_path, "masked")
    seen = []
    bridge.confirm_apply = lambda details: seen.append(details) or "decline"
    result = bridge.call("apply_mapping_answers", {"job_id": "tra_0123456789abcdef", **ANSWERS})
    body = json.loads(result["content"][0]["text"])
    assert result["isError"] is True and body["error"] == "apply_declined"
    assert seen == [{"job_id": "tra_0123456789abcdef", "answers": 1}]
    assert "apply_mapping_answers" not in server.calls()


def test_accepted_apply_reaches_the_server(tmp_path):
    bridge, server = bridge_at(tmp_path, "masked")
    bridge.confirm_apply = lambda details: "accept"
    result = bridge.call("apply_mapping_answers", {"job_id": "tra_0123456789abcdef", **ANSWERS})
    assert result["isError"] is False, result
    assert server.calls()[-1] == "apply_mapping_answers"


def test_stdio_asks_the_client_before_apply_and_honours_a_decline(tmp_path):
    bridge, server = bridge_at(tmp_path, "masked")
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {"elicitation": {"form": {}}}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "apply_mapping_answers", "arguments": {"job_id": "tra_0123456789abcdef", **ANSWERS}}},
        {"jsonrpc": "2.0", "id": "nc-elicit-1", "result": {"action": "decline"}},
    ]
    out = io.StringIO()
    StdioServer(bridge).serve(io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n"), out)
    sent = [json.loads(line) for line in out.getvalue().splitlines()]
    ask = next(m for m in sent if m.get("method") == "elicitation/create")
    assert "re-conversion" in ask["params"]["message"] or "new conversion" in ask["params"]["message"]
    reply = next(m for m in sent if m.get("id") == 2)
    assert reply["result"]["isError"] is True
    assert json.loads(reply["result"]["content"][0]["text"])["error"] == "apply_declined"
    assert "apply_mapping_answers" not in server.calls()
