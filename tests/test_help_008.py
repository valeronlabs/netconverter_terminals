"""#8: help text everywhere, typo suggestions, --vendor codes, /refresh, README version, update --check."""

import argparse
import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from netconverter_cli import __version__, cli, commands, errors, update
from netconverter_cli.api import ExternalClient, StaticCredential

ROOT = Path(__file__).resolve().parents[1]
SERVER = "https://api.example/external/v1"


def _subcommands(parser):
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action


def _options(parser):
    return [a for a in parser._actions
            if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))]


def test_every_subcommand_and_option_has_help():
    parser = cli.parser()
    subs = _subcommands(parser)
    listed = {choice.dest: choice.help for choice in subs._choices_actions}
    missing = sorted(name for name in subs.choices if not (listed.get(name) or "").strip())
    assert not missing, f"subcommands without help: {missing}"
    undocumented = [a.dest for a in _options(parser) if not (a.help or "").strip()]
    for name, sub in subs.choices.items():
        undocumented += [f"{name} {a.dest}" for a in _options(sub) if not (a.help or "").strip()]
    assert not undocumented, f"options without help: {undocumented}"


def test_options_help_carries_an_example_and_to_is_only_on_convert():
    subs = _subcommands(cli.parser()).choices
    options = next(a for a in _options(subs["convert"]) if a.dest == "options")
    assert """'{"panos_target_version":"12.1"}'""" in options.help
    for name in ("validate", "analyze", "optimize"):
        assert "target" not in {a.dest for a in _options(subs[name])}, name
    assert "target" in {a.dest for a in _options(subs["convert"])}


def test_top_level_help_fits_100_columns_without_the_choice_dump(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "100")
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "{run," not in out and "COMMAND" in out
    assert max(len(line) for line in out.splitlines()) <= 100
    assert "convert" in out and "capabilities" in out


@pytest.mark.parametrize("typo,suggestion", [("convrt", "convert"), ("validat", "validate"), ("whomai", "whoami")])
def test_a_typo_suggests_the_command(capsys, typo, suggestion):
    with pytest.raises(SystemExit) as info:
        cli.main([typo])
    assert info.value.code == errors.EXIT_USAGE
    err = capsys.readouterr().err
    assert f"Unknown command '{typo}'. Did you mean '{suggestion}'?" in err
    assert "choose from" not in err


def test_an_unrelated_word_gets_no_suggestion(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["xyzzy"])
    assert info.value.code == errors.EXIT_USAGE
    err = capsys.readouterr().err
    assert "Unknown command 'xyzzy'." in err and "Did you mean" not in err and "--help" in err


def test_missing_vendor_lists_the_valid_codes(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text("config system global\nend\n")
    vendors = [{"code": "fortinet", "name": "Fortinet", "device_type": "firewall", "roles": ["source", "target"]},
               {"code": "cisco_asa", "name": "Cisco ASA", "device_type": "firewall", "roles": ["source"]}]

    def handler(request):
        path = request.url.path.removeprefix("/external/v1/")
        if path == "capabilities":
            return httpx.Response(200, json={"success": True, "data": {"vendors": vendors, "job_types": ["validate"]}})
        return httpx.Response(200, json={"success": True, "data": {"job_types": ["validate"]}})

    client = ExternalClient(StaticCredential("nck_synthetic"), SERVER, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cli, "open_client", lambda credential, url: (client, "external"))
    monkeypatch.setattr(cli, "rest_credential", lambda *a, **k: "nck_synthetic")
    with pytest.raises(SystemExit) as info:
        cli.main(["--workspace", str(tmp_path), "--server", SERVER, "validate", "edge.cfg"])
    assert info.value.code == errors.EXIT_USAGE
    err = capsys.readouterr().err
    assert "--vendor is required" in err and "cisco_asa" in err and "fortinet" in err


def test_missing_vendor_while_signed_out_is_still_a_usage_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "edge.cfg").write_text("config system global\nend\n")

    def refuse(*a, **k):
        raise errors.CommandError(errors.SIGNED_OUT, errors.EXIT_AUTH)
    monkeypatch.setattr(cli, "rest_credential", refuse)
    with pytest.raises(SystemExit) as info:
        cli.main(["--workspace", str(tmp_path), "validate", "edge.cfg"])
    assert info.value.code == errors.EXIT_USAGE
    assert "--vendor is required" in capsys.readouterr().err


# -- the app -------------------------------------------------------------------


def test_app_help_points_at_real_commands():
    assert "--json capabilities" not in commands.HELP
    assert "netconverter capabilities" in commands.HELP
    assert "/refresh" in commands.HELP


def test_refresh_and_the_allowance_alias_both_reload_capabilities():
    calls = []
    controller = SimpleNamespace(capabilities=lambda: calls.append(1) or {"remaining": {}})
    commands.execute(controller, "/refresh")
    commands.execute(controller, "/allowance")
    assert calls == [1, 1]


def test_help_card_and_offline_pill_name_refresh():
    from rich.console import Console

    from netconverter_cli.branding import header
    from netconverter_cli.presentation import HELP_SECTIONS

    rows = [command for _, section in HELP_SECTIONS for command, _ in section]
    assert any("/refresh" in command for command in rows)
    console = Console(width=140, record=True)
    console.print(header(140, server="offline"))
    assert "offline · /refresh to retry" in console.export_text()


# -- versions ----------------------------------------------------------------


def test_readme_banner_matches_the_package_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert project == __version__, "pyproject.toml and src/netconverter_cli/__init__.py disagree"
    shown = re.findall(r"NetConverter\s+v(\d+\.\d+\.\d+)", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert shown, "README.md banner has no version"
    assert set(shown) == {__version__}, (
        f"README.md shows v{', v'.join(sorted(set(shown)))} but the package is {__version__}; "
        "run `python scripts/sync_readme_version.py`")


class GitHub:
    def __init__(self, version):
        self.version = version

    def __call__(self, request):
        return httpx.Response(200, json={"tag_name": f"v{self.version}", "assets": []})


def test_update_check_prints_a_plain_line(capsys):
    code = update.run(SimpleNamespace(check=True, yes=False, json=False),
                      transport=httpx.MockTransport(GitHub("9.8.7")))
    assert code == 0
    assert capsys.readouterr().out.strip() == (
        f"Update available: {__version__} → 9.8.7. Run `netconverter update`.")
    update.run(SimpleNamespace(check=True, yes=False, json=False), transport=httpx.MockTransport(GitHub(__version__)))
    assert capsys.readouterr().out.strip() == f"NetConverter CLI {__version__} is up to date."


def test_update_check_json_is_behind_the_flag(capsys):
    update.run(SimpleNamespace(check=True, yes=False, json=True), transport=httpx.MockTransport(GitHub("9.8.7")))
    assert json.loads(capsys.readouterr().out) == {"installed": __version__, "latest": "9.8.7",
                                                   "update_available": True}
    assert cli.parser().parse_args(["update", "--check", "--json"]).json is True
