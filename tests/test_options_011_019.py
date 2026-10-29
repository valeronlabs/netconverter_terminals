"""#11 options allowlist on every submit path, #19 guided settings the server honours."""
import json

import httpx
import pytest

from netconverter_cli import cli
from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.controller import Controller
from netconverter_cli.job_options import OptionsError, check, external_body
from netconverter_cli.mcp_server import Bridge

SERVER = "https://api.netconverter.ai/external/v1"
CONFIG = b"hostname SYNTHETIC-ASA\nobject network WEB\n host 192.0.2.10\n"


def envelope(data):
    return httpx.Response(200, json={"success": True, "data": data})


class External:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/external/v1/")
        if path == "me":
            return envelope({"tenant_id": "t", "job_types": ["convert", "validate", "optimize"]})
        if path == "capabilities":
            return envelope({"job_types": ["convert", "validate", "optimize"], "vendors": [
                {"code": "cisco_asa", "name": "Cisco ASA", "device_type": "firewall", "roles": ["source"]},
                {"code": "palo_alto_xml", "name": "Palo Alto (XML)", "device_type": "firewall",
                 "roles": ["source", "target"]},
                {"code": "fortinet", "name": "FortiGate", "device_type": "firewall", "roles": ["source", "target"]}],
                "paths": [], "limits": {"max_config_bytes": 5242880}})
        if path == "jobs" and request.method == "POST":
            return envelope({"job_id": "tra_0123456789ab", "status": "queued"})
        return httpx.Response(404, json={})

    def posts(self):
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "asa.cfg").write_bytes(CONFIG)
    return tmp_path


def bridge(workspace, server):
    return Bridge(workspace, SERVER, StaticCredential("nck_synthetic"), transport=httpx.MockTransport(server))


def submit(b, **arguments):
    result = b.call("submit_file", {"path": "asa.cfg", "source_vendor": "cisco_asa", **arguments})
    return result["isError"], json.loads(result["content"][0]["text"])


# -- #11: the bridge's options allowlist ---------------------------------------


@pytest.mark.parametrize("options,named", [
    ({"source_config": "x"}, "source_config"),
    ({"technology": "router"}, "technology"),
    ({"manual_mappings": []}, "manual_mappings"),
    ({"yaml_v2": "zone_mapping: {}"}, "yaml_v2"),
    ({"job_type": "optimize"}, "job_type"),
    ({"surprise": 1, "another": True}, "another, surprise"),
])
def test_mcp_refuses_reserved_and_unknown_options_before_upload(workspace, options, named):
    server = External()
    failed, payload = submit(bridge(workspace, server), target_vendor="palo_alto_xml", options=options)
    assert failed and payload["error"] == "invalid_arguments"
    assert named in payload["message"]
    assert not server.posts()


def test_mcp_refuses_a_wrongly_typed_option(workspace):
    server = External()
    failed, payload = submit(bridge(workspace, server), target_vendor="palo_alto_xml",
                             options={"enable_appid": "yes"})
    assert failed and "enable_appid must be true or false" in payload["message"]
    assert not server.posts()


def test_mcp_allowed_options_pass_through_unchanged(workspace):
    server = External()
    failed, _ = submit(bridge(workspace, server), job_type="optimize",
                       options={"optimization_options": {"enable_ai_fixes": False},
                                "selected_device_groups": ["DG-EDGE"]})
    assert not failed
    body = server.posts()[-1]
    assert body["optimization_options"] == {"enable_ai_fixes": False}
    assert body["selected_device_groups"] == ["DG-EDGE"]


def test_mcp_options_schema_is_enum_keyed_and_typed(workspace):
    tools = {t["name"]: t for t in Bridge(workspace, SERVER).list_tools()}
    schema = tools["submit_file"]["inputSchema"]["properties"]["options"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["routing_engine"]["enum"] == ["vr", "lr"]
    assert schema["properties"]["enable_appid"] == {"type": "boolean"}
    assert not {"yaml_v2", "source_config", "technology", "target_vendor"} & set(schema["properties"])


# -- #19: guided settings reach the server as yaml_v2 ---------------------------


GUIDED = {"remove_unused_objects": True, "enable_appid": True, "app_id_implementation": "dual_stack",
          "add_security_profiles": False, "log_all_rules": True, "implicit_deny": "explicit-deny-all",
          "default_profile_group": "PG-DEFAULT", "zone_mapping": {"inside": "Trust", "outside": "Untrust"},
          "panos_target_version": "10.1", "routing_engine": "vr"}


def test_guided_settings_become_a_yaml_v2_document(workspace):
    server = External()
    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(server))
    controller = Controller(workspace, client)
    controller.select("asa.cfg", "cisco_asa")
    controller.submit("convert", {"target_vendor": "palo_alto_xml", **GUIDED})
    body = server.posts()[-1]
    assert not set(GUIDED) & set(body)  # nothing the server would silently ignore
    document = body["yaml_v2"]
    assert document["zone_mapping"] == {"inside": "Trust", "outside": "Untrust"}
    assert document["pa_target"] == {"panos_target_version": "10.1", "routing_engine": "vr",
                                     "default_profile_group": "PG-DEFAULT"}
    assert document["options"] == {"remove_unused_objects": True, "enable_appid": True,
                                   "app_id_implementation": "dual_stack", "add_security_profiles": False,
                                   "log_all_rules": True, "implicit_deny": "explicit-deny-all"}
    assert document["meta"] == {"schema_version": "2.0"}
    assert body["target_vendor"] == "palo_alto_xml" and body["source_vendor"] == "cisco_asa"


def test_panorama_scope_goes_to_output_platform():
    body = external_body({"panorama_device_group": "DG", "panorama_template": "TPL"}, "convert",
                         "palo_alto_panorama")
    assert body["yaml_v2"]["output_platform"] == {"panorama_device_group": "DG", "panorama_template": "TPL"}


@pytest.mark.parametrize("options,target,job_type,words", [
    ({"pipeline_mode": "like_for_like"}, "palo_alto_xml", "convert", "pilot keys"),
    ({"routing_engine": "lr"}, "fortinet", "convert", "Palo Alto target"),
    ({"panorama_template": "T"}, "palo_alto_xml", "convert", "palo_alto_panorama"),
    ({"zone_mapping": {"inside": "Trust"}}, None, "validate", "does not apply to validate"),
    ({"optimization_options": {"enable_rag": True}}, None, "validate", "does not apply"),
    ({"zone_mapping": {"inside": 7}}, "palo_alto_xml", "convert", "zone_mapping must be"),
    ({"routing_engine": "logical"}, "palo_alto_xml", "convert", "one of vr, lr"),
    ({"yaml_v2": "pa_target: {}", "routing_engine": "lr"}, "palo_alto_xml", "convert", "inside the yaml_v2"),
])
def test_settings_the_server_would_ignore_are_refused(options, target, job_type, words):
    with pytest.raises(OptionsError, match=words):
        external_body(options, job_type, target)


def test_a_yaml_v2_object_is_merged_and_conflicts_refused():
    body = external_body({"yaml_v2": {"pa_target": {"model": "PA-3220"}}, "routing_engine": "lr"},
                         "convert", "palo_alto_xml")
    assert body["yaml_v2"]["pa_target"] == {"model": "PA-3220", "routing_engine": "lr"}
    with pytest.raises(OptionsError, match="conflicts"):
        external_body({"yaml_v2": {"pa_target": {"routing_engine": "vr"}}, "routing_engine": "lr"},
                      "convert", "palo_alto_xml")
    assert external_body({"yaml_v2": "zone_mapping: {}"}, "convert", "palo_alto_xml") == {
        "yaml_v2": "zone_mapping: {}"}


def test_pilot_keys_keep_their_flat_settings():
    flat = {"pipeline_mode": "like_for_like", "routing_engine": "lr", "zone_mapping": {"inside": "Trust"}}
    assert check(flat, "convert", "palo_alto_set", profile="quick") == flat
    with pytest.raises(OptionsError, match="full API"):
        check({"selected_device_groups": ["DG"]}, "convert", "palo_alto_set", profile="quick")


def test_cli_names_an_unknown_option_and_uploads_nothing(workspace, monkeypatch, capsys):
    server = External()
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_synthetic")
    real = cli.open_client
    monkeypatch.setattr(cli, "open_client", lambda credential, srv: real(credential, srv,
                                                                          transport=httpx.MockTransport(server)))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--workspace", str(workspace), "--server", SERVER, "convert", "asa.cfg", "--vendor",
                  "cisco_asa", "--to", "palo_alto_xml", "--options", '{"enable_app_id": true}'])
    assert exc.value.code == 4  # refused input (docs/COMMANDS.md exit codes)
    captured = capsys.readouterr()
    assert "enable_app_id" in captured.err + captured.out
    assert not server.posts()
