"""`netconverter walkthrough` and the TUI's /walkthrough show the same tour."""
import re

import pytest
from rich.console import Console

from netconverter_cli import cli, walkthrough
from netconverter_cli.presentation import help_view, walkthrough_view


def _text(renderable, width=80):
    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_every_step_fits_an_80_column_terminal():
    for index in range(len(walkthrough.STEPS)):
        for line in walkthrough.render_text(index).splitlines():
            assert len(line) <= 80, line


def test_tour_names_the_integrations_and_the_license():
    text = "\n".join(walkthrough.render_text(i) for i in range(len(walkthrough.STEPS)))
    for needle in ("netconverter connect claude-code", "cursor", "codex", "chatgpt",
                   "netconverter login --clerk", "netconverter license show"):
        assert needle in text


def test_commands_shown_are_real_subcommands():
    known = set(cli.parser()._subparsers._group_actions[0].choices)
    for _, lines in walkthrough.STEPS:
        for line in lines:
            if line.startswith("$ netconverter "):
                first = line[2:].split()[1]
                if not first.startswith("-"):  # `netconverter --workspace DIR` opens the app
                    assert first in known, line


def test_cli_prints_all_steps_without_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["walkthrough"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert len(re.findall(r"Step \d of \d", out)) == len(walkthrough.STEPS)


def test_cli_one_step_and_a_bad_step(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["walkthrough", "5"])
    assert exc.value.code == 0
    assert "Step 5 of" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["walkthrough", "99"])
    assert exc.value.code == 2


def test_interactive_tour_stops_on_q(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    out = []
    answers = iter(["", "q"])

    class Args:
        step = None
        all = False

    assert walkthrough.run(Args(), ask=lambda _: next(answers), out=out.append) == 0
    assert sum(line.startswith("Step ") for line in out) == 2  # Enter showed step 2; q stopped


def test_tui_card_and_help_entry():
    first = _text(walkthrough_view(0))
    assert "Walkthrough 1/" in first and "/walkthrough 2 for the next step" in first
    last = _text(walkthrough_view(len(walkthrough.STEPS) - 1))
    assert "That is the tour" in last
    assert "/walkthrough" in _text(help_view(), width=110)
