"""#13: `netconverter privacy level|status` and how `mcp` flags combine with the folder's level.

Precedence: the folder's level (set only with `privacy level`, default masked) is
the most any bridge for that folder serves. `--level`, `--strict` (= masked),
`--full` (= full) and NETCONVERTER_MCP_VIEW can only lower it for one process;
the flag beats the variable. The server then applies min(grant, level).
"""

import json

import pytest

from netconverter_cli import cli, exposure


def privacy(tmp_path, *argv):
    try:
        cli.main(["--workspace", str(tmp_path), "privacy", *argv])
    except SystemExit as exc:
        if exc.code:
            raise


def test_status_shows_the_default_masked_level(tmp_path, capsys):
    privacy(tmp_path, "status")
    out = capsys.readouterr().out
    assert "masked" in out and "default" in out and "Secrets" in out
    privacy(tmp_path, "status", "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["level"] == "masked" and data["sections"] == [] and data["changes"] == 0
    assert data["workspace"] == str(tmp_path.resolve())
    assert set(data["levels"]) == set(exposure.LEVELS)


def test_privacy_without_an_action_is_status(tmp_path, capsys):
    privacy(tmp_path)
    assert "Exposure level" in capsys.readouterr().out


def test_lowering_from_a_script(tmp_path, capsys):
    privacy(tmp_path, "level", "none")
    assert "none" in capsys.readouterr().out
    assert exposure.load(tmp_path).level == "none"


def test_raising_from_a_script_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(exposure, "_interactive", lambda: False)
    with pytest.raises(SystemExit) as exc:
        privacy(tmp_path, "level", "full")
    assert exc.value.code == 1
    assert "terminal" in capsys.readouterr().err
    assert exposure.load(tmp_path).level == "masked"


def test_raising_in_a_terminal_with_the_typed_phrase(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(exposure, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "raise to selected")
    privacy(tmp_path, "level", "selected", "--sections", "nat,routes")
    assert exposure.load(tmp_path) == exposure.Exposure("selected", ("nat", "routes"))
    capsys.readouterr()
    privacy(tmp_path, "status", "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["level"] == "selected" and data["sections"] == ["nat", "routes"] and data["changes"] == 1


def test_unknown_section_is_a_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        privacy(tmp_path, "level", "selected", "--sections", "passwords")
    assert exc.value.code == 2 and "passwords" in capsys.readouterr().err


# -- mcp flags against the folder's level -------------------------------------

@pytest.mark.parametrize("argv,env,view", [
    (["mcp"], {}, None),
    (["mcp", "--strict"], {}, "strict"),
    (["mcp", "--full"], {}, "full"),
    (["mcp", "--level", "none"], {}, "none"),
    (["mcp", "--view", "selected"], {}, "selected"),
    (["mcp"], {"NETCONVERTER_MCP_VIEW": "none"}, "none"),
    (["mcp", "--full"], {"NETCONVERTER_MCP_VIEW": "none"}, "full"),
])
def test_level_flags_parse(monkeypatch, argv, env, view):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.parser().parse_args(argv).view == view


def run_mcp(monkeypatch, tmp_path, argv):
    from netconverter_cli import mcp_server, remote_mcp

    seen = {}

    class FakeRemote:
        def __init__(self, url, credential, client_version=None, view_mode=None):
            seen["header"] = view_mode

        def close(self):
            pass

    def bridge(ws, server, rest, remote, **kw):
        seen.update(level=kw["level"], strict=kw["strict"], workspace_level=kw["workspace_level"])
        return kw

    monkeypatch.setattr(cli, "get_secret", lambda name, prompt=True: "nck_synthetic")
    monkeypatch.setattr(remote_mcp, "RemoteMCP", FakeRemote)
    monkeypatch.setattr(mcp_server, "Bridge", bridge)
    monkeypatch.setattr(mcp_server, "run_stdio", lambda bridge: None)
    cli.run_mcp(cli.parser().parse_args(["--server", "https://api.netconverter.ai/external/v1",
                                         "--workspace", str(tmp_path), *argv]))
    return seen


def raise_folder(tmp_path, monkeypatch, level):
    exposure.set_level(tmp_path, level, interactive=True, ask=lambda prompt: f"raise to {level}")


def test_no_flag_serves_the_folder_level(monkeypatch, tmp_path):
    assert run_mcp(monkeypatch, tmp_path, ["mcp"]) == {
        "header": "masked", "level": "full", "strict": True, "workspace_level": True}
    exposure.set_level(tmp_path, "none", interactive=False)
    assert run_mcp(monkeypatch, tmp_path, ["mcp"])["header"] == "none"


def test_full_flag_cannot_raise_above_the_folder_level(monkeypatch, tmp_path, capsys):
    seen = run_mcp(monkeypatch, tmp_path, ["mcp", "--full"])
    assert seen["header"] == "masked" and seen["strict"] is True
    assert "netconverter privacy level full" in capsys.readouterr().err
    raise_folder(tmp_path, monkeypatch, "full")
    seen = run_mcp(monkeypatch, tmp_path, ["mcp", "--full"])
    assert seen["header"] == "full" and seen["strict"] is False
    assert "full" in capsys.readouterr().err


def test_strict_flag_lowers_a_full_folder_to_masked(monkeypatch, tmp_path):
    raise_folder(tmp_path, monkeypatch, "full")
    assert run_mcp(monkeypatch, tmp_path, ["mcp", "--strict"])["header"] == "masked"
    assert run_mcp(monkeypatch, tmp_path, ["mcp", "--level", "none"])["header"] == "none"


def test_environment_lowers_but_the_flag_wins(monkeypatch, tmp_path):
    raise_folder(tmp_path, monkeypatch, "full")
    monkeypatch.setenv("NETCONVERTER_MCP_VIEW", "none")
    assert run_mcp(monkeypatch, tmp_path, ["mcp"])["header"] == "none"
    assert run_mcp(monkeypatch, tmp_path, ["mcp", "--full"])["header"] == "full"


def test_guided_is_refused_at_level_none(monkeypatch, tmp_path, capsys):
    exposure.set_level(tmp_path, "none", interactive=False)
    with pytest.raises(SystemExit) as exc:
        run_mcp(monkeypatch, tmp_path, ["mcp", "--guided"])
    assert exc.value.code == 2
