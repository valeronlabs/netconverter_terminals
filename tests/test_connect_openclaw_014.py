"""#14 (basic): `netconverter connect openclaw` through OpenClaw's own `openclaw mcp` CLI."""
import argparse
import json
import subprocess
from pathlib import Path

import pytest

from netconverter_cli import cli, connect

EXE = "/opt/bin/netconverter"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(connect, "executable", lambda: EXE)
    monkeypatch.setattr(connect.shutil, "which", lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None)
    work = tmp_path / "migrations"
    work.mkdir()
    return tmp_path, work


@pytest.fixture
def runs(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="netconverter: ok (5 tools)\n", stderr="")
    monkeypatch.setattr(connect.subprocess, "run", run)
    return calls


def add_argv(work):
    return ["/usr/local/bin/openclaw", "mcp", "add", "netconverter", "--command", EXE,
            "--arg", "mcp", "--arg", "--workspace", "--arg", str(work.resolve()), "--arg", "--strict"]


def write_config(home_dir, entry):
    path = home_dir / ".openclaw" / "openclaw.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"mcp": {"servers": {"netconverter": entry}}}))


def test_openclaw_is_listed_and_detected(home):
    home_dir, _ = home
    assert "openclaw" in connect.CLIENTS
    assert connect.CLIENTS["openclaw"].installed()
    assert "openclaw" in connect.installed_local_clients()
    assert not connect.CLIENTS["openclaw"].configured()


def test_plan_shows_the_command_and_applies_add_then_probe(home, runs):
    _, work = home
    change = connect.plan("openclaw", work)
    assert change.can_apply and runs == []  # planning runs nothing
    assert "openclaw mcp add netconverter --command" in change.preview and "--strict" in change.preview
    message = change.apply()
    assert runs == [add_argv(work), ["/usr/local/bin/openclaw", "mcp", "doctor", "netconverter", "--probe"]]
    assert "5 tools" in message
    deny = [extra for extra in change.followups if extra.key == "openclaw-deny"]
    assert deny and not deny[0].can_apply and str(work.resolve()) in deny[0].preview


def test_already_connected_is_a_no_op(home, runs):
    home_dir, work = home
    write_config(home_dir, {"command": EXE, "args": ["mcp", "--workspace", str(work.resolve()), "--strict"]})
    assert connect.CLIENTS["openclaw"].configured()
    change = connect.plan("openclaw", work)
    assert not change.can_apply and "already" in change.summary
    assert runs == []


def test_a_different_entry_is_replaced_via_unset_then_add(home, runs):
    home_dir, work = home
    write_config(home_dir, {"command": EXE, "args": ["mcp", "--workspace", "/elsewhere"]})
    change = connect.plan("openclaw", work)
    assert change.can_apply and "Replaces" in change.summary
    change.apply()
    assert runs[0] == ["/usr/local/bin/openclaw", "mcp", "unset", "netconverter"]
    assert runs[1] == add_argv(work)


def test_remove_path(home, runs):
    home_dir, work = home
    write_config(home_dir, {"command": EXE, "args": ["mcp", "--workspace", str(work.resolve()), "--strict"]})
    change = connect.plan_remove("openclaw", work)
    assert change.can_apply and "openclaw mcp unset netconverter" in change.preview
    change.apply()
    assert runs == [["/usr/local/bin/openclaw", "mcp", "unset", "netconverter"]]
    write_config(home_dir, {"command": "other"})
    assert not connect.plan_remove("openclaw", work).can_apply


def test_failed_add_is_reported(home, monkeypatch):
    _, work = home
    monkeypatch.setattr(connect.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, stdout="", stderr="probe failed: command not found"))
    with pytest.raises(RuntimeError, match="probe failed"):
        connect.plan("openclaw", work).apply()


def test_without_openclaw_on_path_prints_the_json5_block(home, monkeypatch):
    home_dir, work = home
    monkeypatch.setattr(connect.shutil, "which", lambda name: None)
    change = connect.plan("openclaw", work)
    assert not change.can_apply
    assert "mcp: {" in change.preview and "servers: {" in change.preview and "netconverter: {" in change.preview
    assert '"--strict"' in change.preview and "openclaw.json" in change.manual


def args(work, **kw):
    base = dict(workspace=str(work), client="openclaw", all=False, print_only=False, yes=False, remove=False)
    return argparse.Namespace(**{**base, **kw})


def test_cli_asks_before_applying_and_removes_with_remove(home, runs, capsys):
    home_dir, work = home
    cli.run_connect(args(work), ask=lambda prompt: "n")
    assert runs == [] and "Nothing was changed" in capsys.readouterr().out
    cli.run_connect(args(work), ask=lambda prompt: "y")
    assert runs[0] == add_argv(work)
    write_config(home_dir, {"command": EXE, "args": ["mcp", "--workspace", str(work.resolve()), "--strict"]})
    runs.clear()
    cli.run_connect(args(work, remove=True), ask=lambda prompt: "y")
    assert runs == [["/usr/local/bin/openclaw", "mcp", "unset", "netconverter"]]
    assert cli.parser().parse_args(["connect", "openclaw", "--remove"]).remove is True
