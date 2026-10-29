"""License acceptance gate (0.4.4): nothing runs until the license is accepted."""
import io
import json

import pytest

from netconverter_cli import cli, license as lic


@pytest.fixture
def not_accepted(monkeypatch):
    monkeypatch.delenv("NETCONVERTER_ACCEPT_LICENSE", raising=False)
    assert not lic.accepted()


def test_commands_refuse_until_accepted(not_accepted, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["jobs"])
    assert "license has not been accepted" in str(exc.value)
    assert "netconverter license" in str(exc.value)


def test_typed_accept_records_once_per_version(not_accepted):
    out = []
    assert lic.prompt(ask=lambda _: "accept", out=out.append)
    assert lic.accepted()
    record = lic.recorded()
    assert record["license_version"] == lic.LICENSE_VERSION and record["accepted_at"]
    assert oct(lic._record().stat().st_mode)[-3:] == "600"
    assert any("may not copy, share" in line for line in out)


@pytest.mark.parametrize("answer", ["", "yes", "y", "no"])
def test_anything_but_accept_is_not_acceptance(not_accepted, answer):
    assert not lic.prompt(ask=lambda _: answer, out=lambda *_: None)
    assert not lic.accepted()


def test_a_new_license_version_needs_acceptance_again(not_accepted, monkeypatch):
    lic.accept()
    monkeypatch.setattr(lic, "LICENSE_VERSION", "2.0")
    assert not lic.accepted()


def test_environment_accepts_without_a_record(monkeypatch, not_accepted):
    monkeypatch.setenv("NETCONVERTER_ACCEPT_LICENSE", "1")
    assert lic.accepted()
    assert lic.recorded() is None
    assert lic.status()["accepted_via_environment"] is True


def test_license_walkthrough_and_update_work_before_acceptance(not_accepted, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["license", "status"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is False
    with pytest.raises(SystemExit) as exc:
        cli.main(["walkthrough", "1"])
    assert exc.value.code == 0
    lic.ensure("update", interactive=False)  # does not raise


def test_license_accept_yes_for_scripts(not_accepted, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["license", "accept"])
    assert exc.value.code == 2  # no terminal and no --yes
    assert not lic.accepted()
    with pytest.raises(SystemExit) as exc:
        cli.main(["license", "accept", "--yes"])
    assert exc.value.code == 0 and lic.accepted()


def test_full_text_is_the_proprietary_license():
    text = lic.full_text()
    assert "NetConverter Terminal Client License" in text
    assert "MIT License" not in text.splitlines()[0]
    assert "redistribut" in text or "distribute" in text


def test_bridge_without_acceptance_answers_and_explains(not_accepted):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "submit_file", "arguments": {}}},
    ]
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    lic.serve_blocked_mcp(stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]  # the notification gets no reply
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == ["license_status"]
    assert replies[2]["result"]["isError"] is True
    assert "netconverter license" in replies[2]["result"]["content"][0]["text"]


def test_mcp_command_serves_the_blocked_bridge(not_accepted, monkeypatch):
    called = []
    monkeypatch.setattr(lic, "serve_blocked_mcp", lambda: called.append(True))
    cli.main(["mcp"])
    assert called == [True]
