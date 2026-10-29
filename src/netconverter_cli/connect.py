"""Wire an AI assistant to the local bridge (`netconverter mcp`) for one folder.

Every change is shown first and applied only after an explicit yes. Reading a
client's config to see whether it is already connected never modifies it. An
edited JSON file keeps a ``.bak`` copy of what it replaced; Claude Code's MCP
entry is changed only through its own ``claude mcp add`` command.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

SERVER_NAME = "netconverter"


def executable() -> str:
    found = shutil.which("netconverter")
    if found:
        return str(Path(found).resolve())
    script = Path(sys.argv[0])
    return str(script.resolve()) if script.name == "netconverter" and script.exists() else "netconverter"


def _args(root: Path) -> list[str]:
    # Strict view, written explicitly for every client (#11): an environment that
    # sets NETCONVERTER_MCP_VIEW=full cannot widen what a connected assistant sees.
    return ["mcp", "--workspace", str(root), "--strict"]


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
    # Optional extra changes offered after this one applies, each with its own prompt.
    followups: list = field(default_factory=list)
    default_yes: bool = False


def _diff(path: Path, before, after: dict) -> str:
    """A unified diff of a JSON file's change (before=None for a new file)."""
    old = [] if before is None else (json.dumps(before, indent=2) + "\n").splitlines(keepends=True)
    new = (json.dumps(after, indent=2) + "\n").splitlines(keepends=True)
    label = str(path)
    text = "".join(difflib.unified_diff(old, new, "/dev/null" if before is None else label, label))
    return text.rstrip("\n") or "(no change)"


@dataclass
class ClientSpec:
    title: str
    configured: Callable[[], bool]
    # "local" clients start the bridge themselves; "remote" ones (ChatGPT, claude.ai)
    # can only reach an HTTPS MCP server, so connect prints their setup steps.
    kind: str = "local"
    installed: Callable[[], bool] = lambda: True


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


def _platform() -> str:
    return sys.platform


def _desktop_path() -> Path | None:
    """Claude Desktop's config file; None where Claude Desktop does not run."""
    platform = _platform()
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if platform == "win32":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    return None


def _desktop_configured() -> bool:
    path = _desktop_path()
    data = (_read_json(path) or {}) if path else {}
    return any(_is_ours(e) for e in (data.get("mcpServers") or {}).values())


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def read_deny_rule(root: Path) -> str:
    """Claude Code permission rule denying direct reads under ``root``.

    In Claude Code rules ``//`` marks an absolute path (``/x`` alone is relative
    to the settings file); a Windows drive ``C:\\x`` is written ``//c/x``.
    """
    posix = Path(root).as_posix()
    drive = re.match(r"([A-Za-z]):/?(.*)", posix)
    path = f"//{drive.group(1).lower()}/{drive.group(2)}" if drive else "/" + posix
    return f"Read({path.rstrip('/')}/**)"


def _too_broad_for_deny(root: Path) -> bool:
    """A deny rule on the home folder (or anything containing it, or a filesystem root)
    would stop Claude Code reading every project; it is only offered for a dedicated folder."""
    root = Path(root).resolve()
    home = Path.home().resolve()
    return root == home or home.is_relative_to(root) or root.parent == root


def plan_claude_read_deny(root: Path) -> Change:
    path = _claude_settings_path()
    rule = read_deny_rule(root)
    title, where = "Claude Code read rule", str(path)
    if _too_broad_for_deny(root):
        return Change("claude-code-deny", title, where,
                      f"Skipped: {root} is your home folder (or contains it), and a read rule there "
                      "would stop Claude Code reading every project. Use a dedicated folder for "
                      "configurations, e.g. `netconverter --workspace ~/migrations connect claude-code`.",
                      rule, can_apply=False, manual="Nothing was changed.")
    data = _read_json(path)
    permissions = data.get("permissions", {}) if isinstance(data, dict) else None
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else None
    if not isinstance(deny, list):
        block = json.dumps({"permissions": {"deny": [rule]}}, indent=2)
        return Change("claude-code-deny", title, where,
                      f"{path} could not be merged safely; add the deny rule by hand.",
                      block, can_apply=False, manual=f"Add {rule} to permissions.deny in {path}.")
    if rule in deny:
        return Change("claude-code-deny", title, where, f"{path} already denies {rule}.", rule,
                      can_apply=False, manual="Nothing to change.")
    after = json.loads(json.dumps(data))
    after.setdefault("permissions", {}).setdefault("deny", []).append(rule)

    def write() -> str:
        current = _read_json(path)  # re-read: never drop a change made since the preview
        if not isinstance(current, dict):
            raise RuntimeError(f"{path} is no longer valid JSON; nothing was changed")
        rules = current.setdefault("permissions", {}).setdefault("deny", [])
        if not isinstance(rules, list):
            raise RuntimeError(f"{path} permissions.deny is not a list; nothing was changed")
        if rule not in rules:
            rules.append(rule)
        _write_json(path, current)
        return (f"Claude Code will not read files in this folder directly ({rule}); "
                "it works on them through the bridge. Restart Claude Code to apply.")
    return Change("claude-code-deny", title, where,
                  "Stop Claude Code reading this folder's files directly. The bridge uploads "
                  "configurations by path, so the assistant never needs their text.",
                  _diff(path, data if path.exists() else None, after), apply=write, default_yes=True)


def _json_servers_configured(path: Path | None) -> bool:
    data = (_read_json(path) or {}) if path else {}
    servers = data.get("mcpServers") or {}
    return isinstance(servers, dict) and any(_is_ours(e) for e in servers.values())


def _gemini_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _windsurf_path() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


def _lmstudio_path() -> Path:
    return Path.home() / ".lmstudio" / "mcp.json"


def _exists(path_of: Callable[[], Path]) -> Callable[[], bool]:
    """Installed when the client's config folder exists (resolved per call, never at import)."""
    return lambda: path_of().parent.exists()


def _direct_server_names(servers: dict) -> list[str]:
    """Entries pointing an assistant straight at the NetConverter MCP server.

    The server honours only known apps (the bridge's own client and enrolled
    client-metadata URLs), so a desktop assistant's direct entry is refused with
    oauth_client_not_enrolled. Connecting the bridge replaces it.
    """
    hosts = {urlparse(remote_url()).hostname, "api.netconverter.ai"}
    names = []
    for name, entry in (servers or {}).items():
        if name == SERVER_NAME or not isinstance(entry, dict):
            continue
        url = entry.get("url") or entry.get("serverUrl")
        if isinstance(url, str) and urlparse(url).hostname in hosts:
            names.append(name)
    return sorted(names)


def _replacing(names: list[str]) -> str:
    if not names:
        return ""
    return (f" Removes the direct server entr{'y' if len(names) == 1 else 'ies'} "
            f"{', '.join(names)}: NetConverter refuses assistants that sign in directly, "
            f"and the bridge replaces {'it' if len(names) == 1 else 'them'}.")


def _plan_json_servers(key: str, title: str, path: Path, entry: dict, done: str) -> Change:
    """Merge mcpServers.netconverter into a client's JSON config, keeping every other key."""
    block = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)
    data = _read_json(path)
    if data is None or not isinstance(data.get("mcpServers", {}), dict):
        return Change(key, title, str(path),
                      f"{title}'s config is not valid JSON (or mcpServers is not an object); edit it by hand.",
                      block, can_apply=False, manual=f"Add the block above to {path}.")
    after = json.loads(json.dumps(data))
    direct = _direct_server_names(after.get("mcpServers"))
    for name in direct:
        after["mcpServers"].pop(name)
    after.setdefault("mcpServers", {})[SERVER_NAME] = entry

    def write() -> str:
        current = _read_json(path)  # re-read: never drop a change made since the preview
        if current is None or not isinstance(current.get("mcpServers", {}), dict):
            raise RuntimeError(f"{path} is no longer valid JSON; nothing was changed")
        for name in _direct_server_names(current.get("mcpServers")):
            current["mcpServers"].pop(name)
        current.setdefault("mcpServers", {})[SERVER_NAME] = entry
        _write_json(path, current)
        return f"Updated {path}. {done}"
    return Change(key, title, str(path),
                  f"Sets mcpServers.{SERVER_NAME} in {path}, keeping everything else (backup: .bak)."
                  + _replacing(direct),
                  _diff(path, data if path.exists() else None, after), apply=write)


def remote_url() -> str:
    from .remote_mcp import DEFAULT_MCP_URL
    return os.getenv("NETCONVERTER_MCP_URL", DEFAULT_MCP_URL).rstrip("/")


REMOTE_STEPS = {
    "chatgpt": (
        "ChatGPT",
        "In ChatGPT: Settings → Apps & Connectors → Advanced settings → turn on Developer mode, "
        "then Create (custom connector).\n"
        "  Name:            NetConverter\n"
        "  MCP server URL:  {url}\n"
        "  Authentication:  OAuth. Under advanced OAuth settings enter the NetConverter OAuth\n"
        "                   client ID your administrator gives you, then sign in with your\n"
        "                   NetConverter account when asked.\n"
        "Then enable NetConverter in a chat from the + menu (Developer mode)."),
    "claude-ai": (
        "claude.ai (web and mobile)",
        "On claude.ai: Settings → Connectors → Add custom connector.\n"
        "  Name:  NetConverter\n"
        "  URL:   {url}\n"
        "  Advanced settings → OAuth Client ID: the NetConverter OAuth client ID your\n"
        "  administrator gives you.\n"
        "Click Connect and sign in with your NetConverter account."),
}


def plan_remote(key: str) -> Change:
    title, steps = REMOTE_STEPS[key]
    url = remote_url()
    return Change(key, title, title,
                  f"{title} can only use remote MCP servers, so it connects to NetConverter's hosted "
                  "MCP rather than this folder's bridge. You get your jobs, results, account and "
                  "knowledge base; to submit a configuration, use a local client "
                  "(Claude Desktop, Claude Code, Cursor, Gemini CLI …) with this bridge. "
                  "Your NetConverter administrator must have MCP access enabled for your account.",
                  steps.format(url=url), can_apply=False,
                  manual="Follow the steps above in the app; nothing on this computer needs to change.")


def _vscode_configured(root: Path | None = None) -> bool:
    data = _read_json((root or Path.cwd()) / ".vscode" / "mcp.json") or {}
    return any(_is_ours(e) for e in (data.get("servers") or {}).values())


CLIENTS = {
    "claude-code": ClientSpec("Claude Code", _claude_configured,
                              installed=lambda: bool(shutil.which("claude")) or (Path.home() / ".claude.json").exists()),
    "claude-desktop": ClientSpec("Claude Desktop", _desktop_configured,
                                 installed=lambda: bool(_desktop_path()) and _desktop_path().parent.exists()),
    "cursor": ClientSpec("Cursor", _cursor_configured, installed=_exists(_cursor_path)),
    "vscode": ClientSpec("VS Code", _vscode_configured,
                         installed=lambda: bool(shutil.which("code"))),
    "codex": ClientSpec("Codex CLI", _codex_configured, installed=_exists(_codex_path)),
    "gemini": ClientSpec("Gemini CLI", lambda: _json_servers_configured(_gemini_path()),
                         installed=lambda: bool(shutil.which("gemini")) or _gemini_path().parent.exists()),
    "windsurf": ClientSpec("Windsurf", lambda: _json_servers_configured(_windsurf_path()),
                           installed=_exists(_windsurf_path)),
    "lmstudio": ClientSpec("LM Studio", lambda: _json_servers_configured(_lmstudio_path()),
                           installed=lambda: (Path.home() / ".lmstudio").exists()),
    "openclaw": ClientSpec("OpenClaw", lambda: _openclaw().current_entry() is not None
                           and _is_ours(_openclaw().current_entry()),
                           installed=lambda: _openclaw().installed()),
    "chatgpt": ClientSpec("ChatGPT", lambda: False, kind="remote"),
    "claude-ai": ClientSpec("claude.ai (web and mobile)", lambda: False, kind="remote"),
}


def _openclaw():
    from . import connect_openclaw
    return connect_openclaw


def plan_remove(key: str, root: Path) -> Change:
    """Undo `connect <client>`; only OpenClaw has a remove path so far (#14)."""
    if key == "openclaw":
        return _openclaw().plan_remove(Change)
    return Change(key, CLIENTS[key].title if key in CLIENTS else key, key,
                  f"--remove is not available for {key} yet; delete its '{SERVER_NAME}' entry by hand.",
                  "", can_apply=False, manual="Nothing was changed.")


def installed_local_clients() -> list[str]:
    """Local clients that look installed on this computer (for connect --all)."""
    out = []
    for key, spec in CLIENTS.items():
        if spec.kind != "local" or key == "vscode":  # VS Code is per folder, not per user
            continue
        try:
            if spec.installed():
                out.append(key)
        except Exception:
            continue
    return out


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
                      apply=run, followups=[plan_claude_read_deny(root)])
    if key == "claude-desktop":
        path = _desktop_path()
        entry = {"command": exe, "args": _args(root)}
        block = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)
        if path is None:
            return Change(key, "Claude Desktop", "Claude Desktop", "Claude Desktop runs on macOS and Windows only.",
                          block, can_apply=False, manual="Add the block above to claude_desktop_config.json.")
        data = _read_json(path)
        if data is None or not isinstance(data.get("mcpServers", {}), dict):
            return Change(key, "Claude Desktop", str(path),
                          "Claude Desktop's config is not valid JSON (or mcpServers is not an object); edit it by hand.",
                          block, can_apply=False, manual=f"Add the block above to {path}.")
        after = json.loads(json.dumps(data))
        after.setdefault("mcpServers", {})[SERVER_NAME] = entry

        def write() -> str:
            current = _read_json(path)
            if current is None or not isinstance(current.get("mcpServers", {}), dict):
                raise RuntimeError(f"{path} is no longer valid JSON; nothing was changed")
            current.setdefault("mcpServers", {})[SERVER_NAME] = entry
            _write_json(path, current)
            return f"Updated {path}. Quit and reopen Claude Desktop to load the netconverter tools."
        return Change(key, "Claude Desktop", str(path),
                      f"Sets mcpServers.{SERVER_NAME} in {path}, keeping everything else (backup: .bak).",
                      _diff(path, data if path.exists() else None, after), apply=write)
    if key == "gemini":
        return _plan_json_servers(key, "Gemini CLI", _gemini_path(), {"command": exe, "args": _args(root)},
                                  "Restart gemini, then run /mcp to see the netconverter tools.")
    if key == "windsurf":
        return _plan_json_servers(key, "Windsurf", _windsurf_path(), {"command": exe, "args": _args(root)},
                                  "Refresh MCP servers in Windsurf (Cascade → MCP) or restart it.")
    if key == "lmstudio":
        return _plan_json_servers(key, "LM Studio", _lmstudio_path(), {"command": exe, "args": _args(root)},
                                  "Restart LM Studio; use a tool-capable model to call the netconverter tools.")
    if key in REMOTE_STEPS:
        return plan_remote(key)
    if key == "openclaw":
        return _openclaw().plan(Change, root, exe, _args(root))
    if key == "cursor":
        path = _cursor_path()
        data = _read_json(path)
        entry = {"command": exe, "args": _args(root)}
        preview = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2)
        if data is None:
            return Change(key, "Cursor", str(path), "Cursor's mcp.json is not valid JSON; edit it by hand.",
                          preview, can_apply=False, manual=f"Add the block above to {path}.")

        direct = _direct_server_names(data.get("mcpServers"))

        def write() -> str:
            servers = data.setdefault("mcpServers", {})
            for name in _direct_server_names(servers):
                servers.pop(name)
            servers[SERVER_NAME] = entry
            _write_json(path, data)
            return f"Updated {path}. Cursor picks it up after a reload."
        return Change(key, "Cursor", str(path), f"Sets mcpServers.{SERVER_NAME} in {path}." + _replacing(direct),
                      preview, apply=write)
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
        if spec.kind != "local":
            continue
        try:
            ok = _vscode_configured(root) if key == "vscode" else spec.configured()
        except Exception:
            ok = False
        if ok:
            out.append(spec.title)
    return out
