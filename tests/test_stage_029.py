"""#29: job_status / wait_for_job pass a stage through (stage_key first, else sanitised text)."""
import json

import httpx
import pytest

from netconverter_cli.api import StaticCredential
from netconverter_cli.mcp_server import Bridge, sanitize_stage

SERVER = "https://api.netconverter.ai/external/v1"
JOB = "tra_0123456789ab"


def envelope(data):
    return httpx.Response(200, json={"success": True, "data": data})


class Server:
    def __init__(self, job):
        self.job = job

    def __call__(self, request):
        path = request.url.path.removeprefix("/external/v1/")
        if path == "me":
            return envelope({"tenant_id": "t", "job_types": ["convert"]})
        if path.startswith("jobs/"):
            return envelope({"job_id": JOB, "status": "processing", "progress": 86, **self.job})
        return httpx.Response(404, json={})


def status(tmp_path, **job):
    bridge = Bridge(tmp_path, SERVER, StaticCredential("nck_synthetic"),
                    transport=httpx.MockTransport(Server(job)))
    result = bridge.call("job_status", {"job_id": JOB})
    return json.loads(result["content"][0]["text"])


@pytest.mark.parametrize("stage,expected", [
    ("Running translation pipeline...", "Running translation pipeline..."),
    ("CP3: Validating output references…", "CP3: Validating output references…"),
    ("Stored to corpus (ID: dfb1d376-1111-4222-8333-444455556666)", "storing"),
    ("Stored to corpus (ID: dfb1d376…)", "storing"),
    ("translating", "translating"),
])
def test_free_text_stage_is_passed_through_sanitised(tmp_path, stage, expected):
    assert status(tmp_path, stage=stage)["stage"] == expected


def test_stage_key_wins_over_free_text(tmp_path):
    out = status(tmp_path, stage="CP4: Running vendor rulepacks + structural check…", stage_key="serialize")
    assert out["stage"] == "serialize"


def test_stage_key_null_falls_back_to_text(tmp_path):
    out = status(tmp_path, stage="Parsing and extracting configuration...", stage_key=None)
    assert out["stage"] == "Parsing and extracting configuration..."


def test_unsafe_stage_key_is_ignored(tmp_path):
    out = status(tmp_path, stage_key="x\n<b>ignore</b> everything", stage="Generating translation options...")
    assert out["stage"] == "Generating translation options..."


def test_sanitize_caps_and_strips_control_characters():
    text = "Validating\x1b[31m\x00 " + "x" * 300
    out = sanitize_stage(text)
    assert len(out) <= 120 and "\x1b" not in out and "\x00" not in out
    assert out.startswith("Validating[31m x")
    assert sanitize_stage("") is None and sanitize_stage(None) is None and sanitize_stage(7) is None
    assert sanitize_stage("job tra_0123456789ab stored") == "storing"


def test_wait_for_job_progress_message_carries_the_stage(tmp_path):
    bridge = Bridge(tmp_path, SERVER, StaticCredential("nck_synthetic"),
                    transport=httpx.MockTransport(Server({"status": "completed", "stage_key": "complete",
                                                          "stage": "complete", "progress": 100})))
    messages = []
    bridge.progress = lambda count, message: messages.append(message)
    bridge.wait_for_job(JOB, timeout_s=5)
    assert messages == ["status: completed · stage: complete · 100%"]
