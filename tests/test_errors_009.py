"""#9 and valeronlabs#7: Ctrl-C, specific error reasons, stderr and distinct exit codes.

Every server reply is an httpx.MockTransport; every file is synthetic.
"""

import os
import re
import select
import sys
import time
from pathlib import Path

import httpx
import pytest

from netconverter_cli import cli, credentials, errors
from netconverter_cli.api import APIError, ExternalClient, StaticCredential

SERVER = "https://api.example/external/v1"
ROOT = Path(__file__).resolve().parents[1]
VENDORS = [{"code": "fortinet", "name": "Fortinet FortiGate", "device_type": "firewall", "roles": ["source", "target"]},
           {"code": "cisco_asa", "name": "Cisco ASA", "device_type": "firewall", "roles": ["source"]},
           {"code": "palo_alto_xml", "name": "Palo Alto", "device_type": "firewall", "roles": ["source", "target"]}]
FORTI = 'config system global\n    set hostname "SYNTHETIC-FW"\nend\n'


class Server:
    """GET /me and /capabilities succeed; POST /jobs answers ``reply``."""

    def __init__(self, reply=None, limit=5 * 1024 * 1024):
        self.reply, self.limit, self.requests = reply, limit, []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/external/v1/")
        if path == "me":
            return httpx.Response(200, json={"success": True, "data": {"job_types": ["convert", "validate", "optimize"]}})
        if path == "capabilities":
            return httpx.Response(200, json={"success": True, "data": {
                "vendors": VENDORS, "job_types": ["convert", "validate", "optimize"],
                "limits": {"max_config_bytes": self.limit}}})
        if path == "jobs" and request.method == "POST":
            return self.reply or httpx.Response(200, json={"success": True, "data": {"job_id": "tra_0123456789ab", "status": "queued"}})
        return httpx.Response(404, json={})


def signed_in(monkeypatch, server):
    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(server))
    monkeypatch.setattr(cli, "open_client", lambda credential, url: (client, "external"))
    monkeypatch.setattr(cli, "rest_credential", lambda *a, **k: "nck_synthetic")


def signed_out(monkeypatch):
    def refuse(*a, **k):
        raise errors.CommandError(errors.SIGNED_OUT, errors.EXIT_AUTH)
    monkeypatch.setattr(cli, "rest_credential", refuse)


def run(argv):
    with pytest.raises(SystemExit) as info:
        cli.main(argv)
    return info.value.code


# -- Ctrl-C ----------------------------------------------------------------


def test_ctrl_c_anywhere_in_a_command_is_one_line_and_exit_130(tmp_path, monkeypatch, capsys):
    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "configure", interrupted)
    assert run(["--workspace", str(tmp_path), "setup"]) == 130
    captured = capsys.readouterr()
    assert captured.err.strip() == "Cancelled. Nothing was saved."
    assert captured.out == ""


# The child makes the pty its controlling terminal (setsid + TIOCSCTTY) so that
# Ctrl-C reaches it as SIGINT, exactly as in a real terminal.
_CHILD = ("import os, sys, fcntl, termios, runpy; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
          "sys.argv = ['netconverter', *sys.argv[1:]]; runpy.run_module('netconverter_cli.cli', run_name='__main__')")


def _read(fd, output, until, deadline):
    while (until is None or until.encode() not in output) and time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
    return output


def _pty_run(args, tmp_path, wait_for):
    """Run the CLI on a pseudo-terminal, press Ctrl-C at the first prompt, return (status, output)."""
    pty = pytest.importorskip("pty")
    import subprocess

    env = {**os.environ, "HOME": str(tmp_path), "NETCONVERTER_NO_UPDATE_CHECK": "1",
           "PYTHONPATH": str(ROOT / "src"), "TERM": "dumb", "NETCONVERTER_AUTH": "key"}
    env.pop("NETCONVERTER_API_KEY", None)
    master, slave = pty.openpty()
    child = subprocess.Popen([sys.executable, "-c", _CHILD, *args], stdin=slave, stdout=slave, stderr=slave,
                             cwd=tmp_path, env=env, close_fds=True)
    os.close(slave)
    deadline = time.monotonic() + 20
    try:
        output = _read(master, b"", wait_for, deadline)
        assert wait_for.encode() in output, output.decode(errors="replace")
        os.write(master, b"\x03")
        output = _read(master, output, None, deadline)
        status = child.wait(timeout=max(1, deadline - time.monotonic()))
    finally:
        if child.poll() is None:
            child.kill()
        os.close(master)
    return status, output.decode(errors="replace")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pseudo-terminal")
def test_ctrl_c_at_the_api_key_prompt_on_a_terminal(tmp_path):
    code, output = _pty_run(["login", "--key"], tmp_path, "API key")
    assert code == 130, output
    assert "Traceback" not in output
    assert "Cancelled. Nothing was saved." in output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pseudo-terminal")
def test_ctrl_c_at_the_setup_prompt_on_a_terminal(tmp_path):
    code, output = _pty_run(["setup"], tmp_path, "Server URL")
    assert code == 130, output
    assert "Traceback" not in output
    assert "Cancelled. Nothing was saved." in output


# -- local input is checked before sign-in, verbatim, exit 4 -----------------


@pytest.mark.parametrize("name,prepare,expected", [
    ("missing.cfg", lambda root: None, "missing.cfg"),
    ("empty.cfg", lambda root: (root / "empty.cfg").write_text(""), "empty"),
    ("../outside.cfg", lambda root: (root.parent / "outside.cfg").write_text(FORTI), "Path is outside the workspace"),
    ("link.cfg", lambda root: ((root / "real.cfg").write_text(FORTI), (root / "link.cfg").symlink_to(root / "real.cfg")),
     "Symbolic links are not accepted"),
])
def test_file_problems_are_reported_verbatim_before_the_sign_in(tmp_path, monkeypatch, capsys, name, prepare, expected):
    root = tmp_path / "work"
    root.mkdir()
    prepare(root)
    signed_out(monkeypatch)
    code = run(["--workspace", str(root), "--server", SERVER, "validate", name, "--vendor", "fortinet"])
    captured = capsys.readouterr()
    assert code == errors.EXIT_INPUT, captured
    assert expected in captured.err
    assert "Invalid or unavailable operation" not in captured.err + captured.out
    assert "not signed in" not in captured.err.lower()
    assert captured.out == ""


@pytest.mark.parametrize("options,expected", [("{bad", "--options is not valid JSON"),
                                              ('["a"]', "--options must be a JSON object")])
def test_malformed_options_are_an_input_error(tmp_path, monkeypatch, capsys, options, expected):
    (tmp_path / "edge.cfg").write_text(FORTI)
    signed_out(monkeypatch)
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "convert", "edge.cfg", "--vendor", "fortinet",
                "--to", "palo_alto_xml", "--options", options])
    err = capsys.readouterr().err
    assert code == errors.EXIT_INPUT and expected in err
    assert "panos_target_version" in err  # the example shows the shape


def test_size_limit_from_the_server_is_shown_verbatim(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text(FORTI)
    signed_in(monkeypatch, Server(limit=10))
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "validate", "edge.cfg", "--vendor", "fortinet"])
    captured = capsys.readouterr()
    assert code == errors.EXIT_INPUT
    assert "Configuration must be 1–10 bytes" in captured.err and captured.out == ""


# -- server replies ---------------------------------------------------------


def _envelope(status, code, message):
    return httpx.Response(status, json={"success": False, "request_id": "req_synthetic",
                                        "error": {"code": code, "message": message}})


def test_a_422_reason_goes_to_stderr_with_the_input_exit_code(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text(FORTI)
    reason = "yaml_v2: unknown top-level section 'zone_mappingz' (line 3, column 1)"
    signed_in(monkeypatch, Server(_envelope(422, "unprocessable", reason)))
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "convert", "edge.cfg", "--vendor", "fortinet",
                "--to", "palo_alto_xml"])
    captured = capsys.readouterr()
    assert code == errors.EXIT_INPUT
    assert reason in captured.err and captured.out == ""


@pytest.mark.parametrize("message,expected", [
    ("insufficient scope", "permission"),
    ("{'code': 'feature_not_available', 'feature': 'optimizer'}", "optimizer"),
    ("tenant not active", "not active"),
])
def test_a_403_says_what_is_missing(tmp_path, monkeypatch, capsys, message, expected):
    (tmp_path / "edge.cfg").write_text(FORTI)
    signed_in(monkeypatch, Server(_envelope(403, "forbidden", message)))
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "optimize", "edge.cfg", "--vendor", "fortinet"])
    err = capsys.readouterr().err
    assert code == errors.EXIT_AUTH
    assert expected in err and "capabilities" in err
    assert err.strip() != "forbidden"


def test_a_401_prints_the_signed_out_message(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text(FORTI)
    signed_in(monkeypatch, Server(_envelope(401, "unauthorized", "invalid api key")))
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "validate", "edge.cfg", "--vendor", "fortinet"])
    assert code == errors.EXIT_AUTH and errors.SIGNED_OUT in capsys.readouterr().err


def test_a_server_failure_has_its_own_exit_code(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text(FORTI)
    signed_in(monkeypatch, Server(_envelope(503, "error", "maintenance window")))
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "validate", "edge.cfg", "--vendor", "fortinet"])
    assert code == errors.EXIT_SERVER and "maintenance window" in capsys.readouterr().err


def test_not_signed_in_is_the_auth_exit_code(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text(FORTI)
    monkeypatch.setattr(cli, "get_secret", lambda *a, **k: "")
    monkeypatch.setattr(cli, "keyring_available", lambda: True)
    code = run(["--workspace", str(tmp_path), "--server", SERVER, "validate", "edge.cfg", "--vendor", "fortinet"])
    assert code == errors.EXIT_AUTH and "netconverter login" in capsys.readouterr().err


def test_tui_shows_the_server_reason_for_a_422():
    reason = "cisco_nxos is not a supported source vendor"
    text = errors.api_error_message(APIError(422, "unprocessable", "req_1", message=reason))
    assert reason in text
    assert errors.api_error_message(APIError(401, "unauthorized", "req_1")) == errors.SIGNED_OUT
    assert "optimizer" in errors.api_error_message(
        APIError(403, "forbidden", "req_1", message="{'code': 'feature_not_available', 'feature': 'optimizer'}"))


# -- prompts and docs --------------------------------------------------------


def test_api_key_prompt_names_the_host_not_an_internal_id(monkeypatch):
    prompts = []
    monkeypatch.delenv("NETCONVERTER_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "_os_backend", lambda: None)
    monkeypatch.setattr(credentials.getpass, "getpass", lambda text: prompts.append(text) or "nck_typed")
    monkeypatch.setenv("NETCONVERTER_AUTH", "key")
    assert cli.rest_credential("https://api.netconverter.ai/external/v1", {}) == "nck_typed"
    assert prompts == ["NetConverter API key for api.netconverter.ai (hidden; kept in memory for this run only): "]
    assert not re.search(r"server:[0-9a-f]", prompts[0])


def test_exit_codes_are_documented():
    text = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    section = text.split("## Exit codes", 1)[1]
    for code in (errors.EXIT_FAILURE, errors.EXIT_USAGE, errors.EXIT_AUTH, errors.EXIT_INPUT,
                 errors.EXIT_SERVER, errors.EXIT_CANCELLED):
        assert f"| `{code}` |" in section


@pytest.mark.asyncio
async def test_tui_card_carries_the_422_reason(tmp_path):
    from textual.widgets import RichLog

    from netconverter_cli.controller import Controller
    from netconverter_cli.tui import Terminal

    reason = "yaml_v2: unknown top-level section 'zone_mappingz' (line 3, column 1)"
    (tmp_path / "edge.cfg").write_text(FORTI)
    server = Server(_envelope(422, "unprocessable", reason))
    controller = Controller(tmp_path, ExternalClient(StaticCredential("nck_synthetic"), SERVER,
                                                     transport=httpx.MockTransport(server)))
    app = Terminal(controller)
    async with app.run_test(size=(140, 40)) as pilot:
        await app.workers.wait_for_complete()
        app.dispatch('/open edge.cfg fortinet')
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.dispatch('/convert {"target_vendor":"palo_alto_xml"}')
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = "\n".join(line.text for line in app.query_one(RichLog).lines)
    assert "zone_mappingz" in text
    assert "could not accept these choices" not in text


def test_bridge_403_says_what_is_missing():
    from netconverter_cli.mcp_server import _api_failure

    failure = _api_failure(APIError(403, "forbidden", "req_1", message="insufficient scope"))
    assert failure.code == "forbidden" and "permission" in str(failure)
    assert failure.extra["http_status"] == 403
