"""#13 / MCP-C4: `netconverter privacy apply --client X` keeps a client's own file tools out of the folder.

Claude Code, Cursor CLI and Gemini CLI get rules written (diff first, yes required,
idempotent, .bak kept). Codex and OpenClaw get printed guidance: applying there
would change the client's active sandbox profile or agent policy. These tests
prove the files written, not that a live client enforces them.
"""

import json
import tomllib

import pytest

from netconverter_cli import cli, connect, privacy_apply


@pytest.fixture
def home(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(connect.Path, "home", lambda: home_dir)
    work = tmp_path / "migrations"
    work.mkdir()
    return home_dir, work


def apply(work, client, *extra, answer="y"):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return answer

    args = cli.parser().parse_args(["--workspace", str(work), "privacy", "apply", "--client", client, *extra])
    from netconverter_cli.privacy_cli import run

    return run(args, ask=ask), asked


def test_claude_code_rules_shown_then_applied_after_yes_with_backup(home, capsys):
    home_dir, work = home
    settings = home_dir / ".claude" / "settings.json"
    settings.parent.mkdir()
    original = {"model": "x", "permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read(//opt/**)"]}}
    settings.write_text(json.dumps(original))
    read_rule, edit_rule = connect.read_deny_rule(work.resolve()), connect.edit_deny_rule(work.resolve())
    assert read_rule == f"Read(/{work.resolve().as_posix()}/**)" and edit_rule.startswith("Edit(//")

    code, asked = apply(work, "claude-code", answer="n")
    out = capsys.readouterr().out
    assert code == 0 and asked and "Nothing was changed" in out
    assert f'+      "{read_rule}"' in out and f'+      "{edit_rule}"' in out  # the diff
    assert json.loads(settings.read_text()) == original

    code, _ = apply(work, "claude-code", answer="y")
    data = json.loads(settings.read_text())
    assert code == 0
    assert data["permissions"]["deny"] == ["Bash(rm:*)", read_rule, edit_rule]
    assert data["model"] == "x" and data["permissions"]["allow"] == ["Read(//opt/**)"]
    assert json.loads((settings.parent / "settings.json.bak").read_text()) == original
    out = capsys.readouterr().out
    assert "Bash" in out  # shell guidance: a deny rule cannot cover every shell command

    before = settings.read_text()
    code, asked = apply(work, "claude-code")
    assert code == 0 and not asked and settings.read_text() == before  # idempotent
    assert "already" in capsys.readouterr().out


def test_print_only_changes_nothing(home, capsys):
    home_dir, work = home
    code, asked = apply(work, "claude-code", "--print")
    assert code == 0 and not asked
    assert not (home_dir / ".claude" / "settings.json").exists()
    assert "Read(" in capsys.readouterr().out


def test_the_home_folder_is_never_denied(home, monkeypatch, capsys):
    home_dir, _ = home
    code, asked = apply(home_dir, "claude-code")
    assert code == 1 and not asked and "home folder" in capsys.readouterr().out


def test_cursor_cli_permissions_merged_and_idempotent(home, capsys):
    home_dir, work = home
    config = home_dir / ".cursor" / "cli-config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"version": 1, "permissions": {"allow": ["Shell(git)"], "deny": []}}))
    code, _ = apply(work, "cursor")
    data = json.loads(config.read_text())
    root = work.resolve().as_posix()
    assert code == 0
    assert data["permissions"]["deny"] == [f"Read({root}/**)", f"Write({root}/**)"]
    assert data["permissions"]["allow"] == ["Shell(git)"] and data["version"] == 1
    assert (config.parent / "cli-config.json.bak").exists()
    out = capsys.readouterr().out
    assert ".cursorignore" in out and "Shell(cat)" in out
    before = config.read_text()
    code, asked = apply(work, "cursor")
    assert code == 0 and not asked and config.read_text() == before


def test_cursor_without_cursor_installed_is_guidance(home, capsys):
    home_dir, work = home
    code, _ = apply(work, "cursor")
    assert code == 1 and not (home_dir / ".cursor").exists()


def test_gemini_policy_file_written_once(home, capsys):
    home_dir, work = home
    code, asked = apply(work, "gemini")
    files = list((home_dir / ".gemini" / "policies").glob("netconverter-*.toml"))
    assert code == 0 and asked and len(files) == 1
    policy = tomllib.loads(files[0].read_text())
    tools = {rule["toolName"] for rule in policy["rule"]}
    assert {"read_file", "read_many_files", "write_file", "replace", "run_shell_command"} <= tools
    assert all(rule["decision"] == "deny" for rule in policy["rule"])
    assert all(work.resolve().as_posix().replace(".", "\\.") in rule["argsPattern"] or
               work.resolve().as_posix() in rule["argsPattern"] for rule in policy["rule"])
    assert ".geminiignore" in capsys.readouterr().out
    before = files[0].read_text()
    code, asked = apply(work, "gemini")
    assert code == 0 and not asked and files[0].read_text() == before


@pytest.mark.parametrize("client,needles", [
    ("codex", ['default_permissions', '= "deny"', ':workspace']),
    ("openclaw", ["workspaceOnly", "workspaceAccess", '"read"', '"exec"']),
])
def test_codex_and_openclaw_get_guidance_and_nothing_is_written(home, capsys, client, needles):
    home_dir, work = home
    code, asked = apply(work, client)
    out = capsys.readouterr().out
    assert code == 0 and not asked
    for needle in needles:
        assert needle in out
    assert str(work.resolve()) in out
    assert not any(home_dir.iterdir())


def test_every_client_warns_against_starting_it_in_the_folder(home, capsys):
    _, work = home
    for client in privacy_apply.CLIENTS:
        apply(work, client, "--print")
        assert "outside" in capsys.readouterr().out
