"""`netconverter connect openclaw` (#14, basic): through OpenClaw's own `openclaw mcp` CLI.

OpenClaw keeps MCP servers under ``mcp.servers`` in ``~/.openclaw/openclaw.json``
(JSON5). The file is never hand-edited here: ``openclaw mcp add`` writes the
entry, ``openclaw mcp doctor <name> --probe`` checks the bridge starts, and
``openclaw mcp unset`` removes it (docs.openclaw.ai/cli/mcp/registry). Without
``openclaw`` on PATH the JSON5 block is shown for a manual paste.

The stdio command runs where the OpenClaw **Gateway** runs, so ``netconverter``
must be installed and signed in on that host. OpenClaw agents have their own
file tools, so the workspace folder should also be denied to them by OpenClaw
tool policy; that step is shown, not applied.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

SERVER_NAME = "netconverter"


def config_path() -> Path:
    return Path.home() / ".openclaw" / "openclaw.json"


def installed() -> bool:
    return bool(shutil.which("openclaw")) or (Path.home() / ".openclaw").exists()


def current_entry():
    """``mcp.servers.netconverter`` from openclaw.json; None if absent or unreadable (JSON5)."""
    try:
        text = config_path().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        # JSON5 (comments, bare keys): a strict parser is not bundled; drop comments and retry.
        stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
        stripped = re.sub(r"([{,]\s*)([A-Za-z_][\w-]*)\s*:", r'\1"\2":', stripped)
        stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
        try:
            data = json.loads(stripped)
        except ValueError:
            return None
    servers = ((data or {}).get("mcp") or {}).get("servers") if isinstance(data, dict) else None
    entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    return entry if isinstance(entry, dict) else None


def json5_block(exe: str, args: list[str]) -> str:
    return ("// ~/.openclaw/openclaw.json (merge into the existing file)\n{\n  mcp: {\n    servers: {\n"
            f"      {SERVER_NAME}: {{ command: {json.dumps(exe)}, args: {json.dumps(args)} }},\n"
            "    },\n  },\n}")


def _run(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or f"{' '.join(argv[:3])} failed").strip()[:300])
    return (done.stdout or "").strip()


def deny_step(change_cls, root: Path):
    root = Path(root).resolve()
    steps = (f"OpenClaw agents have their own file and exec tools. Deny them {root} in OpenClaw's tool "
             "policy (Gateway config), so configurations reach NetConverter only through the bridge, "
             "by path. Then restart the Gateway.")
    return change_cls("openclaw-deny", "OpenClaw file access", "OpenClaw tool policy",
                      "Keep OpenClaw's own file tools out of this folder (a manual step).",
                      f"Deny path: {root}/**", can_apply=False, manual=steps)


def plan(change_cls, root: Path, exe: str, args: list[str]):
    found = shutil.which("openclaw")
    key, title = "openclaw", "OpenClaw"
    add = ["openclaw", "mcp", "add", SERVER_NAME, "--command", exe]
    for arg in args:
        add += ["--arg", arg]
    block = json5_block(exe, args)
    gateway = ("The command runs on the OpenClaw Gateway host: netconverter must be installed "
               "and signed in there.")
    if not found:
        return change_cls(key, title, str(config_path()), "openclaw is not on PATH; add the block by hand. "
                          + gateway, block, can_apply=False,
                          manual=f"Merge the block above into {config_path()} on the Gateway host, then "
                                 f"run `openclaw mcp doctor {SERVER_NAME} --probe`.")
    entry = current_entry()
    if entry == {"command": exe, "args": args} or (
            isinstance(entry, dict) and entry.get("command") == exe and entry.get("args") == args):
        return change_cls(key, title, "OpenClaw", f"OpenClaw already has '{SERVER_NAME}' for this folder.",
                          " ".join(add), can_apply=False, manual="Nothing to change.")
    replace = entry is not None
    steps = ([["openclaw", "mcp", "unset", SERVER_NAME]] if replace else []) + [add]

    def apply() -> str:
        for argv in steps:
            _run([found, *argv[1:]])
        probe = _run([found, "mcp", "doctor", SERVER_NAME, "--probe"])
        return ("OpenClaw: added the netconverter MCP server (strict view). "
                + (f"Probe: {probe[:300]}" if probe else "Probe passed."))
    summary = (f"Adds the '{SERVER_NAME}' MCP server for this folder with `openclaw mcp add`, then probes it. "
               if not replace else
               f"Replaces OpenClaw's existing '{SERVER_NAME}' entry (`openclaw mcp unset`, then "
               "`openclaw mcp add`), then probes it. ") + gateway
    return change_cls(key, title, "OpenClaw (openclaw mcp)", summary,
                      "\n".join(" ".join(argv) for argv in steps), apply=apply,
                      followups=[deny_step(change_cls, root)])


def plan_remove(change_cls):
    found = shutil.which("openclaw")
    argv = ["openclaw", "mcp", "unset", SERVER_NAME]
    entry = current_entry()
    ours = isinstance(entry, dict) and Path(str(entry.get("command", ""))).name == "netconverter"
    if not ours:
        return change_cls("openclaw", "OpenClaw", "OpenClaw",
                          f"OpenClaw has no netconverter '{SERVER_NAME}' entry to remove.", " ".join(argv),
                          can_apply=False, manual="Nothing to change.")
    if not found:
        return change_cls("openclaw", "OpenClaw", str(config_path()), "openclaw is not on PATH.",
                          " ".join(argv), can_apply=False,
                          manual=f"Run the command above on the Gateway host, or delete mcp.servers.{SERVER_NAME} "
                                 f"from {config_path()}.")

    def apply() -> str:
        _run([found, *argv[1:]])
        return f"OpenClaw: removed the '{SERVER_NAME}' MCP server. Restart the Gateway."
    return change_cls("openclaw", "OpenClaw", "OpenClaw (openclaw mcp)",
                      f"Removes OpenClaw's '{SERVER_NAME}' MCP server with `openclaw mcp unset`.",
                      " ".join(argv), apply=apply)
