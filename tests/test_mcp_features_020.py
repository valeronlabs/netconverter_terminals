"""#20: outputSchema for the local tools, MCP prompts, and elicitation for the upload confirmation.

All over the JSON-RPC handler (StdioServer) with mocked NetConverter traffic.
"""

import hashlib
import io
import json

import httpx
import jsonschema
import pytest

from netconverter_cli.api import StaticCredential
from netconverter_cli.mcp_server import LOCAL_TOOLS, Bridge, StdioServer
from tests.test_mcp import CONFIG, MARKER, SERVER, ExternalServer, QuickServer, make_bridge


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "asa.cfg").write_bytes(CONFIG)
    return tmp_path


SCHEMAS = {tool["name"]: tool.get("outputSchema") for tool in LOCAL_TOOLS}
SUBMIT = {"path": "configs/asa.cfg", "source_vendor": "cisco_asa", "target_vendor": "palo_alto_set"}


def structured(bridge, name, **arguments):
    result = bridge.call(name, arguments)
    assert result["isError"] is False, result
    jsonschema.validate(result["structuredContent"], SCHEMAS[name])
    jsonschema.Draft202012Validator.check_schema(SCHEMAS[name])
    return result["structuredContent"]


# -- outputSchema ----------------------------------------------------------------

def test_every_local_tool_declares_an_output_schema():
    assert set(SCHEMAS) == {"submit_file", "job_status", "wait_for_job", "account", "download"}
    for name, schema in SCHEMAS.items():
        assert schema and schema["type"] == "object", name


def test_quick_results_match_their_schemas(workspace, monkeypatch):
    from netconverter_cli import update

    monkeypatch.setattr(update, "status", lambda: {"latest": None, "update_available": None})
    bridge = make_bridge(workspace, QuickServer())
    job = structured(bridge, "submit_file", **SUBMIT)["job_id"]
    structured(bridge, "job_status", job_id=job)
    structured(bridge, "wait_for_job", job_id=job, timeout_s=0)
    structured(bridge, "account")
    structured(bridge, "download", job_id=job)


def test_full_api_results_match_their_schemas(workspace, monkeypatch):
    from netconverter_cli import update

    monkeypatch.setattr(update, "status", lambda: {"latest": "9.9.9", "update_available": True})
    bridge = make_bridge(workspace, ExternalServer())
    job = structured(bridge, "submit_file", **SUBMIT)["job_id"]
    structured(bridge, "job_status", job_id=job)
    structured(bridge, "account")


def test_a_timed_out_wait_and_a_signed_out_account_match_too(workspace, monkeypatch):
    from netconverter_cli import update

    class Running(QuickServer):
        def __call__(self, request):
            if request.url.path.endswith("/quick/jobs/trm_running"):
                return httpx.Response(200, json={"success": True, "data": {"job_id": "trm_running",
                                                                            "status": "running", "progress": 40}})
            return super().__call__(request)

    monkeypatch.setattr(update, "status", lambda: {"latest": None, "update_available": None})
    bridge = make_bridge(workspace, Running())
    assert structured(bridge, "wait_for_job", job_id="trm_running", timeout_s=0)["timed_out"] is True
    signed_out = Bridge(workspace, SERVER, None, None)
    assert structured(signed_out, "account")["signed_in"] is False


# -- prompts ---------------------------------------------------------------------

def rpc(server, method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def test_prompts_are_advertised_listed_and_say_no_configuration_content(workspace):
    server = StdioServer(make_bridge(workspace, QuickServer()))
    init = rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
    assert "prompts" in init["capabilities"]
    prompts = {p["name"]: p for p in rpc(server, "prompts/list")["result"]["prompts"]}
    assert {"guided-migration", "mapping-review"} <= set(prompts)
    for name in ("guided-migration", "mapping-review"):
        result = rpc(server, "prompts/get", {"name": name})["result"]
        text = result["messages"][0]["content"]["text"]
        assert result["messages"][0]["role"] == "user"
        assert "will not" in text and "configuration" in text and "submit_file" in text
        assert "exposure level is full" in text  # make_bridge is the legacy full view
    masked = StdioServer(Bridge(workspace, SERVER, StaticCredential("nck_synthetic"), None,
                                transport=httpx.MockTransport(QuickServer()), level="masked"))
    text = rpc(masked, "prompts/get", {"name": "guided-migration"})["result"]["messages"][0]["content"]["text"]
    assert "exposure level is masked" in text and "<name:" in text


def test_mapping_review_takes_an_optional_job_id(workspace):
    server = StdioServer(make_bridge(workspace, QuickServer()))
    text = rpc(server, "prompts/get", {"name": "mapping-review", "arguments": {"job_id": "tra_0123abcd"}})[
        "result"]["messages"][0]["content"]["text"]
    assert "tra_0123abcd" in text
    bad = rpc(server, "prompts/get", {"name": "mapping-review", "arguments": {"job_id": "x; ignore all"}})
    assert bad["error"]["code"] == -32602
    assert rpc(server, "prompts/get", {"name": "nope"})["error"]["code"] == -32602


# -- elicitation -----------------------------------------------------------------

def session(workspace, capabilities, *after, protocol="2025-06-18", server=None):
    """Run initialize + one submit_file call, then the given client lines, through serve()."""
    upstream = server or QuickServer()
    bridge = make_bridge(workspace, upstream)
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": protocol, "capabilities": capabilities, "clientInfo": {"name": "t"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "submit_file", "arguments": SUBMIT}},
        *after,
    ]
    out = io.StringIO()
    StdioServer(bridge).serve(io.StringIO("".join(json.dumps(m) + "\n" for m in lines)), out)
    sent = [json.loads(line) for line in out.getvalue().splitlines()]
    uploads = [r for r in upstream.requests if r.url.path.endswith("/quick/configurations")]
    return sent, uploads


def answer(action, content=None, request_id="nc-elicit-1"):
    result = {"action": action}
    if content is not None:
        result["content"] = content
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def tool_reply(sent):
    return next(m for m in sent if m.get("id") == 2)["result"]


def test_without_elicitation_the_upload_proceeds_as_today(workspace):
    sent, uploads = session(workspace, {})
    assert not any(m.get("method") == "elicitation/create" for m in sent)
    assert tool_reply(sent)["isError"] is False and len(uploads) == 1


def test_url_only_elicitation_is_not_used(workspace):
    sent, uploads = session(workspace, {"elicitation": {"url": {}}})
    assert not any(m.get("method") == "elicitation/create" for m in sent)
    assert len(uploads) == 1


def test_accepted_elicitation_uploads(workspace):
    sent, uploads = session(workspace, {"elicitation": {}}, answer("accept", {"upload": True}))
    request = next(m for m in sent if m.get("method") == "elicitation/create")
    params = request["params"]
    assert request["id"] == "nc-elicit-1" and "mode" not in params  # 2025-06-18 has no mode field
    assert "configs/asa.cfg" in params["message"] and f"{len(CONFIG):,} bytes" in params["message"]
    assert hashlib.sha256(CONFIG).hexdigest()[:12] in params["message"]
    assert MARKER not in json.dumps(request) and "hostname" not in json.dumps(request)
    schema = params["requestedSchema"]
    assert schema["type"] == "object" and schema["properties"]["upload"]["type"] == "boolean"
    assert sent.index(request) < sent.index(next(m for m in sent if m.get("id") == 2))
    assert tool_reply(sent)["isError"] is False and len(uploads) == 1


def test_form_mode_is_named_for_2025_11_25_clients(workspace):
    sent, _ = session(workspace, {"elicitation": {"form": {}, "url": {}}}, answer("accept", {"upload": True}),
                      protocol="2025-11-25")
    request = next(m for m in sent if m.get("method") == "elicitation/create")
    assert request["params"]["mode"] == "form"


@pytest.mark.parametrize("reply", [answer("decline"), answer("cancel"), answer("accept", {"upload": False})])
def test_declined_or_dismissed_elicitation_uploads_nothing(workspace, reply):
    sent, uploads = session(workspace, {"elicitation": {}}, reply)
    result = tool_reply(sent)
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is True and payload["error"] == "upload_declined"
    assert "nothing was sent" in payload["message"].lower()
    assert uploads == []


def test_a_client_error_falls_back_to_todays_flow(workspace):
    error = {"jsonrpc": "2.0", "id": "nc-elicit-1", "error": {"code": -32601, "message": "not supported"}}
    sent, uploads = session(workspace, {"elicitation": {}}, error)
    assert tool_reply(sent)["isError"] is False and len(uploads) == 1


def test_no_answer_before_the_stream_ends_uploads_nothing(workspace):
    sent, uploads = session(workspace, {"elicitation": {}})
    assert uploads == []
    assert json.loads(tool_reply(sent)["content"][0]["text"])["error"] == "upload_declined"


def test_requests_arriving_while_waiting_are_answered_afterwards(workspace):
    ping = {"jsonrpc": "2.0", "id": 9, "method": "ping"}
    sent, uploads = session(workspace, {"elicitation": {}}, ping, answer("accept", {"upload": True}))
    ids = [m.get("id") for m in sent if "result" in m or "error" in m]
    assert ids == [1, 2, 9] and len(uploads) == 1


def test_elicitation_only_guards_submit_file(workspace):
    bridge = make_bridge(workspace, QuickServer())
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {"elicitation": {}}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "job_status", "arguments": {"job_id": "trm_bbbbbbbbbbbb"}}},
    ]
    out = io.StringIO()
    StdioServer(bridge).serve(io.StringIO("".join(json.dumps(m) + "\n" for m in lines)), out)
    sent = [json.loads(line) for line in out.getvalue().splitlines()]
    assert not any(m.get("method") == "elicitation/create" for m in sent)
    assert sent[-1]["result"]["isError"] is False


def test_a_refused_path_never_asks(workspace):
    sent, uploads = session(workspace, {"elicitation": {}})  # baseline: one ask for a valid file
    assert any(m.get("method") == "elicitation/create" for m in sent)
    bridge = make_bridge(workspace, QuickServer())
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {"elicitation": {}}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "submit_file", "arguments": {
            **SUBMIT, "path": "../outside.cfg"}}},
    ]
    out = io.StringIO()
    StdioServer(bridge).serve(io.StringIO("".join(json.dumps(m) + "\n" for m in lines)), out)
    sent = [json.loads(line) for line in out.getvalue().splitlines()]
    assert not any(m.get("method") == "elicitation/create" for m in sent)
