"""#7 plain one-shot summaries, #27 the TUI scorecard: snapshots over synthetic job payloads.

The payloads in tests/fixtures/jobs are synthetic, shaped like GET /jobs/{id} on the
External API (analysis_digest.validation_result / optimization_result, the convert
verdict fields and ci_verdict), named after the tester's replay jobs.
"""
import io
import json
import re
from pathlib import Path

import httpx
import pytest
from rich.console import Console

from netconverter_cli import cli
from netconverter_cli.summary import plain, plain_lines, sarif_findings, scorecard, summarize

FIXTURES = Path(__file__).parent / "fixtures" / "jobs"
SERVER = "https://api.netconverter.ai/external/v1"


def load(name):
    return json.loads((FIXTURES / name).read_text())


VALIDATE = """\
Validation val_9f9acb9b5a59 · Cisco ASA · completed
Verdict: blocked · not ready to convert: 2 blocking issues
Score 48/100 · 22 objects · 11 rules · 7 unparsed lines (4.6%)
6 findings: 2 blocking, 1 error, 3 warnings
  blocking  Missing reference: object group DMZ-SERVERS
  blocking  Missing reference: service group WEB-PORTS (object completeness check)
  error     HTTP management exposed to any host
  … 3 more: netconverter resume val_9f9acb9b5a59 --all
Unparsed lines: netconverter query unparsed_lines
Next: fix the blocking issues, then: netconverter validate <file> --vendor cisco_asa"""

CONVERT = """\
Conversion tra_4058ef406cd6 · Cisco ASA → Palo Alto (XML) · completed
Verdict: needs review · 5 items to review
  • The NAT equivalence check had nothing to test: no NAT rules to compare
  • The shadowing check found 1 new shadowed rule in the parsed model
  • The vendor rule check: security rule count near the platform limit
  … 2 more: netconverter resume tra_4058ef406cd6 --all
Next: netconverter download"""

OPTIMIZE = """\
Optimization opt_4056e02e5b66 · fortinet · completed
Verdict: needs review · 3 errors to review
Score 70/100 · 140 objects · 38 rules
11 findings: 3 errors, 3 warnings, 5 info
  error     SSH management exposed to any host
  error     Allow rules missing security profiles (6)
  error     Shadowed rule (relationship score 0.4) (2)
  … 8 more: netconverter resume opt_4056e02e5b66 --all
Next: netconverter download"""

RUNNING = """\
Conversion tra_5a5a5a5a5a5a · Cisco ASA → Palo Alto (XML) · processing 25%
Stage: Running translation pipeline...
Next: netconverter resume tra_5a5a5a5a5a5a"""

SNAPSHOTS = [("val_9f9acb9b5a59.json", VALIDATE), ("tra_4058ef406cd6.json", CONVERT),
             ("opt_4056e02e5b66.json", OPTIMIZE), ("tra_running.json", RUNNING)]
FORBIDDEN = re.compile(r"\bBC\d|\bcp\d|\bIR\b|vacuous|RAG|graph contribution|get_evidence|list_with",
                       re.IGNORECASE)


@pytest.mark.parametrize("name,expected", SNAPSHOTS)
def test_plain_summary_snapshots(name, expected):
    assert "\n".join(plain_lines(summarize(load(name)))) == expected


@pytest.mark.parametrize("name,_", SNAPSHOTS)
def test_summary_is_short_plain_and_ends_with_a_command(name, _):
    lines = plain_lines(summarize(load(name)))
    assert len(lines) <= 10
    assert lines[-1].startswith("Next: ") and "netconverter " in lines[-1]
    text = "\n".join(lines)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    verdicts = [line for line in lines if line.startswith("Verdict: ")]
    assert len(verdicts) <= 1
    for line in verdicts:
        assert line.split(" · ")[0] in {"Verdict: ready", "Verdict: needs review", "Verdict: blocked"}


def test_validate_never_says_push():
    text = "\n".join(plain_lines(summarize(load("val_9f9acb9b5a59.json")), all_findings=True))
    assert "push" not in text.lower()


@pytest.mark.parametrize("name", ["val_9f9acb9b5a59.json", "opt_4056e02e5b66.json"])
def test_every_count_sentence_adds_up(name):
    for line in plain_lines(summarize(load(name))):
        match = re.fullmatch(r"(\d+) findings: (.*)", line)
        if match:
            parts = [int(n) for n in re.findall(r"(\d+) \w+", match.group(2))]
            assert sum(parts) == int(match.group(1))
            break
    else:
        pytest.fail("no count sentence")


def test_all_shows_every_finding():
    job = load("val_9f9acb9b5a59.json")
    every = sarif_findings(json.loads((FIXTURES / "val_9f9acb9b5a59.sarif").read_text()))
    lines = plain_lines(summarize(job, findings=every), all_findings=True)
    listed = [line for line in lines if line.startswith("  ") and not line.startswith("  …")]
    assert len(listed) == 6  # 6 of 6
    assert "Overlapping service definitions" in "\n".join(lines)
    assert not any("more:" in line for line in lines)


def test_plain_wording_map():
    assert plain("BC4 blocked: zone inside has no target") == "The zone check blocked: zone inside has no target"
    assert plain("Knowledge: RAG confidence 0.8") == "Knowledge: knowledge-base match 80%"
    assert plain("CP0 found 3 lines; IR built") == "The parse coverage check found 3 lines; the parsed model built"
    assert plain("unsafe to push", validate=True) == "unsafe to convert"
    assert plain("x\x1b[2Jy") == "x[2Jy"


# -- CLI wiring ------------------------------------------------------------------


class Jobs:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/external/v1/")
        env = lambda data: httpx.Response(200, json={"success": True, "data": data})
        if path == "me":
            return env({"tenant_id": "t", "job_types": ["convert", "validate", "optimize"]})
        if path.endswith("/findings.sarif"):
            return httpx.Response(200, content=(FIXTURES / "val_9f9acb9b5a59.sarif").read_bytes())
        if path.startswith("jobs/"):
            return env(load(path.split("/")[1] + ".json"))
        return httpx.Response(404, json={})


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    server = Jobs()
    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_synthetic")
    real = cli.open_client
    monkeypatch.setattr(cli, "open_client",
                        lambda credential, srv: real(credential, srv, transport=httpx.MockTransport(server)))

    def go(*argv):
        cli.main(["--workspace", str(tmp_path), "--server", SERVER, *argv])
        return capsys.readouterr().out
    return go


def test_resume_prints_the_plain_summary_by_default(run):
    assert run("resume", "val_9f9acb9b5a59").rstrip("\n") == VALIDATE


def test_resume_json_is_the_raw_payload_without_ascii_escapes(run):
    out = run("resume", "tra_4058ef406cd6", "--json")
    payload = load("tra_4058ef406cd6.json")
    assert out == json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n"
    assert "\\u2192" not in run("resume", "tra_running", "--json")


def test_resume_all_lists_every_finding(run):
    out = run("resume", "val_9f9acb9b5a59", "--all")
    assert out.count("\n  ") >= 6 and "Overlapping service definitions" in out


# -- #27 TUI scorecard -----------------------------------------------------------


def render(renderable):
    console = Console(file=io.StringIO(), width=110, color_system=None)
    console.print(renderable)
    return console.file.getvalue()


@pytest.mark.parametrize("name", ["val_9f9acb9b5a59.json", "opt_4056e02e5b66.json"])
def test_tui_scorecard_is_a_short_plain_card(name):
    text = render(scorecard(load(name), surface="tui"))
    assert len(text.strip().splitlines()) <= 15
    for gone in ("Further detail is available", "Count definitions", "Count labels", "By type",
                 "get_evidence", "Severity scale", "Kind"):
        assert gone not in text
    assert not FORBIDDEN.search(text)
    assert "/download" in text


# -- query unparsed_lines ----------------------------------------------------------


def test_query_unparsed_lines_lists_them_through_the_evidence_tool(tmp_path):
    from netconverter_cli.api import ExternalClient, StaticCredential
    from netconverter_cli.controller import Controller

    calls = []

    class Remote:
        def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return {"structuredContent": {"unparsed_lines": [{"line": 12, "text": "wccp web-cache"}]}}

    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(Jobs()))
    controller = Controller(tmp_path, client, kind="external", remote=Remote)
    controller.state["active_job"] = "val_9f9acb9b5a59"
    result = controller.query("unparsed_lines", {})
    assert calls == [("select_job", {"job_id": "val_9f9acb9b5a59"}),
                     ("get_evidence", {"section": "unparsed_lines"})]
    assert result["details"]["unparsed_lines"][0]["line"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["val_9f9acb9b5a59.json", "opt_4056e02e5b66.json", "tra_4058ef406cd6.json"])
async def test_tui_job_card_shows_the_scorecard(tmp_path, name):
    from unittest.mock import Mock

    from textual.widgets import RichLog

    from netconverter_cli.controller import Controller
    from netconverter_cli.tui import Terminal

    api = Mock()
    api.capabilities.return_value = {"remaining": {"convert": 3}, "targets": ["palo_alto_set"]}
    app = Terminal(Controller(tmp_path, api))
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        log = app.query_one(RichLog)
        before = len(log.lines)
        app.downloaded_jobs.add(load(name)["job_id"])  # no automatic /download in this test
        app.show_job(load(name))
        await pilot.pause()
        card = "\n".join(line.text for line in log.lines[before:])
    assert len(card.strip().splitlines()) <= 16
    assert not FORBIDDEN.search(card), FORBIDDEN.search(card)
    for gone in ("Further detail is available", "Count definitions", "By type", "Severity scale"):
        assert gone not in card
    if name.startswith("val"):
        assert "BLOCKED" in card and "6 findings: 2 blocking, 1 error, 3 warnings" in card


def test_tui_unparsed_lines_command_routes_to_the_query(tmp_path):
    from unittest.mock import Mock

    from netconverter_cli.commands import execute

    controller = Mock()
    controller.query.return_value = {"details": {}}
    execute(controller, "/unparsed_lines")
    controller.query.assert_called_once_with("unparsed_lines", {})
