"""License acceptance: the client runs only after the user accepts its license.

Acceptance is recorded once per user and license version in the per-user
config folder (never the workspace, which travels with a shared folder).
``NETCONVERTER_ACCEPT_LICENSE=1`` accepts for one process, for CI, containers
and headless hosts that cannot answer a prompt; it is not recorded.
"""

import json
import os
import sys
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from . import __version__

LICENSE_VERSION = "1.0"
ENV_ACCEPT = "NETCONVERTER_ACCEPT_LICENSE"
# Commands that must work before acceptance: reading the license, the tour and updating.
EXEMPT = frozenset({"license", "walkthrough", "update"})
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # as mcp_server

SUMMARY = """NetConverter Terminal Client License (version {version})
Copyright (c) 2026 ValeronLabs LLC. All rights reserved.

You may install and run this client to use NetConverter with your own
NetConverter account, for your own business. You may not copy, share,
redistribute, resell, modify or reverse its security or usage limits.
The source may be readable for transparency; that grants no other rights.
The client is provided as is, without warranty.

Read the full text: netconverter license show"""

NOT_ACCEPTED = ("The NetConverter license has not been accepted on this computer. "
                "Run `netconverter license` in a terminal to read and accept it "
                f"(or set {ENV_ACCEPT}=1 for an unattended install), then retry.")


def config_dir() -> Path:
    """The per-user config folder (never the workspace)."""
    override = os.getenv("NETCONVERTER_CONFIG_HOME")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "netconverter"
    if os.name == "nt":
        base = os.getenv("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "netconverter"
    base = os.getenv("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "netconverter"


def _record() -> Path:
    return config_dir() / "license.json"


def full_text() -> str:
    """The LICENSE shipped with this package, or the summary when it is missing."""
    try:
        return resources.files(__package__).joinpath("LICENSE").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        here = Path(__file__).resolve()
        for candidate in (here.parent / "LICENSE", here.parents[2] / "LICENSE"):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
    return SUMMARY.format(version=LICENSE_VERSION)


def recorded() -> dict | None:
    try:
        data = json.loads(_record().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def accepted() -> bool:
    if os.getenv(ENV_ACCEPT, "").strip().lower() in {"1", "true", "yes"}:
        return True
    data = recorded()
    return bool(data) and data.get("license_version") == LICENSE_VERSION


def accept() -> Path:
    path = _record()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {"license_version": LICENSE_VERSION, "client_version": __version__,
               "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def status() -> dict:
    data = recorded() or {}
    via_env = os.getenv(ENV_ACCEPT, "").strip().lower() in {"1", "true", "yes"}
    return {"license_version": LICENSE_VERSION, "accepted": accepted(),
            "accepted_at": data.get("accepted_at") if data.get("license_version") == LICENSE_VERSION else None,
            "accepted_via_environment": via_env and data.get("license_version") != LICENSE_VERSION}


def prompt(ask=input, out=print) -> bool:
    """Show the summary and ask for a typed `accept`. Returns True once accepted."""
    out(SUMMARY.format(version=LICENSE_VERSION))
    out("")
    try:
        answer = ask("Type 'accept' to accept the license, or press Enter to quit: ")
    except (EOFError, KeyboardInterrupt):
        out("")
        return False
    if answer.strip().lower() != "accept":
        return False
    accept()
    out("License accepted. Thank you.")
    return True


def ensure(command: str | None, *, interactive: bool, ask=input, out=print) -> None:
    """Gate every command except EXEMPT; raises SystemExit when not accepted."""
    if command in EXEMPT or accepted():
        return
    if interactive and prompt(ask, out):
        return
    raise SystemExit(f"netconverter: {NOT_ACCEPTED}")


def blocked_mcp_reply(message):
    """One JSON-RPC reply from a bridge that cannot run until the license is accepted.

    An AI client starts the bridge without a terminal, so it cannot prompt. It
    answers initialize and lists one tool whose result tells the assistant what
    the user must do, instead of exiting with nothing the user would see.
    """
    if not isinstance(message, dict) or "id" not in message:
        return None
    request_id, method = message.get("id"), message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "netconverter-local", "version": __version__},
            "instructions": NOT_ACCEPTED}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [{
            "name": "license_status",
            "description": "Explains why NetConverter is not available yet: its license must be accepted in a terminal.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "openWorldHint": False}}]}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": NOT_ACCEPTED}], "isError": True}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}


def serve_blocked_mcp(stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    print(f"netconverter mcp: {NOT_ACCEPTED}", file=sys.stderr)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = blocked_mcp_reply(message)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def run(args, ask=input, out=print) -> int:
    """`netconverter license [show|accept|status]`."""
    action = getattr(args, "license_action", None) or "review"
    if action == "show":
        out(full_text())
        return 0
    if action == "status":
        out(json.dumps(status(), sort_keys=True))
        return 0
    if action == "accept":
        if not sys.stdin.isatty() and not getattr(args, "yes", False):
            out(f"netconverter: run `netconverter license accept` in an interactive terminal, "
                f"pass --yes to accept non-interactively, or set {ENV_ACCEPT}=1.")
            return 2
        if getattr(args, "yes", False):
            out(SUMMARY.format(version=LICENSE_VERSION))
            accept()
            out("License accepted.")
            return 0
        return 0 if prompt(ask, out) else 1
    # review: show where things stand and offer to accept
    if accepted():
        out(SUMMARY.format(version=LICENSE_VERSION))
        out("")
        out("You have accepted this license. `netconverter license show` prints the full text.")
        return 0
    if not sys.stdin.isatty():
        out(SUMMARY.format(version=LICENSE_VERSION))
        out("")
        out(f"Not accepted yet. Run `netconverter license` in an interactive terminal, or set {ENV_ACCEPT}=1.")
        return 1
    return 0 if prompt(ask, out) else 1
