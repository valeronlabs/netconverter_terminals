"""#22: a refused vendor code names the server's reason and the valid codes.

Server traffic is mocked with httpx.MockTransport; the 422 body shape is the
External API's envelope (``error.code`` + ``error.message``).
"""

import json

import httpx
import pytest

from netconverter_cli import cli
from netconverter_cli.api import APIError, ExternalClient, StaticCredential

SERVER = "https://api.example/external/v1"
REASON = "unknown source_vendor 'auto'; valid: ['cisco_asa', 'juniper_junos_router']"
VENDORS = [{"code": "cisco_asa", "name": "Cisco ASA", "device_type": "firewall", "roles": ["source"]},
           {"code": "juniper_junos_router", "name": "Juniper", "device_type": "router",
            "roles": ["source", "target"]},
           {"code": "palo_alto_set", "name": "Palo Alto", "device_type": "firewall", "roles": ["target"]}]


class VendorServer:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/external/v1/")
        if path == "me":
            return httpx.Response(200, json={"success": True, "data": {"job_types": ["validate"]}})
        if path == "capabilities":
            return httpx.Response(200, json={"success": True, "data": {"vendors": VENDORS, "job_types": ["validate"]}})
        if path == "jobs" and request.method == "POST":
            return httpx.Response(422, json={"success": False, "request_id": "req_5c886ce2",
                                             "error": {"code": "unprocessable", "message": REASON}})
        return httpx.Response(404, json={})


def test_api_error_carries_the_server_message():
    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(VendorServer()))
    with pytest.raises(APIError) as info:
        client.submit_job({"source_vendor": "auto", "source_config": "x"}, "key")
    exc = info.value
    assert exc.status == 422 and exc.code == "unprocessable" and exc.request_id == "req_5c886ce2"
    assert exc.message == REASON
    assert REASON in str(exc) and "HTTP 422" in str(exc)


def test_mcp_tool_failure_carries_the_server_message():
    from netconverter_cli.mcp_server import _api_failure

    failure = _api_failure(APIError(422, "unprocessable", "req_1", message=REASON))
    assert failure.code == "unprocessable" and REASON in str(failure)


def test_validate_vendor_auto_is_refused_before_any_upload(tmp_path, monkeypatch, capsys):
    (tmp_path / "srx.conf").write_text("system { host-name synthetic; }\n")
    server = VendorServer()
    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(server))
    monkeypatch.setattr(cli, "open_client", lambda credential, url: (client, "external"))
    monkeypatch.setattr(cli, "get_secret", lambda *a, **k: "nck_synthetic")
    with pytest.raises(SystemExit) as info:
        cli.main(["--workspace", str(tmp_path), "--server", SERVER, "validate", "srx.conf", "--vendor", "auto"])
    assert info.value.code == 2  # a usage error (#9 exit codes)
    out = capsys.readouterr().err
    assert "'auto'" in out and "cisco_asa" in out and "juniper_junos_router" in out
    assert "palo_alto_set" not in out  # target-only codes are not offered as a source
    assert "netconverter capabilities" in out
    assert not [r for r in server.requests if r.method == "POST"]


def test_validate_with_a_server_refused_vendor_prints_the_reason(tmp_path, monkeypatch, capsys):
    """A code the local catalogue cannot judge still shows the server's message."""
    (tmp_path / "srx.conf").write_text("system { host-name synthetic; }\n")

    class NoVendorList(VendorServer):
        def __call__(self, request):
            if request.url.path.endswith("/capabilities"):
                self.requests.append(request)
                return httpx.Response(200, json={"success": True, "data": {"job_types": ["validate"]}})
            return super().__call__(request)

    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(NoVendorList()))
    monkeypatch.setattr(cli, "open_client", lambda credential, url: (client, "external"))
    monkeypatch.setattr(cli, "get_secret", lambda *a, **k: "nck_synthetic")
    with pytest.raises(SystemExit):
        cli.main(["--workspace", str(tmp_path), "--server", SERVER, "validate", "srx.conf", "--vendor", "auto"])
    out = capsys.readouterr().err  # errors go to stderr (#9)
    assert REASON in out
    assert json.loads(out.splitlines()[-1]) if out.splitlines()[-1].startswith("{") else True
