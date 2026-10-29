"""#19: on a full-API credential the guided app offers the Advanced and Zone screens.

Driven through Textual's harness against a mocked full External API; the
submitted request body must carry the chosen settings as a YAML v2 document
(job_options maps them), never as flat keys the server would ignore.
"""
import json

import httpx
import pytest
from textual.widgets import Input, OptionList, RichLog

from netconverter_cli.api import ExternalClient, StaticCredential
from netconverter_cli.controller import Controller
from netconverter_cli.tui import Terminal

SERVER = "https://api.netconverter.ai/external/v1"
FORTI = 'config system global\n    set hostname "SYNTHETIC-FW"\nend\nconfig firewall address\nend\n'
CAPS = {
    "job_types": ["convert", "validate", "optimize"],
    "vendors": [
        {"code": "fortinet", "name": "Fortinet FortiGate", "device_type": "firewall",
         "roles": ["source", "target"], "input": "text"},
        {"code": "palo_alto_xml", "name": "Palo Alto (XML)", "device_type": "firewall",
         "roles": ["source", "target"], "input": "text"},
        {"code": "palo_alto_panorama", "name": "Palo Alto Panorama", "device_type": "firewall",
         "roles": ["target"], "input": "text"},
        {"code": "cisco_asa", "name": "Cisco ASA", "device_type": "firewall", "roles": ["source"], "input": "text"},
    ],
    "paths": [{"source": s, "target": t, "device_type": "firewall"} for s, t in [
        ("cisco_asa", "fortinet"), ("cisco_asa", "palo_alto_xml"), ("cisco_asa", "palo_alto_panorama"),
        ("fortinet", "palo_alto_xml")]],
    "limits": {"max_config_bytes": 5 * 1024 * 1024},
}


class FullAPI:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/external/v1/")
        env = lambda data: httpx.Response(200, json={"success": True, "data": data})  # noqa: E731
        if path == "me":
            return env({"tenant_id": "t", "job_types": CAPS["job_types"]})
        if path == "capabilities":
            return env(CAPS)
        if path == "jobs" and request.method == "POST":
            return env({"job_id": "tra_0123456789ab", "status": "queued"})
        if path.startswith("jobs/"):
            return env({"job_id": path.split("/")[1], "status": "queued"})
        return httpx.Response(404, json={})

    def posts(self):
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


async def settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


async def choose(app, pilot, value):
    """Pick the choice whose value is ``value`` (by value, not by position)."""
    values = [v for _, v in app.choice_values]
    assert value in values, (app.question, app.choice_values)
    app.query_one(OptionList).highlighted = values.index(value)
    await pilot.press("enter")
    await settle(app, pilot)


async def enter(app, pilot, text):
    app.query_one(Input).value = text
    await pilot.press("enter")
    await settle(app, pilot)


def history(app):
    return "\n".join(line.text for line in app.query_one(RichLog).lines)


async def open_convert(app, pilot, filename, vendor):
    await settle(app, pilot)
    app.dispatch("/convert")
    await settle(app, pilot)
    await choose(app, pilot, next(v for _, v in app.choice_values if getattr(v, "name", None) == filename))
    await choose(app, pilot, vendor)


@pytest.fixture
def full_api(tmp_path):
    (tmp_path / "edge-fw.conf").write_text(FORTI)
    (tmp_path / "asa.cfg").write_text("ASA Version 9.16\nhostname SYNTHETIC-ASA\n")
    server = FullAPI()
    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(server))
    return Controller(tmp_path, client), server


@pytest.mark.asyncio
async def test_full_api_offers_advanced_and_zone_screens_and_sends_yaml_v2(full_api):
    controller, server = full_api
    app = Terminal(controller)
    async with app.run_test(size=(110, 36)) as pilot:
        await open_convert(app, pilot, "edge-fw.conf", "fortinet")
        assert app.question == "Convert Fortinet FortiGate to"
        await choose(app, pilot, "palo_alto_xml")
        assert app.question == "Conversion settings"  # no longer straight to review
        await choose(app, pilot, True)  # customize
        assert app.question == "Remove unused objects during validated conversion?"
        await choose(app, pilot, True)
        assert app.question == "App-ID"
        await choose(app, pilot, True)
        await choose(app, pilot, "dual_stack")
        await choose(app, pilot, False)  # security profiles: disable
        await choose(app, pilot, None)  # log all rules: server default
        await choose(app, pilot, "explicit-deny-all")
        assert "profile group" in app.question.lower()
        await enter(app, pilot, "PG-SYNTHETIC")
        assert "Zone mapping" in app.question
        await enter(app, pilot, '{"inside": "Trust", "outside": "Untrust"}')
        assert app.question == "Submit this job?"
        assert not server.posts()  # nothing leaves before the review's Submit
        await choose(app, pilot, True)
        body = server.posts()[-1]
    assert body["source_vendor"] == "fortinet" and body["target_vendor"] == "palo_alto_xml"
    flat = {"remove_unused_objects", "enable_appid", "app_id_implementation", "add_security_profiles",
            "implicit_deny", "default_profile_group", "zone_mapping", "log_all_rules"}
    assert not flat & set(body)
    document = body["yaml_v2"]
    assert document["meta"] == {"schema_version": "2.0"}
    assert document["zone_mapping"] == {"inside": "Trust", "outside": "Untrust"}
    assert document["options"] == {"remove_unused_objects": True, "enable_appid": True,
                                   "app_id_implementation": "dual_stack", "add_security_profiles": False,
                                   "implicit_deny": "explicit-deny-all"}
    assert document["pa_target"] == {"default_profile_group": "PG-SYNTHETIC"}


@pytest.mark.asyncio
async def test_full_api_non_palo_target_skips_palo_only_settings(full_api):
    controller, server = full_api
    app = Terminal(controller)
    async with app.run_test(size=(110, 36)) as pilot:
        await open_convert(app, pilot, "asa.cfg", "cisco_asa")
        await choose(app, pilot, "fortinet")
        await choose(app, pilot, True)  # customize
        await choose(app, pilot, False)  # keep objects
        for _ in range(5):
            await choose(app, pilot, None)  # every advanced setting: server default
        assert "Zone mapping" in app.question  # no Palo Alto profile-group question
        await enter(app, pilot, '{"inside": "lan"}')
        await choose(app, pilot, True)
        body = server.posts()[-1]
    assert body["target_vendor"] == "fortinet"
    assert body["yaml_v2"]["zone_mapping"] == {"inside": "lan"}
    assert body["yaml_v2"]["options"] == {"remove_unused_objects": False}
    assert "pa_target" not in body["yaml_v2"]


@pytest.mark.asyncio
async def test_full_api_panorama_scope_is_optional_and_reaches_output_platform(full_api):
    controller, server = full_api
    app = Terminal(controller)
    async with app.run_test(size=(110, 36)) as pilot:
        await open_convert(app, pilot, "asa.cfg", "cisco_asa")
        await choose(app, pilot, "palo_alto_panorama")
        await choose(app, pilot, True)  # customize
        assert "device group" in app.question.lower()
        await enter(app, pilot, "DG-SYNTHETIC")
        assert "template" in app.question.lower()
        await enter(app, pilot, "")  # Enter: server default
        await choose(app, pilot, False)
        for _ in range(5):
            await choose(app, pilot, None)
        await enter(app, pilot, "")  # profile group: preset
        await enter(app, pilot, "")  # zone mapping: none
        await choose(app, pilot, True)
        body = server.posts()[-1]
    assert body["yaml_v2"]["output_platform"] == {"panorama_device_group": "DG-SYNTHETIC"}
    assert "zone_mapping" not in body["yaml_v2"]


@pytest.mark.asyncio
async def test_full_api_defaults_send_no_decisions_document(full_api):
    controller, server = full_api
    app = Terminal(controller)
    async with app.run_test(size=(110, 36)) as pilot:
        await open_convert(app, pilot, "edge-fw.conf", "fortinet")
        await choose(app, pilot, "palo_alto_xml")
        await choose(app, pilot, False)  # use NetConverter's defaults
        assert app.question == "Submit this job?"
        await choose(app, pilot, True)
        body = server.posts()[-1]
    assert "yaml_v2" not in body
