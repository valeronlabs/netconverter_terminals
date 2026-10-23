"""Running from a folder that can't be written ("/" on macOS) must not crash."""
import argparse
import os

import pytest

from netconverter_cli import cli


def _args(command=None, workspace=None):
    return argparse.Namespace(command=command, workspace=workspace)


@pytest.fixture
def readonly(tmp_path):
    folder = tmp_path / "readonly"
    folder.mkdir()
    folder.chmod(0o500)
    yield folder
    folder.chmod(0o700)


def test_default_workspace_falls_back_when_cwd_is_readonly(readonly, tmp_path, monkeypatch, capsys):
    if os.access(readonly, os.W_OK):
        pytest.skip("running as a user that can write any folder")
    home = tmp_path / "home" / "migrations"
    monkeypatch.setattr(cli, "DEFAULT_WORKSPACE", home)
    monkeypatch.chdir(readonly)
    args = _args("run")
    cli.resolve_workspace(args)
    assert args.workspace == str(home)
    assert home.is_dir() and (home.stat().st_mode & 0o777) == 0o700
    assert "is not writable" in capsys.readouterr().err


def test_explicit_readonly_workspace_is_a_clear_error(readonly):
    if os.access(readonly, os.W_OK):
        pytest.skip("running as a user that can write any folder")
    with pytest.raises(SystemExit, match="not writable"):
        cli.resolve_workspace(_args("run", str(readonly)))


def test_writable_folder_and_account_commands_are_unchanged(readonly, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = _args("run")
    cli.resolve_workspace(args)
    assert args.workspace == "."
    monkeypatch.chdir(readonly)
    args = _args("whoami")
    cli.resolve_workspace(args)
    assert args.workspace == "."


def test_parser_leaves_workspace_unset_so_the_default_is_detectable():
    assert cli.parser().parse_args([]).workspace is None
    assert cli.parser().parse_args(["--workspace", "x"]).workspace == "x"
