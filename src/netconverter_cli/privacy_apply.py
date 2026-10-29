"""`netconverter privacy apply --client X`: keep an AI client's own file tools out of the folder (#13).

The bridge uploads a configuration by path, so an assistant never needs the
file's text; but most clients can also read files with their own tools when the
folder is in reach (tester MCP-C4). Where a client has a documented, mergeable
settings file the matching deny rules are written, after a diff and a yes, with
a ``.bak`` of what was replaced, and a second run changes nothing:

* Claude Code: ``Read``/``Edit`` rules in ``~/.claude/settings.json`` ``permissions.deny``;
* Cursor CLI: ``Read``/``Write`` rules in ``~/.cursor/cli-config.json`` ``permissions.deny``;
* Gemini CLI: a policy file of its own, ``~/.gemini/policies/netconverter-<id>.toml``.

Codex and OpenClaw get the exact settings printed instead: applying them would
change the client's active sandbox profile or agent policy, which is the user's call.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import connect
from .errors import EXIT_FAILURE

CLIENTS = ("claude-code", "cursor", "gemini", "codex", "openclaw")


@dataclass
class Plan:
    change: connect.Change
    notes: list = field(default_factory=list)
    guidance: bool = False      # printed settings only; nothing to apply is not a failure
    already: bool = False       # the rules are in place


def _outside_note(root: Path, title: str) -> str:
    return (f"Start {title} outside {root} (not in it or a parent folder): a client started there can "
            "reach the files through its project tools whatever its deny rules say. Run the bridge "
            "for the folder instead (`netconverter connect`).")


def plan(client: str, root: Path) -> Plan:
    root = Path(root).resolve()
    builders = {"claude-code": _claude_code, "cursor": _cursor, "gemini": _gemini,
                "codex": _codex, "openclaw": _openclaw}
    if client not in builders:
        raise ValueError(f"Unknown client {client!r}; choose one of {', '.join(CLIENTS)}")
    return builders[client](root)


# -- Claude Code -----------------------------------------------------------------

def _claude_code(root: Path) -> Plan:
    change = connect.plan_claude_read_deny(root, [connect.read_deny_rule(root), connect.edit_deny_rule(root)])
    change.title = "Claude Code file rules"
    notes = [
        "Claude Code's Bash tool is not covered: a deny rule matches a command prefix and cannot cover every "
        "way to read a file. Keep Bash on ask for this folder; the tester's stricter option is "
        "\"Bash(cat:*)\" in permissions.deny, which blocks cat everywhere.",
        _outside_note(root, "Claude Code"),
    ]
    return Plan(change, notes, already=change.manual == "Nothing to change.")


# -- Cursor CLI ------------------------------------------------------------------

def _cursor(root: Path) -> Plan:
    path = Path.home() / ".cursor" / "cli-config.json"
    posix = root.as_posix().rstrip("/")
    wanted = [f"Read({posix}/**)", f"Write({posix}/**)"]
    title, where = "Cursor CLI file rules", str(path)
    notes = [
        f"Cursor (editor and CLI) also honours a .cursorignore in the project it opens: add a line "
        f"\"{posix}/\" to that project's .cursorignore if the folder sits inside it.",
        "Shell commands are not covered by these rules; the tester's stricter option is \"Shell(cat)\" in "
        "permissions.deny, which blocks cat everywhere.",
        _outside_note(root, "Cursor"),
    ]
    if not path.parent.is_dir():
        change = connect.Change("cursor-deny", title, where, "Cursor CLI is not set up on this computer.",
                                json.dumps({"permissions": {"deny": wanted}}, indent=2), can_apply=False,
                                manual=f"After installing the Cursor CLI, add the rules above to {path}.")
        return Plan(change, notes)
    return _json_plan(path, wanted, title, notes)


def _json_plan(path: Path, wanted: list[str], title: str, notes: list) -> Plan:
    data = connect._read_json(path)
    deny = (data.get("permissions") or {}).get("deny", []) if isinstance(data, dict) and \
        isinstance(data.get("permissions", {}), dict) else None
    if not isinstance(deny, list):
        change = connect.Change("cursor-deny", title, str(path), f"{path} could not be merged safely.",
                                json.dumps({"permissions": {"deny": wanted}}, indent=2), can_apply=False,
                                manual=f"Add the rules above to permissions.deny in {path} by hand.")
        return Plan(change, notes)
    if all(rule in deny for rule in wanted):
        change = connect.Change("cursor-deny", title, str(path), f"{path} already denies {', '.join(wanted)}.",
                                ", ".join(wanted), can_apply=False, manual="Nothing to change.")
        return Plan(change, notes, already=True)
    after = json.loads(json.dumps(data))
    rules = after.setdefault("permissions", {}).setdefault("deny", [])
    rules.extend(rule for rule in wanted if rule not in rules)

    def write() -> str:
        current = connect._read_json(path)  # re-read: never drop a change made since the preview
        if not isinstance(current, dict) or not isinstance(current.get("permissions", {}), dict):
            raise RuntimeError(f"{path} changed and cannot be merged; nothing was changed")
        rules = current.setdefault("permissions", {}).setdefault("deny", [])
        if not isinstance(rules, list):
            raise RuntimeError(f"{path} permissions.deny is not a list; nothing was changed")
        rules.extend(rule for rule in wanted if rule not in rules)
        connect._write_json(path, current)
        return f"Updated {path}. Restart the Cursor CLI to apply."
    change = connect.Change("cursor-deny", title, str(path),
                            "Stop Cursor's own read and write tools touching this folder's files.",
                            connect._diff(path, data if path.exists() else None, after), apply=write)
    return Plan(change, notes)


# -- Gemini CLI ------------------------------------------------------------------

GEMINI_TOOLS = ("read_file", "read_many_files", "write_file", "replace", "glob", "list_directory",
                "search_file_content", "grep_search", "run_shell_command")


def _regex_literal(text: str) -> str:
    """A regex matching ``text`` literally, with only the metacharacters escaped (JavaScript RegExp safe)."""
    return "".join("\\" + ch if ch in ".^$*+?()[]{}|\\" else ch for ch in text)


def _gemini_policy(root: Path) -> str:
    pattern = _regex_literal(root.as_posix().rstrip("/"))
    lines = [f"# Written by `netconverter privacy apply --client gemini` for {root}.",
             "# Gemini CLI's own file and shell tools may not touch this folder; the NetConverter",
             "# bridge (netconverter mcp) uploads configurations by path.", ""]
    for tool in GEMINI_TOOLS:
        lines += ["[[rule]]", f'toolName = "{tool}"', f"argsPattern = '{pattern}'", 'decision = "deny"',
                  "priority = 900",
                  'denyMessage = "This folder is reached only through the netconverter MCP tools."', ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _gemini(root: Path) -> Plan:
    folder = Path.home() / ".gemini" / "policies"
    path = folder / f"netconverter-{hashlib.sha256(str(root).encode()).hexdigest()[:12]}.toml"
    title, where = "Gemini CLI policy", str(path)
    notes = [f"Gemini CLI also honours a .geminiignore in the project it opens: add a line \"{root.as_posix()}/\" "
             "there if the folder sits inside it. A shell command that names a file by a relative path "
             "is not matched by the policy.", _outside_note(root, "Gemini CLI")]
    if "'" in str(root) or "\n" in str(root):
        change = connect.Change("gemini-deny", title, where, "This folder's path cannot be written into a "
                                "TOML literal string.", "", can_apply=False,
                                manual="Use a folder whose path has no quote characters.")
        return Plan(change, notes)
    content = _gemini_policy(root)
    try:
        before = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        before = None
    except OSError as exc:
        change = connect.Change("gemini-deny", title, where, f"{path} cannot be read ({exc.strerror}).",
                                content, can_apply=False, manual=f"Write the policy above to {path} by hand.")
        return Plan(change, notes)
    if before == content:
        change = connect.Change("gemini-deny", title, where, f"{path} is already in place.", str(path),
                                can_apply=False, manual="Nothing to change.")
        return Plan(change, notes, already=True)
    diff = "".join(difflib.unified_diff((before or "").splitlines(keepends=True),
                                        content.splitlines(keepends=True),
                                        "/dev/null" if before is None else str(path), str(path)))

    def write() -> str:
        folder.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        fd, name = tempfile.mkstemp(prefix=".nc-", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        return f"Wrote {path}. Restart gemini to apply."
    change = connect.Change("gemini-deny", title, where,
                            "Deny Gemini CLI's own file and shell tools any path in this folder.", diff,
                            apply=write)
    return Plan(change, notes)


# -- Codex and OpenClaw: printed settings ----------------------------------------------

def _codex(root: Path) -> Plan:
    path = Path.home() / ".codex" / "config.toml"
    block = ("default_permissions = \"netconverter\"   # top level, before any [table]\n\n"
             "[permissions.netconverter]\nextends = \":workspace\"\n\n"
             f"[permissions.netconverter.filesystem]\n{json.dumps(str(root))} = \"deny\"")
    manual = (f"Add this to {path} yourself. It makes the profile active for every Codex session, and Codex "
              "ignores permission profiles while sandbox_mode or [sandbox_workspace_write] is set; if you "
              "already use a profile, add only the \"deny\" line to its filesystem table. The tester verified "
              "that the deny line blocks Codex's shell while the bridge still reads the folder.")
    change = connect.Change("codex-deny", "Codex CLI permission profile", str(path),
                            "Deny Codex's own sandbox access to this folder (permission profile).",
                            block, can_apply=False, manual=manual)
    return Plan(change, [_outside_note(root, "Codex")], guidance=True)


def _openclaw(root: Path) -> Plan:
    block = ("// ~/.openclaw/openclaw.json: for the agent that has the netconverter MCP server\n"
             "{\n  tools: {\n    deny: [\"read\", \"exec\"],\n    fs: { workspaceOnly: true },\n  },\n"
             "  sandbox: { workspaceAccess: \"none\" },\n}")
    manual = (f"Give that OpenClaw agent a workspace other than {root}, then merge the settings above into its "
              "Gateway config (OpenClaw's own tool policy) and restart the Gateway. The agent then reaches "
              "the folder only through the netconverter tools.")
    change = connect.Change("openclaw-deny", "OpenClaw tool policy", "OpenClaw Gateway config",
                            "Keep OpenClaw's own read and exec tools away from this folder.", block,
                            can_apply=False, manual=manual)
    return Plan(change, [_outside_note(root, "OpenClaw")], guidance=True)


# -- command -----------------------------------------------------------------------

def run(root: Path, args, ask) -> int:
    result = plan(args.client, root)
    change = result.change
    print(f"{change.title}: {change.summary}\n\n{change.preview}\n")
    for note in result.notes:
        print(f"- {note}")
    print()
    if getattr(args, "print_only", False):
        return 0
    if not change.can_apply:
        print(change.manual)
        return 0 if (result.guidance or result.already) else EXIT_FAILURE
    if not args.yes and str(ask(f"Apply to {change.where}? [y/N] ")).strip().lower() not in {"y", "yes"}:
        print("Nothing was changed.")
        return 0
    try:
        print(change.apply())
    except Exception as exc:  # noqa: BLE001 - shown, nothing half-written (atomic writes)
        print(f"Could not apply: {exc}")
        return EXIT_FAILURE
    return 0
