"""Wire an AI assistant to the local bridge (`netconverter mcp`) for one folder.

Every change is shown first and applied only after an explicit yes. Reading a
client's config to see whether it is already connected never modifies it. An
edited JSON file keeps a ``.bak`` copy of what it replaced; Claude Code is
changed only through its own ``claude mcp add`` command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SERVER_NAME = "netconverter"


def executable() -> str:
    found = shutil.which("netconverter")
    if found:
        return str(Path(found).resolve())
    script = Path(sys.argv[0])
    return str(script.resolve()) if script.name == "netconverter" and script.exists() else "netconverter"


def _args(root: Path) -> list[str]:
    return ["mcp", "--workspace", str(root)]


def _is_ours(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command", ""))
    args = entry.get("args") or []
    return Path(command).name == "netconverter" and bool(args) and args[0] == "mcp"


def _read_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, name = tempfile.mkstemp(prefix=".nc-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class Change:
    key: str
    title: str
    where: str
    summary: str
    preview: str
    can_apply: bool = True
    manual: str = ""
    apply: Callable[[], str] = field(default=lambda: "")


@dataclass
class ClientSpec:
    title: str
    configured: Callable[[], bool]


def _claude_configured() -> bool:
    data = _read_json(Path.home() / ".claude.json") or {}
    scopes = [data.get("mcpServers") or {}]
    scopes += [(p or {}).get("mcpServers") or {} for p in (data.get("projects") or {}).values()
               if isinstance(p, dict)]
    return any(_is_ours(entry) for scope in scopes if isinstance(scope, dict) for entry in scope.values())


def _cursor_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _cursor_configured() -> bool:
    data = _read_json(_cursor_path()) or {}
    return any(_is_ours(e) for e in (data.get("mcpServers") or {}).values())


def _codex_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _codex_servers() -> dict:
    try:
        return tomllib.loads(_codex_path().read_text(encoding="utf-8")).get("mcp_servers") or {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _codex_configured() -> bool:
    return any(_is_ours(e) for e in _codex_servers().values())


def _vscode_configured(root: Path | None = None) -> bool:
    data = _read_json((root or Path.cwd()) / ".vscode" / "mcp.json") or {}
    return any(_is_ours(e) for e in (data.get("servers") or {}).values())


CLIENTS = {
    "claude-code": ClientSpec("Claude Code", _claude_configured),
    "cursor": ClientSpec("Cursor", _cursor_configured),
    "vscode": ClientSpec("VS Code", _vscode_configured),
    "codex": ClientSpec("Codex CLI", _codex_configured),
}


def plan(key: str, root: Path) -> Change:
    root = Path(root).resolve()
    exe = executable()
    if key == "claude-code":
        argv = ["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", exe, *_args(root)]
        found = shutil.which("claude")

        def run() -> str:
            done = subprocess.run([found, *argv[1:]], capture_output=True, text=True, timeout=60)
            if done.returncode != 0:
                raise RuntimeError((done.stderr or done.stdout or "claude mcp add failed").strip()[:300])
            return "Claude Code: restart it or run /mcp to see the netconverter tools."
        return Change(key, "Claude Code", "Claude Code (user scope)",
                      f"Adds the '{SERVER_NAME}' MCP server for this folder.",
                      " ".join(argv), can_apply=bool(found),
                      manual="Claude Code is not on PATH. Run the command above in a terminal where it is.",
                      apply=run)
    if key == "cursor":
        path = _cursor_path()
        data = _read_json(path)
        entry = {"command": exe, "args": _args(root)}
        preview = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)
        if data is None:
            return Change(key, "Cursor", str(path), "Cursor's mcp.json is not valid JSON; edit it by hand.",
                          preview, can_apply=False, manual=f"Add the block above to {path}.")

        def write() -> str:
            servers = data.setdefault("mcpServers", {})
            servers[SERVER_NAME] = entry
            _write_json(path, data)
            return f"Updated {path}. Cursor picks it up after a reload."
        return Change(key, "Cursor", str(path), f"Sets mcpServers.{SERVER_NAME} in {path}.", preview, apply=write)
    if key == "vscode":
        path = root / ".vscode" / "mcp.json"
        data = _read_json(path)
        entry = {"type": "stdio", "command": exe, "args": _args(root)}
        preview = json.dumps({"servers": {SERVER_NAME: entry}}, indent=2)
        if data is None:
            return Change(key, "VS Code", str(path), "This folder's .vscode/mcp.json is not valid JSON.",
                          preview, can_apply=False, manual=f"Add the block above to {path}.")

        def write() -> str:
            data.setdefault("servers", {})[SERVER_NAME] = entry
            _write_json(path, data)
            return f"Updated {path}. Open this folder in VS Code and start the server from MCP: List Servers."
        return Change(key, "VS Code", str(path), f"Sets servers.{SERVER_NAME} in this folder's .vscode/mcp.json.",
                      preview, apply=write)
    if key == "codex":
        path = _codex_path()
        block = (f"\n[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(exe)}\n"
                 f"args = {json.dumps(_args(root))}\n")
        if SERVER_NAME in _codex_servers():
            return Change(key, "Codex CLI", str(path), f"{path} already has [mcp_servers.{SERVER_NAME}].",
                          block.strip(), can_apply=False,
                          manual=f"Edit that table in {path} if it should point at this folder.")

        def append() -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                shutil.copy2(path, path.with_name(path.name + ".bak"))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(block)
            return f"Appended [mcp_servers.{SERVER_NAME}] to {path}. Restart Codex."
        return Change(key, "Codex CLI", str(path), f"Appends [mcp_servers.{SERVER_NAME}] to {path}.",
                      block.strip(), apply=append)
    raise ValueError(f"Unknown AI client {key!r}; choose one of {', '.join(CLIENTS)}")


def configured_clients(root: Path | None = None) -> list[str]:
    out = []
    for key, spec in CLIENTS.items():
        try:
            ok = _vscode_configured(root) if key == "vscode" else spec.configured()
        except Exception:
            ok = False
        if ok:
            out.append(spec.title)
    return out
