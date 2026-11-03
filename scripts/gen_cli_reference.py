"""Write docs/CLI_REFERENCE.md from the real argparse definitions.

Usage: python scripts/gen_cli_reference.py          (rewrite the file)
       python scripts/gen_cli_reference.py --check  (exit 1 when it is out of date)

Every command, sub-command, argument and option comes from ``netconverter_cli.cli.parser()``;
only the examples and the short notes below are written by hand. A test fails when the
checked-in file differs, or when a command has no help text or no example.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Defaults must not depend on the caller's shell (several come from these variables).
for _name in ("NETCONVERTER_MCP_VIEW", "NETCONVERTER_MCP_AUTH", "NETCONVERTER_AUTH",
              "NETCONVERTER_MCP_URL", "NETCONVERTER_MCP_UPLOAD_CONFIRM"):
    os.environ.pop(_name, None)
os.environ["COLUMNS"] = "100"

from netconverter_cli import __version__, cli  # noqa: E402

OUT = ROOT / "docs" / "CLI_REFERENCE.md"

# One or more examples per command path (synthetic file names and ids only).
EXAMPLES = {
    "netconverter": ["netconverter                      # the full-screen app in this folder",
                     "netconverter --workspace ~/migrations jobs",
                     "netconverter --version"],
    "run": ["netconverter run"],
    "license": ["netconverter license show", "netconverter license accept", "netconverter license status"],
    "walkthrough": ["netconverter walkthrough", "netconverter walkthrough 3", "netconverter walkthrough --all"],
    "login": ["netconverter login --clerk              # browser sign-in with your NetConverter account",
              "netconverter login --clerk --device     # headless: shows a code to enter on another device",
              "netconverter login                      # paste an API key (nck_…); stored, never echoed",
              "netconverter login --clerk --store file # passphrase-encrypted file instead of the OS keyring"],
    "logout": ["netconverter logout", "netconverter logout --all"],
    "whoami": ["netconverter whoami"],
    "mcp": ["netconverter mcp --workspace ~/migrations                 # what an AI assistant runs",
            "netconverter mcp --workspace ~/migrations --level masked  # serve at most masked",
            "netconverter mcp --workspace ~/migrations --auth key      # use the stored API key",
            "netconverter mcp --workspace ~/migrations --no-upload-confirm"],
    "connect": ["netconverter connect                    # list assistants and their state",
                "netconverter connect claude-code",
                "netconverter connect codex              # also the ChatGPT desktop app's agent",
                "netconverter connect chatgpt            # hosted-connector steps (and the desktop-agent pointer)",
                "netconverter connect cursor --print     # show the change only",
                "netconverter connect --all"],
    "update": ["netconverter update --check", "netconverter update", "netconverter update --check --json"],
    "capabilities": ["netconverter capabilities"],
    "draft": ["netconverter draft catalog"],
    "draft catalog": ["netconverter draft catalog"],
    "draft context": ["netconverter draft context DRAFT_ID --revision 1 --view-id interfaces --limit 50"],
    "draft prepare": ["netconverter draft prepare asa.cfg --vendor cisco_asa --to palo_alto_set "
                      "--workflow studio --idempotency-key prepare-001"],
    "draft decisions": ["netconverter draft decisions DRAFT_ID --revision 1"],
    "draft export": ["netconverter draft export DRAFT_ID --revision 1"],
    "draft import": ["netconverter draft import DRAFT_ID --revision 1 --yaml DRAFT_ID.revision-1.yaml "
                     "--idempotency-key import-001"],
    "draft propose": ["netconverter draft propose DRAFT_ID --revision 2 --changes '[...]' "
                      "--idempotency-key propose-001"],
    "draft validate": ["netconverter draft validate DRAFT_ID --revision 2 --idempotency-key validate-001"],
    "draft review": ["netconverter draft review DRAFT_ID --revision 2 --idempotency-key review-001"],
    "draft execute": ["netconverter draft execute DRAFT_ID --revision 2 --approval-ref APPROVAL_REF "
                      "--idempotency-key execute-001"],
    "draft job-status": ["netconverter draft job-status JOB_ID --draft-id DRAFT_ID --revision 2"],
    "draft download-result": ["netconverter draft download-result JOB_ID --draft-id DRAFT_ID --revision 2 "
                              "--artifact-id ARTIFACT_ID --manifest-revision 1"],
    "project": ["netconverter project schema"],
    "project schema": ["netconverter project schema"],
    "project get": ["netconverter project get PROJECT_ID --revision 1"],
    "project prepare": ["netconverter project prepare --devices '[...]' --links '[...]' "
                        "--idempotency-key project-001"],
    "project propose": ["netconverter project propose PROJECT_ID --expected-revision 1 --devices '[...]' "
                        "--links '[...]' --idempotency-key project-002"],
    "privacy": ["netconverter privacy"],
    "privacy status": ["netconverter privacy status", "netconverter privacy status --json"],
    "privacy level": ["netconverter privacy level full       # asks you to type \"raise to full\"",
                      "netconverter privacy level masked     # lowering needs no confirmation",
                      "netconverter privacy level selected --sections nat,routes"],
    "privacy apply": ["netconverter privacy apply --client claude-code",
                      "netconverter privacy apply --client codex --print"],
    "setup": ["netconverter setup"],
    "jobs": ["netconverter jobs"],
    "resume": ["netconverter resume", "netconverter resume tra_0123456789ab --all"],
    "validate": ["netconverter validate edge-fw.cfg --vendor cisco_asa",
                 "netconverter validate edge-fw.cfg --vendor fortinet --json"],
    "analyze": ["netconverter analyze edge-fw.cfg --vendor cisco_asa"],
    "optimize": ["netconverter optimize edge-fw.cfg --vendor palo_alto_xml"],
    "convert": ["netconverter convert edge-fw.cfg --vendor cisco_asa --to palo_alto_xml",
                "netconverter convert edge-fw.cfg --vendor cisco_asa --to palo_alto_set "
                "--options '{\"panos_target_version\":\"11.2\"}'"],
    "ask": ["netconverter --provider anthropic ask \"Which rules allow tcp/22 from outside?\""],
    "query": ["netconverter query nat", "netconverter query dependencies --arguments '{\"object_name\":\"WEB-SRV\"}'"],
    "download": ["netconverter download"],
    "allowance": ["netconverter allowance"],
    "model-test": ["netconverter --provider ollama --model qwen2.5 model-test"],
    "plain": ["netconverter plain", "netconverter plain '/jobs'"],
}

# A line of context where the option list alone does not say what a command is for.
NOTES = {
    "login": "Two kinds of credential: **`--clerk`** signs you in with your NetConverter account "
             "(OAuth in the browser, or `--device` on a headless machine); without it, `login` stores an "
             "**API key** (`nck_…`) issued to you or your organisation. Either is kept in the OS keyring, "
             "or with `--store file` in a passphrase-encrypted file. See the "
             "[guide](GUIDE.md#sign-in-and-credentials).",
    "mcp": "Started by an AI assistant, not by you: it speaks MCP over stdio. The assistant passes file "
           "**paths**; the bridge uploads the file itself. What the assistant may see is this folder's "
           "exposure level (`privacy`); `--level` can only lower it. See the "
           "[guide](GUIDE.md#ai-assistants-and-the-mcp-bridge).",
    "connect": "Writes the assistant's MCP settings so it starts `netconverter mcp` for this folder "
               "(`chatgpt` and `claude-ai` print hosted-connector steps instead).",
    "privacy": "The **exposure level** decides what an AI assistant sees from this folder's jobs. "
               "See the [guide](GUIDE.md#privacy-and-exposure-levels).",
    "privacy level": "Raising a level asks you to type a phrase in a terminal, so no assistant can raise it; "
                     "every change is recorded in `.netconverter/privacy-audit.jsonl`.",
    "draft": "Development preview of the revisioned draft contract ([guided-workflows.md](guided-workflows.md)); "
             "prints JSON.",
    "project": "Development preview: candidate multi-device projects built from drafts; no project execution.",
    "convert": "Uploads the file and converts it in one step. For a guided migration (prescan, then your "
               "decisions, then the conversion) use an AI assistant with the bridge "
               "([guide](GUIDE.md#guided-migration-prescan-decisions-conversion)), or Quick Convert / "
               "Conversion Studio in the portal.",
}

HEADER = f"""# CLI reference — netconverter {__version__}

Generated from the command definitions by `scripts/gen_cli_reference.py`; do not edit by hand.
What the concepts mean (sign-in, exposure levels, the MCP bridge, guided migration, error codes):
[GUIDE.md](GUIDE.md). Settings, environment variables and bridge tools: [COMMANDS.md](COMMANDS.md).

Global options go **before** the command: `netconverter --workspace DIR --server URL COMMAND …`.
"""


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            for name, sub in action.choices.items():
                yield name, sub, helps.get(name)


def _commands(parser, path=()):
    """(path, parser, help) for every command, depth first, in definition order."""
    for name, sub, text in _subparsers(parser):
        yield (*path, name), sub, text
        yield from _commands(sub, (*path, name))


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _default(action) -> str:
    if isinstance(action, (argparse._StoreConstAction, argparse._StoreFalseAction, argparse._VersionAction)):
        return ""  # flags; a default from the environment is stated in the help text
    value = action.default
    if value in (None, False, argparse.SUPPRESS, "") or value == {}:
        return ""
    return f"`{value}`"


def _arguments(parser) -> list[str]:
    rows = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) or action.help == argparse.SUPPRESS:
            continue
        if action.option_strings:
            name = ", ".join(f"`{o}`" for o in action.option_strings)
            if action.nargs != 0 and not isinstance(action, argparse._VersionAction):
                name += f" `{action.metavar or action.dest.upper()}`"
        else:
            name = f"`{action.metavar or action.dest}`" + (" (optional)" if action.nargs in ("?", "*") else "")
        meaning = _cell(action.help or "")
        meaning = meaning[:1].upper() + meaning[1:]
        if meaning and not meaning.endswith((".", ")")):
            meaning += "."
        if action.choices:
            meaning += (" " if meaning else "") + "Choices: " + ", ".join(f"`{c}`" for c in action.choices) + "."
        if getattr(action, "required", False) and action.option_strings:
            meaning = "**Required.** " + meaning
        rows.append(f"| {name} | {meaning} | {_default(action)} |")
    if not rows:
        return ["No options besides `-h`/`--help`."]
    return ["| Argument / option | Meaning | Default |", "| --- | --- | --- |", *rows]


def _usage(parser) -> str:
    return " ".join(parser.format_usage().replace("usage: ", "").split())


def render() -> str:
    root = cli.parser()
    commands = list(_commands(root))
    lines = [HEADER, "## Contents", ""]
    for path, _, text in commands:
        indent = "  " * (len(path) - 1)
        lines.append(f"{indent}- [`netconverter {' '.join(path)}`](#netconverter-{'-'.join(path)}) — {_cell(text or '')}")
    lines += ["", "## Global options", "", "```", _usage(root), "```", "", *_arguments(root), "",
              "Examples:", "", "```sh", *EXAMPLES["netconverter"], "```", ""]
    for path, sub, text in commands:
        key = " ".join(path)
        heading = "##" if len(path) == 1 else "###"
        text = _cell(text or "")
        lines += [f'{heading} <a id="netconverter-{"-".join(path)}"></a>`netconverter {key}`', "",
                  text[:1].upper() + text[1:] + ("" if text.endswith(".") else "."), ""]
        if key in NOTES:
            lines += [NOTES[key], ""]
        lines += ["```", _usage(sub), "```", "", *_arguments(sub), ""]
        lines += ["Example" + ("s" if len(EXAMPLES[key]) > 1 else "") + ":", "", "```sh", *EXAMPLES[key], "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def missing() -> list[str]:
    """Commands without a help text or an example (the test keeps this empty)."""
    out = []
    for path, _, text in _commands(cli.parser()):
        key = " ".join(path)
        if not text:
            out.append(f"{key}: no help text")
        if key not in EXAMPLES:
            out.append(f"{key}: no example")
    return out


def main(argv) -> int:
    text = render()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python scripts/gen_cli_reference.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
